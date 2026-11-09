"""Alpine Linux 发行版策略：minirootfs + apk + OpenRC。

基础系统与 Ubuntu 同样分两阶段：Phase 1 解压 SHA256 固定的 minirootfs 并在
qemu chroot 中 ``apk add``，结果按计划指纹缓存；Phase 2 由 flange 共用编排完成
内核模块、固件、overlay，本策略只负责 App 包安装、账号/主机名/串口/服务定制
与包清单导出。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from builder.chroot import ChrootContext
from builder.config.canonical import userspace_arch
from builder.config.schema import Map, Object, STRING, STRINGS
from builder.distro import DistroBackend
from builder.docker import BuildError
from builder.environment import environment_identity
from builder.graph import InputSpec, TaskPlan
from builder.locking import FileLock
from builder.rootfs_base import emulator_for
from builder.snapshot import TAR_METADATA_OPTIONS

#: 本层提供的完整构建环境：内建镜像 + apk.static + clang/lld + musl SDK。
BUILD_ENVIRONMENT = "alpine"

EXTENSION_SCHEMA = Object(
    {
        "release": STRING,
        "mirror": STRING,
        "repositories": STRINGS,
        "minirootfs": Map(STRING),
        "services": Map(STRINGS),
        "consoles": STRINGS,
    },
    ("release", "minirootfs"),
)

#: flange 用户态架构名 → Alpine 架构名。
_ARCH = {"armhf": "armv7", "aarch64": "aarch64", "x86_64": "x86_64", "riscv64": "riscv64"}
_DEFAULT_MIRROR = "https://dl-cdn.alpinelinux.org/alpine"
_SUDO_GROUP_RULE = "/etc/sudoers.d/00-flange-sudo-group"


def _settings(config: dict) -> dict:
    return (config.get("extensions") or {}).get("distro:alpine") or {}


def alpine_arch(config: dict) -> str:
    arch = userspace_arch(config)
    try:
        return _ARCH[arch]
    except KeyError:
        raise ValueError(f"Alpine 不支持用户态架构 {arch!r}") from None


def _branch(release: str) -> str:
    parts = release.split(".")
    if len(parts) < 2:
        raise ValueError(f"extensions.distro:alpine.release 必须形如 3.24.4：{release!r}")
    return f"v{parts[0]}.{parts[1]}"


def _tarball(config: dict) -> dict:
    settings = _settings(config)
    release = settings["release"]
    arch = alpine_arch(config)
    digest = settings["minirootfs"].get(userspace_arch(config))
    if not digest:
        raise ValueError(f"extensions.distro:alpine.minirootfs 缺少 {userspace_arch(config)} 的 SHA256")
    mirror = settings.get("mirror", _DEFAULT_MIRROR).rstrip("/")
    name = f"alpine-minirootfs-{release}-{arch}.tar.gz"
    return {
        "url": f"{mirror}/{_branch(release)}/releases/{arch}/{name}",
        "sha256": digest,
        "filename": name,
    }


def _repositories(config: dict) -> list[str]:
    settings = _settings(config)
    mirror = settings.get("mirror", _DEFAULT_MIRROR).rstrip("/")
    branch = _branch(settings["release"])
    return [f"{mirror}/{branch}/{name}" for name in settings.get("repositories", ["main"])]


class ApkDistro(DistroBackend):
    """Alpine 的基础系统、App 安装与系统定制。"""

    init_system = "openrc"
    package_format = "apk"

    # ── Phase 1 ──────────────────────────────────────────────

    def base_plan(self, config, component, context):
        settings = config.get(component) or {}
        emulator = emulator_for(config)
        inputs = [
            InputSpec.value("tarball", _tarball(config)),
            InputSpec.value(
                "apk",
                {
                    "packages": sorted(settings.get("packages") or []),
                    "repositories": _repositories(config),
                },
            ),
            InputSpec.value("distro", "alpine"),
            InputSpec.value("architecture", alpine_arch(config)),
            InputSpec.value("emulator", emulator),
            InputSpec.value(
                "environment",
                environment_identity(emulator=emulator, config=config, context=context),
            ),
        ]
        for filename in ("chroot.py", "snapshot.py", "source.py", "docker.py", "locking.py"):
            path = context.tool_root / "builder" / filename
            if path.is_file():
                inputs.append(InputSpec.file(f"recipe:{filename}", path))
        return TaskPlan("rootfs:base", "alpine-base-apk-v1", tuple(inputs), ())

    def build_base(self, plan, root, *, context, source, docker, status):
        tarball = source.ensure_download("rootfs", "alpine-minirootfs", plan.value("tarball"))
        docker.run_privileged(["tar", *TAR_METADATA_OPTIONS, "-xf", str(tarball), "-C", str(root)])
        emulator = plan.value("emulator")
        docker.run_privileged(["cp", f"/usr/bin/{emulator}", str(root / "usr/bin/")])
        apk = plan.value("apk")
        (root / "etc/apk/repositories").write_text("\n".join(apk["repositories"]) + "\n")

        # apk 缓存按架构与仓库身份隔离并跨工作区共享；/etc/apk/cache 只在构建期存在。
        cache = context.build_root / "cache/apk" / plan.value("architecture")
        cache.mkdir(parents=True, exist_ok=True)
        cache_mount = root / "etc/apk/cache"
        with FileLock(cache.with_name(f".{cache.name}.flange.lock")), ChrootContext(root, docker) as chroot:
            chroot.bind_mount(str(cache), cache_mount)
            status("apk update...")
            chroot.run(["apk", "update", "--no-progress"], label="apk update...")
            chroot.run(["apk", "upgrade", "--no-progress"], label="apk upgrade...")
            if apk["packages"]:
                chroot.run(
                    ["apk", "add", "--no-progress", *apk["packages"]],
                    label=f"安装 {len(apk['packages'])} 个 apk 包...",
                )
        if cache_mount.is_dir() and not cache_mount.is_symlink():
            cache_mount.rmdir()

    # ── Phase 2 ──────────────────────────────────────────────

    def install_apps(self, builder, root, config):
        names = builder._component_config(config).get("custom_packages") or []
        if not names:
            return
        if builder.app_report is None:
            raise BuildError("rootfs 缺少本次构建的 AppBuildReport")
        if not builder.app_report.validate():
            raise BuildError("App 产物已经变更或缺失，拒绝安装")
        packages = builder.app_report.runtime_packages_for(names)
        wrong = [package.path.name for package in packages if package.format != "apk"]
        if wrong:
            raise BuildError(f"Alpine rootfs 只能安装 apk 格式的 App 包：{', '.join(wrong)}")
        staging = root / "tmp/flange-apks"
        staging.mkdir(parents=True, exist_ok=True)
        for package in packages:
            shutil.copy2(package.path, staging)
        builder._status(f"安装 {len(packages)} 个 App apk")
        try:
            with ChrootContext(root, builder.docker) as chroot:
                chroot.run(
                    ["apk", "add", "--no-progress", "--no-network", "--allow-untrusted",
                     *[f"/tmp/flange-apks/{package.path.name}" for package in packages]],
                    label=f"apk add（{len(packages)} 个 App 包）...",
                )
        finally:
            shutil.rmtree(staging)

    def install_extra(self, builder, root, config):
        rootfs = builder._component_config(config)
        for field in ("extra_debs", "extra_apt_sources", "phase2_packages"):
            if rootfs.get(field):
                raise BuildError(f"Alpine 目标不支持 rootfs.{field}（APT/DEB 专有字段）")

    def customize(self, builder, root, config):
        self._write_sudo_group_rule(root)
        builder._configure_users(root, config)
        builder._install_hostname(root, config)
        self._configure_consoles(root, config)
        self._enable_services(root, config)
        # 这是最后一个需要 chroot 的步骤；qemu 模拟器不进 NAND 镜像。
        (root / "usr/bin" / emulator_for(config)).unlink(missing_ok=True)

    def export_packages(self, builder, root):
        """从 apk 数据库生成 ``名称<TAB>版本`` 清单，格式与 DEB 发行版一致。"""
        database = root / "lib/apk/db/installed"
        if not database.is_file():
            database = root / "usr/lib/apk/db/installed"
        entries = []
        name = version = None
        for line in database.read_text(encoding="utf-8").splitlines() + [""]:
            if line.startswith("P:"):
                name = line[2:]
            elif line.startswith("V:"):
                version = line[2:]
            elif not line and name:
                entries.append(f"{name}\t{version}")
                name = version = None
        manifest = root / "etc/flange/packages.manifest"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("".join(f"{entry}\n" for entry in sorted(entries)), encoding="utf-8")
        builder._packages_manifest = builder._work_dir / "packages.manifest"
        shutil.copy2(manifest, builder._packages_manifest)
        builder._status(f"已安装 {len(entries)} 个 apk 包")

    # ── 定制细节 ─────────────────────────────────────────────

    @staticmethod
    def _write_sudo_group_rule(root: Path) -> None:
        """Alpine 的 sudoers 默认只有注释掉的 wheel 规则；补上 flange 约定的 sudo 组。"""
        if not (root / "etc/sudoers").is_file():
            return
        path = root / _SUDO_GROUP_RULE.lstrip("/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("%sudo ALL=(ALL:ALL) ALL\n")
        os.chown(path, 0, 0)
        path.chmod(0o440)

    @staticmethod
    def _configure_consoles(root: Path, config: dict) -> None:
        """在 inittab 中为每个串口 console 启动 getty，替换 minirootfs 的 tty 行。"""
        consoles = _settings(config).get("consoles") or []
        if not consoles:
            return
        inittab = root / "etc/inittab"
        lines = [
            line for line in inittab.read_text().splitlines()
            if "/sbin/getty" not in line
        ]
        lines += [f"{tty}::respawn:/sbin/getty -L 0 {tty} vt100" for tty in consoles]
        inittab.write_text("\n".join(lines) + "\n")

    @staticmethod
    def _enable_services(root: Path, config: dict) -> None:
        services = _settings(config).get("services") or {}
        for level, names in services.items():
            runlevel = root / "etc/runlevels" / level
            runlevel.mkdir(parents=True, exist_ok=True)
            for name in names:
                if not (root / "etc/init.d" / name).is_file():
                    raise BuildError(f"OpenRC 服务 {name} 不存在（runlevel {level}）；检查包集合")
                link = runlevel / name
                if not link.is_symlink():
                    link.symlink_to(f"/etc/init.d/{name}")


def create_distro():
    return ApkDistro()
