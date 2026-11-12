"""只安装固定 SDK 的原始模块；拒绝 ABI 不一致，不改写 vermagic。"""
from pathlib import Path
import hashlib
import json
import re
import shutil
import sys


def vermagic(path: Path) -> bytes:
    values = re.findall(rb"(?:^|\x00)vermagic=([^\x00]+)", path.read_bytes())
    if len(values) != 1:
        raise ValueError(f"模块 vermagic 缺失或重复：{path}")
    return values[0]


def prepare(sdk: Path, output: Path) -> None:
    expected = vermagic(output / "abi_check.o")
    entries = json.loads((Path(__file__).parent / "modules.json").read_text())
    for name, entry in entries.items():
        source = sdk / entry["path"]
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"厂商模块 SHA256 不匹配：{source}")
        if vermagic(source) != expected:
            raise ValueError(f"厂商模块与目标内核 vermagic 不匹配：{source}")
    for name, entry in entries.items():
        shutil.copyfile(sdk / entry["path"], output / name)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]), Path(sys.argv[2]))
