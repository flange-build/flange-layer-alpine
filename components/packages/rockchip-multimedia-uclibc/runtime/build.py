"""固定官方 SDK 与运行库，交付私有 ABI 目录、固件与硬件自检程序。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from builder.file_tree import copy_entry, copy_tree
from builder.elf import read_elf_abi
from builder.locking import FileLock


ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = "/opt/rockchip-uclibc"
LIBRARIES = (
    "librockit.so", "librockchip_mpp.so", "librockchip_mpp.so.0",
    "librockchip_mpp.so.1", "librga.so", "librkaiq.so",
)
RUNTIME_LIBRARIES = (
    "ld-uClibc-1.0.31.so", "ld-uClibc.so.0", "ld-uClibc.so.1",
    "libuClibc-1.0.31.so", "libc.so.0", "libc.so.1", "libgcc_s.so.1",
    "libstdc++.so", "libstdc++.so.6", "libstdc++.so.6.0.25",
)


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(source: dict, cache: Path) -> Path:
    """校验已有缓存；下载使用临时文件，完整校验后原子发布。"""
    digest = source["sha256"]
    cache.mkdir(parents=True, exist_ok=True)
    result = cache / digest
    with FileLock(cache / "locks" / f"{digest}.lock"):
        if result.exists():
            if checksum(result) != digest:
                raise ValueError(f"源码缓存 SHA256 不匹配，请移除后重试：{result}")
            return result
        descriptor, temporary = tempfile.mkstemp(prefix="download-", dir=cache)
        try:
            with os.fdopen(descriptor, "wb") as output:
                with urllib.request.urlopen(source["url"], timeout=120) as response:
                    shutil.copyfileobj(response, output)
            if checksum(Path(temporary)) != digest:
                raise ValueError(f"下载文件 SHA256 不匹配：{source['url']}")
            os.chmod(temporary, 0o644)
            os.replace(temporary, result)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return result


def extract(archive: Path, destination: Path) -> None:
    """归档只解到当前 App 工作目录，拒绝越界路径和链接。"""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir()
    with tarfile.open(archive) as stream:
        stream.extractall(destination, filter="data")


def build() -> None:
    if os.environ.get("FLANGE_TARGET_ARCH") != "armhf":
        raise ValueError("此厂商 SDK 仅支持 RV1106/ARM hard-float 用户态")
    work = Path(os.environ["FLANGE_APP_WORK_DIR"])
    cache = Path(os.environ["FLANGE_BUILD_ROOT"]) / "sources/rockchip-multimedia-uclibc"
    specs = json.loads((ROOT / "sources.json").read_text())
    inputs = {name: fetch(source, cache) for name, source in specs.items()}
    extract(inputs["sdk"], work / "sdk")
    entries = list((work / "sdk").iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise ValueError("SDK 归档必须包含唯一顶层目录")
    sdk = entries[0]
    extract(inputs["runtime"], work / "runtime")
    install = Path(os.environ["DESTDIR"])
    runtime = install / RUNTIME_ROOT.lstrip("/")
    (runtime / "lib").mkdir(parents=True)
    for name in RUNTIME_LIBRARIES:
        copy_entry(work / "runtime/lib" / name, runtime / "lib" / name)
    libraries = runtime / "usr/lib"
    libraries.mkdir(parents=True)
    for name in LIBRARIES:
        copy_entry(sdk / "lib/uclibc" / name, libraries / name)
    headers = runtime / "usr/include"
    headers.mkdir(parents=True)
    for source in sorted((sdk / "include").glob("rk_*.h")):
        copy_entry(source, headers / source.name)
    for name in ("rockchip", "librga", "rkaiq"):
        copy_tree(sdk / "include" / name, headers / name)
    # strip 仅作用于隔离副本，保留符号链接；厂商原始输入仍由 SHA256 标识。
    for directory in (runtime / "lib", libraries):
        for source in directory.iterdir():
            if source.is_symlink():
                continue
            abi = read_elf_abi(source)
            if abi:
                subprocess.run([os.environ["STRIP"], "--strip-unneeded", str(source)], check=True)
                # uClibc 本身也携带可执行入口；统一重定位到私有加载器。
                if abi.interpreter:
                    subprocess.run([
                        "patchelf", "--set-interpreter", RUNTIME_ROOT + "/lib/ld-uClibc.so.0",
                        str(source),
                    ], check=True)
    binary = runtime / "bin/rockchip-multimedia-check"
    binary.parent.mkdir()
    # 只用厂商启动对象和运行库链接；不消费 Alpine 的 CRT、libc 或 C++ ABI。
    subprocess.run([
        os.environ["CC"], "--target=arm-linux-gnueabihf", "--sysroot=" + str(runtime),
        "-nostdlib",
        "-fno-stack-protector", "-fno-pie", "-Wl,-no-pie", "-O2",
        "-Wl,--dynamic-linker=" + RUNTIME_ROOT + "/lib/ld-uClibc.so.0",
        str(inputs["crt1.o"]), str(inputs["crti.o"]), str(inputs["crtbegin.o"]),
        str(ROOT / "check.c"), "-L" + str(runtime / "lib"),
        "-Wl,-rpath-link," + str(runtime / "lib"), "-l:libc.so.0", "-l:libgcc_s.so.1",
        str(inputs["crtend.o"]), str(inputs["crtn.o"]), "-o", str(binary),
    ], check=True)
    for name, source, extra in (
        ("rockchip-multimedia-encode", "encode.c", []),
        ("rockchip-multimedia-rga", "rga.c", ["-lrga"]),
    ):
        subprocess.run([
            os.environ["CC"], "--target=arm-linux-gnueabihf", "--sysroot=" + str(runtime),
            "-nostdlib", "-ffreestanding", "-fno-stack-protector", "-fno-pie",
            "-Wl,-no-pie", "-O2", "-I" + str(headers),
            "-Wl,--dynamic-linker=" + RUNTIME_ROOT + "/lib/ld-uClibc.so.0",
            str(inputs["crt1.o"]), str(inputs["crti.o"]), str(inputs["crtbegin.o"]),
            str(ROOT / source), "-L" + str(libraries), "-L" + str(runtime / "lib"),
            "-Wl,-rpath-link," + str(libraries), "-Wl,-rpath-link," + str(runtime / "lib"),
            "-lrockit", *extra, "-l:libc.so.0", "-l:libgcc_s.so.1",
            str(inputs["crtend.o"]), str(inputs["crtn.o"]), "-o", str(binary.parent / name),
        ], check=True)
    firmware = install / "lib/firmware/rockchip/rv1106-hpmcu.bin"
    firmware.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(inputs["hpmcu_wrap.bin"], firmware)
    launcher = install / "usr/bin/rockchip-uclibc-run"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    copy_entry(ROOT / "rockchip-uclibc-run", launcher)
    launcher.chmod(0o755)
    licenses = install / "usr/share/licenses/rockchip-multimedia-uclibc"
    licenses.mkdir(parents=True)
    for name in ("COPYING.LIB", "COPYING3", "COPYING.RUNTIME"):
        shutil.copy2(inputs[name], licenses / name)
    shutil.copy2(ROOT / "sources.json", licenses / "sources.json")
    shutil.copy2(sdk / "README_CN.md", licenses / "SDK-README.md")


if __name__ == "__main__":
    build()
