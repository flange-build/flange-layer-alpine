"""私有多媒体运行时的配置、可信下载和包边界测试。"""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import subprocess

import pytest

from builder.app_spec import load_spec
from builder.config.registry import resolve_config
from builder.layers import LayerStack
from conftest import LAYER_ROOT, TOOL_ROOT, load_strategy


PACKAGE = LAYER_ROOT / "components/packages/rockchip-multimedia-uclibc"


@pytest.fixture
def media():
    return load_strategy(
        "components/packages/rockchip-multimedia-uclibc/runtime/build.py", "media_build"
    )


def test_multimedia_only_enabled_for_alpine_product():
    stack = LayerStack.load(TOOL_ROOT, [LAYER_ROOT])
    alpine = resolve_config("luckfox-pico-pro-max", "alpine", "release",
                            project_root=TOOL_ROOT, layer_stack=stack)
    ubuntu = resolve_config("luckfox-pico-pro-max", "default", "release",
                            project_root=TOOL_ROOT, layer_stack=stack)
    name = "rockchip-multimedia-uclibc"
    assert name in alpine["packages"]
    assert name in alpine["rootfs"]["custom_packages"]
    assert name in alpine["external_apps"]
    assert name not in ubuntu.get("packages", [])
    assert name not in ubuntu["rootfs"]["custom_packages"]


def test_package_declares_private_runtime_and_required_libraries(media):
    stack = LayerStack.load(TOOL_ROOT, [LAYER_ROOT])
    spec = load_spec(PACKAGE / "runtime", layer_stack=stack)
    assert spec.app.type == "vendor" and spec.app.arch == ["armhf"]
    assert spec.packaging.format == "apk"
    assert spec.packaging.isolated_runtime.root == "/opt/rockchip-uclibc"
    assert spec.packaging.isolated_runtime.loader == "lib/ld-uClibc.so.0"
    assert set(media.LIBRARIES) >= {
        "librockit.so", "librockchip_mpp.so.1", "librga.so", "librkaiq.so",
    }


def test_source_lock_covers_runtime_sdk_startup_and_licenses():
    sources = json.loads((PACKAGE / "runtime/sources.json").read_text())
    assert set(sources) == {
        "sdk", "runtime", "crt1.o", "crti.o", "crtn.o", "crtbegin.o", "crtend.o",
        "COPYING.LIB", "COPYING3", "COPYING.RUNTIME",
    }
    for source in sources.values():
        assert source["url"].startswith("https://")
        assert len(bytes.fromhex(source["sha256"])) == 32


def test_verified_download_can_be_reused_offline(media, tmp_path):
    source = tmp_path / "upstream"
    source.write_bytes(b"vendor bytes")
    descriptor = {"url": source.as_uri(), "sha256": media.checksum(source)}
    cached = media.fetch(descriptor, tmp_path / "cache")
    assert cached.read_bytes() == source.read_bytes()
    source.unlink()
    assert media.fetch(descriptor, tmp_path / "cache") == cached
    cached.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="缓存 SHA256"):
        media.fetch(descriptor, tmp_path / "cache")


def test_bad_download_is_not_published(media, tmp_path):
    source = tmp_path / "upstream"
    source.write_bytes(b"wrong bytes")
    cache = tmp_path / "cache"
    descriptor = {"url": source.as_uri(), "sha256": hashlib.sha256(b"expected").hexdigest()}
    with pytest.raises(ValueError, match="下载文件 SHA256"):
        media.fetch(descriptor, cache)
    assert not (cache / descriptor["sha256"]).exists()
    assert not list(cache.glob("download-*"))


def test_tar_extraction_rejects_escape(media, tmp_path):
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as stream:
        entry = tarfile.TarInfo("../escaped")
        entry.size = 1
        stream.addfile(entry, io.BytesIO(b"x"))
    with pytest.raises(tarfile.FilterError):
        media.extract(archive, tmp_path / "unpack")
    assert not (tmp_path / "escaped").exists()


def test_tar_extraction_preserves_library_links(media, tmp_path):
    archive = tmp_path / "good.tar"
    with tarfile.open(archive, "w") as stream:
        entry = tarfile.TarInfo("lib/libdemo.so.1")
        entry.size = 1
        stream.addfile(entry, io.BytesIO(b"x"))
        link = tarfile.TarInfo("lib/libdemo.so")
        link.type = tarfile.SYMTYPE
        link.linkname = "libdemo.so.1"
        stream.addfile(link)
    media.extract(archive, tmp_path / "unpack")
    link = tmp_path / "unpack/lib/libdemo.so"
    assert link.is_symlink() and link.readlink() == Path("libdemo.so.1")


@pytest.mark.parametrize("arguments", [[], ["/bin/sh"],
                                     ["/opt/rockchip-uclibc/bin/../../../../bin/sh"]])
def test_launcher_rejects_missing_or_nonprivate_program(arguments):
    result = subprocess.run(
        ["/bin/sh", str(PACKAGE / "runtime/rockchip-uclibc-run"), *arguments],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
