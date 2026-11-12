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


@pytest.mark.parametrize("variant", ["debug", "release"])
def test_multimedia_only_enabled_for_alpine_product(variant):
    stack = LayerStack.load(TOOL_ROOT, [LAYER_ROOT])
    alpine = resolve_config("luckfox-pico-pro-max", "alpine", variant,
                            project_root=TOOL_ROOT, layer_stack=stack)
    ubuntu = resolve_config("luckfox-pico-pro-max", "default", variant,
                            project_root=TOOL_ROOT, layer_stack=stack)
    core = resolve_config("luckfox-pico-pro-max", "default", variant,
                          project_root=TOOL_ROOT)
    name = "rockchip-multimedia-uclibc"
    assert name in alpine["packages"]
    assert name in alpine["rootfs"]["custom_packages"]
    assert name in alpine["external_apps"]
    assert "rockchip-multimedia-service" in alpine["rootfs"]["custom_packages"]
    assert alpine["kernel"]["source"] == ubuntu["kernel"]["source"] == core["kernel"]["source"]
    source_name = core["kernel"]["source"]["name"]
    assert alpine["sources"][source_name] == core["sources"][source_name]
    assert alpine["kernel"]["device_tree"] == core["kernel"]["device_tree"]
    assert ubuntu["kernel"]["device_tree"] == core["kernel"]["device_tree"]
    assert alpine["kernel"]["config"]["CONFIG_HIGH_RES_TIMERS"] == "y"
    assert core["kernel"]["config"]["CONFIG_ROCKCHIP_RKNPU"] == "m"
    assert core["kernel"]["config"]["CONFIG_ROCKCHIP_RKNPU_DMA_HEAP"] == "y"
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
        "librockit.so", "librockchip_mpp.so.1", "librga.so", "librkaiq.so", "librknnmrt.so",
    }


def test_source_lock_covers_runtime_sdk_startup_and_licenses():
    sources = json.loads((PACKAGE / "runtime/sources.json").read_text())
    assert set(sources) == {
        "sdk", "runtime", "crt1.o", "crti.o", "crtn.o", "crtbegin.o", "crtend.o",
        "COPYING.LIB", "COPYING3", "COPYING.RUNTIME", "hpmcu_wrap.bin",
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


@pytest.mark.parametrize("failure", ["checksum", "vermagic"])
def test_driver_install_rejects_incompatible_or_corrupt_module(tmp_path, monkeypatch, failure):
    driver = load_strategy(
        "components/packages/rockchip-multimedia-uclibc/driver/prepare.py", "media_driver"
    )
    sdk = tmp_path / "sdk"
    output = tmp_path / "output"
    sdk.mkdir()
    output.mkdir()
    good = b"\0vermagic=5.10.160 mod_unload ARMv7 thumb2 p2v8 \0"
    wrong = b"\0vermagic=6.1.115+ mod_unload ARMv7 thumb2 p2v8 \0"
    (output / "abi_check.o").write_bytes(good)
    (sdk / "driver.ko").write_bytes(wrong if failure == "vermagic" else good + b"changed")
    expected = wrong if failure == "vermagic" else good
    (tmp_path / "modules.json").write_text(json.dumps({"driver.ko": {
        "path": "driver.ko", "sha256": hashlib.sha256(expected).hexdigest(),
    }}))
    monkeypatch.setattr(driver, "__file__", str(tmp_path / "prepare.py"))
    with pytest.raises(ValueError, match="SHA256|vermagic"):
        driver.prepare(sdk, output)
    assert not (output / "driver.ko").exists()


def test_demo_download_rejects_corrupt_model_without_replacing_output(tmp_path):
    demo = load_strategy(
        "components/packages/rockchip-multimedia-uclibc/demo/demo.py", "rknn_demo"
    )
    source = tmp_path / "upstream"
    source.write_bytes(b"model")
    descriptor = {"url": source.as_uri(), "sha256": hashlib.sha256(b"model").hexdigest()}
    destination = tmp_path / "model.rknn"
    demo.fetch(descriptor, destination)
    assert destination.read_bytes() == b"model"
    source.unlink()
    demo.fetch(descriptor, destination)
    destination.write_bytes(b"damaged")
    with pytest.raises(ValueError, match="SHA256"):
        demo.fetch(descriptor, destination)
    assert destination.read_bytes() == b"damaged"
    destination.unlink()
    source.write_bytes(b"incorrect download")
    with pytest.raises(ValueError, match="摘要"):
        demo.fetch(descriptor, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".download-*"))
