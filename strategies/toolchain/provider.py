"""Alpine musl 用户态工具链；SDK 随构建环境镜像提供，镜像摘要进入 ABI 身份。"""

from builder.config.canonical import userspace_arch
from builder.toolchain import Toolchain

_TARGETS = {
    "armhf": ("armv7-alpine-linux-musleabihf", "armv7", "arm", "/opt/flange-sdk/armv7"),
}


def create_toolchain(config, context):
    arch = userspace_arch(config)
    if arch not in _TARGETS:
        raise ValueError(f"Alpine 构建环境尚未提供 {arch} 目标 SDK")
    triple, processor, family, sysroot = _TARGETS[arch]
    return Toolchain(
        arch, triple, processor, family,
        profile="alpine3.24",
        target_sysroot=sysroot,
        sdk_identity=f"alpine-v3.24-{processor}-musl-v1",
        sdk_source="environment",
    )
