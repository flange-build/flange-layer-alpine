"""在宿主准备可复现的 RKNN 图片示例，并绘制板端返回的检测结果。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parent


def fetch(source: dict, destination: Path) -> None:
    """已有文件也校验；失败不发布半个模型。"""
    digest = source["sha256"]
    if destination.exists():
        with destination.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                raise ValueError(f"SHA256 不匹配，请检查或移走：{destination}")
        return
    descriptor, name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    temporary = Path(name)
    try:
        checksum = hashlib.sha256()
        with os.fdopen(descriptor, "wb") as output:
            with urllib.request.urlopen(source["url"], timeout=120) as response:
                while block := response.read(1024 * 1024):
                    checksum.update(block)
                    output.write(block)
        if checksum.hexdigest() != digest:
            raise ValueError(f"下载摘要不符：{source['url']}")
        os.chmod(temporary, 0o644)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def prepare(directory: Path, image_path: Path | None) -> None:
    from PIL import Image

    directory.mkdir(parents=True, exist_ok=True)
    sources = json.loads((ROOT / "sources.json").read_text())
    for name, source in sources.items():
        if name == "bus.jpg" and image_path is not None:
            continue
        fetch(source, directory / name)
    with Image.open(image_path or directory / "bus.jpg") as image:
        width, height = image.size
        if max(width, height) > 4096 or width * height * 3 > 16 * 1024 * 1024:
            raise ValueError("板端示例限制：每边最多 4096 像素，RGB 像素数据最多 16 MiB")
        image.convert("RGB").save(directory / "input.ppm")
    print(f"已准备模型和 {width}×{height} RGB 图片：{directory}")


def render(directory: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    result = json.loads((directory / "result.json").read_text())
    if result["schema_version"] != 1:
        raise ValueError("不支持的结果 schema_version")
    labels = (directory / "coco_80_labels_list.txt").read_text().splitlines()
    with Image.open(directory / "input.ppm") as image:
        if image.size != (result["width"], result["height"]):
            raise ValueError("结果尺寸与输入图片不符")
        drawing = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=16)
        for detection in result["detections"]:
            name = labels[detection["class_id"]]
            box = detection["box"]
            color = "#ffbf36" if name == "bus" else "#39ff83"
            drawing.rectangle(box, outline=color, width=3)
            position = (box[0], max(0, box[1] - 20))
            text = f"{name} {detection['score']:.1%}"
            drawing.rectangle(drawing.textbbox(position, text, font=font), fill=color)
            drawing.text(position, text, fill="black", font=font)
        image.save(directory / "result.png")
    print(f"已绘制 {len(result['detections'])} 个检测框：{directory / 'result.png'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "render"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--image", type=Path, help="prepare 时改用自己的图片")
    args = parser.parse_args()
    if args.action == "render" and args.image is not None:
        parser.error("render 使用已准备的 input.ppm，不接受 --image")
    if args.action == "prepare":
        prepare(args.directory, args.image)
    else:
        render(args.directory)


if __name__ == "__main__":
    main()
