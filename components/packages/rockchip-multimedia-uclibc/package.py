"""Luckfox RV1106 的独立 uClibc 多媒体运行环境。"""

PACKAGE = {
    "name": "rockchip-multimedia-uclibc",
    "description": "Rockit、MPP、RGA、RKAIQ 与私有 uClibc 运行时",
    "components": [
        {"type": "vendor", "name": "rockchip-multimedia-uclibc", "dir": "runtime"},
    ],
}
