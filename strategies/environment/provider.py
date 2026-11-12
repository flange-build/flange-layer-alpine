"""Alpine 完整构建环境：内建镜像 + apk.static + clang/lld + musl 目标 SDK。"""

from pathlib import Path

from builder.build_environment import BuildEnvironmentSpec


def create_environment(config, context):
    directory = Path(__file__).parent / "image"
    return BuildEnvironmentSpec(
        name="alpine",
        image="flange-alpine:3.24",
        dockerfile=directory / "Dockerfile",
        build_context=directory,
        toolchain="alpine",
        required_tools=(
            ("/usr/bin/patchelf", "patchelf"),
            ("/opt/arm-linux-gcc10/bin/arm-none-linux-gnueabihf-gcc", "10.3"),
            ("/usr/local/bin/armv7-alpine-linux-musleabihf-gcc", "clang version"),
            ("/usr/local/bin/apk.static", "apk-tools 3."),
        ),
    )
