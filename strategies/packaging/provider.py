"""apk 包格式：apk-tools 3 的 ``apk mkpkg`` 生成包，设备与 rootfs 用 ``apk add`` 安装。

不需要 abuild 与签名密钥：flange 自产包在 rootfs 与设备上均以 ``--allow-untrusted``
安装。OpenRC 服务的 auto_start 由安装与升级脚本 ``rc-update add`` 实现，
rootfs 构建时该脚本在 qemu chroot 中执行。
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from builder.app_spec import AppSpec
from builder.file_tree import copy_entry
from builder.packaging.base import InstalledFile, PackageBackend
from builder.packaging.deb import DebPackageBackend
from builder.packaging.model import PackageOutput

#: 构建环境内的静态 apk-tools；只在容器内执行。
APK = "/usr/local/bin/apk.static"
_ARCH = {"armhf": "armv7", "aarch64": "aarch64", "x86_64": "x86_64", "riscv64": "riscv64"}


def _run(command: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(
            f"命令失败 (exit {result.returncode}): {shlex.join(command)}\n{result.stderr.strip()}"
        )
    return result


class ApkPackageBackend(PackageBackend):
    format = "apk"

    def validate_output(self, output: PackageOutput) -> None:
        if not output.file.endswith(".apk"):
            raise ValueError(f"apk 输出必须使用 .apk 后缀：{output.file!r}")

    @staticmethod
    def _names(spec: AppSpec) -> list[tuple[str, str]]:
        name = f"lib{spec.app.name}" if spec.app.type == "lib" else spec.app.name
        names = [(name, "runtime")]
        if spec.app.type == "lib":
            names.append((name + (spec.lib.dev_suffix if spec.lib else "-dev"), "development"))
        return names

    def plan(self, spec: AppSpec, arch: str) -> tuple[PackageOutput, ...]:
        if spec.app.type in {"staging", "amp"}:
            return ()
        if spec.packaging.outputs:
            return tuple(spec.packaging.outputs)
        return tuple(
            PackageOutput(f"{name}-{spec.app.version}.apk", role)
            for name, role in self._names(spec)
        )

    def build(
        self, spec: AppSpec, arch: str, files: Sequence[InstalledFile], output: Path
    ) -> None:
        if spec.app.type == "staging":
            return
        if spec.maintainer_scripts:
            raise ValueError("apk 包不支持 Debian maintainer_scripts；请改用 OpenRC 与 data_dirs")
        depends = list(spec.packaging.depends.get("apk", []))
        if spec.app.type != "lib":
            self._mkpkg(spec, spec.app.name, arch, files, depends, output, scripts=True)
            return
        (runtime_name, _), (development_name, _) = self._names(spec)
        runtime, development = [], []
        for entry in files:
            target = development if DebPackageBackend._is_development(entry) else runtime
            target.append(entry)
        self._mkpkg(spec, runtime_name, arch, runtime, depends, output, scripts=False)
        self._mkpkg(
            spec, development_name, arch, development,
            [f"{runtime_name}={spec.app.version}"], output, scripts=False,
        )

    def _scripts(self, spec: AppSpec) -> dict[str, str]:
        install, remove = [], []
        for directory in spec.data_dirs:
            install.append(f"mkdir -p {shlex.quote(directory)}")
        openrc = spec.openrc
        if spec.app.type == "service" and openrc:
            service = shlex.quote(Path(openrc.script).name)
            if openrc.auto_start:
                runlevel = shlex.quote(openrc.runlevel)
                install.append(f"mkdir -p /etc/runlevels/{runlevel}")
                install.append(f"rc-update add {service} {runlevel}")
            remove.append(f"rc-service {service} stop >/dev/null 2>&1 || true")
            remove.append(f"rc-update --all del {service} >/dev/null 2>&1 || true")
        scripts = {}
        if install:
            content = "\n".join(["#!/bin/sh", "set -xe", *install, ""])
            scripts.update({"post-install": content, "post-upgrade": content})
        if remove:
            scripts["pre-deinstall"] = "\n".join(["#!/bin/sh", "set -xe", *remove, ""])
        return scripts

    def _mkpkg(
        self,
        spec: AppSpec,
        name: str,
        arch: str,
        files: Sequence[InstalledFile],
        depends: list[str],
        output: Path,
        *,
        scripts: bool,
    ) -> None:
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="apk-", dir=output.parent) as temporary:
            # mkpkg 按磁盘上的属主与权限记录每个目录（含根目录）的 ACL：
            # 目录统一 0755、全部属主 root，不能把临时目录的 0700 带进设备。
            root = Path(temporary) / "root"
            root.mkdir(mode=0o755)
            for source, destination, mode in files:
                target = root / destination.lstrip("/")
                copy_entry(source, target)
                if not target.is_symlink():
                    target.chmod(mode)
            for path in [root, *root.rglob("*")]:
                os.lchown(path, 0, 0)
                if path.is_dir() and not path.is_symlink():
                    path.chmod(0o755)
            command = [
                APK, "mkpkg",
                "--files", str(root),
                "--output", str(output / f"{name}-{spec.app.version}.apk"),
                "--info", f"name:{name}",
                "--info", f"version:{spec.app.version}",
                "--info", f"arch:{self.architecture(arch)}",
                "--info", f"description:{spec.app.description}",
                "--info", f"maintainer:{spec.maintainer.name} <{spec.maintainer.email}>",
            ]
            if depends:
                command += ["--info", "depends:" + " ".join(depends)]
            for kind, content in (self._scripts(spec) if scripts else {}).items():
                script = Path(temporary) / kind
                script.write_text(content)
                script.chmod(0o755)
                command += ["--script", f"{kind}:{script}"]
            _run(command)

    def import_outputs(
        self,
        outputs: Sequence[PackageOutput],
        arch: str,
        output: Path,
        install: Path,
        runner,
    ) -> set[str]:
        runtime_paths = set()
        for item in outputs:
            package = output / item.file
            if package.is_symlink() or not package.is_file():
                raise ValueError(f"缺少声明的包产物或包不是普通文件：{package}")
            with tempfile.TemporaryDirectory(prefix="unpack-", dir=install.parent) as temporary:
                index = Path(temporary) / "index.adb"
                runner.run([APK, "mkndx", "--allow-untrusted", "--output", str(index), str(package)])
                inspected = runner.run([APK, "adbdump", "--format", "json", str(index)], capture=True)
                try:
                    metadata = json.loads(inspected.stdout)["packages"]
                    if not isinstance(metadata, list) or len(metadata) != 1:
                        raise ValueError("索引必须包含一个包")
                    actual = metadata[0]["arch"]
                except (ValueError, KeyError, TypeError) as error:
                    raise ValueError(f"APK 架构元数据无效：{item.file}") from error
                expected = self.architecture(arch)
                if actual not in (expected, "noarch"):
                    raise ValueError(f"APK 架构不匹配：{item.file} 是 {actual}，目标为 {expected}")
                extracted = Path(temporary) / "root"
                extracted.mkdir()
                runner.run([APK, "extract", "--allow-untrusted", "--destination", str(extracted),
                            str(package)])
                paths = DebPackageBackend._merge(extracted, install)
                if item.role == "runtime":
                    runtime_paths.update(paths)
        return runtime_paths

    def architecture(self, arch: str) -> str:
        try:
            return _ARCH[arch]
        except KeyError:
            raise ValueError(f"apk 不支持架构 {arch!r}") from None

    def architecture_command(self) -> list[str]:
        return ["apk", "--print-arch"]

    def install_command(self, paths: Sequence[str]) -> list[str]:
        return ["apk", "add", "--allow-untrusted", *paths]

    def recipe_paths(self) -> tuple[Path, ...]:
        return (Path(__file__).resolve(),)


def create_backend():
    return ApkPackageBackend()
