"""Alpine 发行版策略的纯逻辑测试；不启动 Docker。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from builder.docker import BuildError


def _config(**settings):
    alpine = {
        "release": "3.24.4",
        "minirootfs": {"armhf": "a" * 64},
        **settings,
    }
    return {
        "distro": "alpine",
        "architecture": {"userspace": "armhf", "kernel": "arm", "bootloader": "arm"},
        "extensions": {"distro:alpine": alpine},
        "rootfs": {"packages": ["openrc", "busybox"]},
    }


def test_minirootfs_url_follows_release_branch_and_alpine_arch(distro):
    tarball = distro._tarball(_config())

    assert tarball == {
        "url": "https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/armv7/"
               "alpine-minirootfs-3.24.4-armv7.tar.gz",
        "sha256": "a" * 64,
        "filename": "alpine-minirootfs-3.24.4-armv7.tar.gz",
    }


def test_missing_arch_digest_is_rejected(distro):
    config = _config(minirootfs={"aarch64": "b" * 64})

    with pytest.raises(ValueError, match="armhf"):
        distro._tarball(config)


def test_repositories_use_same_branch(distro):
    assert distro._repositories(_config(repositories=["main", "community"])) == [
        "https://dl-cdn.alpinelinux.org/alpine/v3.24/main",
        "https://dl-cdn.alpinelinux.org/alpine/v3.24/community",
    ]


def test_extension_schema_rejects_unknown_fields(distro):
    with pytest.raises(ValueError, match="未知字段"):
        distro.EXTENSION_SCHEMA.check({**_config()["extensions"]["distro:alpine"], "x": 1}, "e")


def test_package_manifest_parsed_from_apk_database(distro, tmp_path):
    root = tmp_path / "root"
    database = root / "lib/apk/db/installed"
    database.parent.mkdir(parents=True)
    database.write_text(
        "C:Q1abc=\nP:musl\nV:1.2.6-r3\nA:armv7\n\n"
        "C:Q1def=\nP:busybox\nV:1.37.0-r31\nA:armv7\n"
    )
    work = tmp_path / "work"
    work.mkdir()
    builder = SimpleNamespace(_work_dir=work, _status=lambda message: None)

    distro.ApkDistro().export_packages(builder, root)

    expected = "busybox\t1.37.0-r31\nmusl\t1.2.6-r3\n"
    assert (root / "etc/flange/packages.manifest").read_text() == expected
    assert builder._packages_manifest.read_text() == expected


def test_consoles_replace_minirootfs_getty_lines(distro, tmp_path):
    inittab = tmp_path / "etc/inittab"
    inittab.parent.mkdir(parents=True)
    inittab.write_text(
        "::sysinit:/sbin/openrc sysinit\n"
        "tty1::respawn:/sbin/getty 38400 tty1\n"
        "::shutdown:/sbin/openrc shutdown\n"
    )

    distro.ApkDistro._configure_consoles(tmp_path, _config(consoles=["ttyFIQ0"]))

    assert inittab.read_text() == (
        "::sysinit:/sbin/openrc sysinit\n"
        "::shutdown:/sbin/openrc shutdown\n"
        "ttyFIQ0::respawn:/sbin/getty -L 0 ttyFIQ0 vt100\n"
    )


def test_services_are_linked_into_runlevels(distro, tmp_path):
    (tmp_path / "etc/init.d").mkdir(parents=True)
    (tmp_path / "etc/init.d/sshd").write_text("#!/sbin/openrc-run\n")

    distro.ApkDistro._enable_services(tmp_path, _config(services={"default": ["sshd"]}))

    link = tmp_path / "etc/runlevels/default/sshd"
    assert link.is_symlink() and str(Path(link.readlink())) == "/etc/init.d/sshd"


def test_missing_service_fails_build(distro, tmp_path):
    (tmp_path / "etc/init.d").mkdir(parents=True)

    with pytest.raises(BuildError, match="sshd"):
        distro.ApkDistro._enable_services(tmp_path, _config(services={"default": ["sshd"]}))


def test_apt_only_fields_are_rejected(distro):
    builder = SimpleNamespace(_component_config=lambda config: config["rootfs"])
    config = _config()
    config["rootfs"]["extra_debs"] = [{"name": "x"}]

    with pytest.raises(BuildError, match="extra_debs"):
        distro.ApkDistro().install_extra(builder, Path("/nonexistent"), config)
