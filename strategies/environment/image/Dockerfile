# Alpine 目标构建环境：在 flange 内建镜像（内核/U-Boot 的 gcc-10、qemu、成像工具）之上
# 增加 apk.static 与 Alpine musl 目标 SDK。编译器复用内建镜像随 Swift 提供的
# clang/lld（/opt/swift-embedded），不再安装第二套 LLVM。SDK 独立于最终 rootfs。
FROM flange-build:latest

ARG ALPINE_MIRROR=https://dl-cdn.alpinelinux.org/alpine
ARG ALPINE_BRANCH=v3.24
ARG APK_STATIC=apk-tools-static-3.0.9-r0.apk
ARG APK_STATIC_SHA256=0a1a0682375f66a83b7b903f6e4638ccfe312547d50d336b5f2be9fc391281be
ARG ALPINE_KEYS=alpine-keys-2.6-r0.apk
ARG ALPINE_KEYS_SHA256=dd211936d544f4050924ce8aec078d24e7b1b036ae70b30bd07867349587c708

# apk.static 与签名公钥：按摘要校验后解包，之后所有 Alpine 索引都验签。
RUN set -eu; mkdir -p /tmp/apkboot /opt/flange-alpine; cd /tmp/apkboot \
    && curl -fsSLO "${ALPINE_MIRROR}/${ALPINE_BRANCH}/main/x86_64/${APK_STATIC}" \
    && curl -fsSLO "${ALPINE_MIRROR}/${ALPINE_BRANCH}/main/x86_64/${ALPINE_KEYS}" \
    && echo "${APK_STATIC_SHA256}  ${APK_STATIC}" | sha256sum -c - \
    && echo "${ALPINE_KEYS_SHA256}  ${ALPINE_KEYS}" | sha256sum -c - \
    && tar -xzf "${APK_STATIC}" -C /opt/flange-alpine sbin/apk.static 2>/dev/null \
    && tar -xzf "${ALPINE_KEYS}" -C /opt/flange-alpine usr/share/apk/keys 2>/dev/null \
    && ln -s /opt/flange-alpine/sbin/apk.static /usr/local/bin/apk.static \
    && apk.static --version \
    && rm -rf /tmp/apkboot

# armv7 目标 SDK：musl 头文件/库、gcc 运行库（crt、libgcc）与 libstdc++。
# --no-scripts：只取文件，不在宿主执行目标架构维护脚本。
RUN set -eu; sdk=/opt/flange-sdk/armv7; mkdir -p "$sdk" /opt/flange-sdk-metadata \
    && apk.static --arch armv7 --root "$sdk" --initdb --no-scripts --no-cache \
        --keys-dir /opt/flange-alpine/usr/share/apk/keys/armv7 \
        -X "${ALPINE_MIRROR}/${ALPINE_BRANCH}/main" \
        -X "${ALPINE_MIRROR}/${ALPINE_BRANCH}/community" \
        add musl-dev gcc g++ libstdc++-dev linux-headers zlib-dev \
    && apk.static --root "$sdk" info -v | sort > /opt/flange-sdk-metadata/armv7-packages.txt \
    && cat /opt/flange-sdk-metadata/armv7-packages.txt

COPY wrappers/ /opt/flange-alpine/wrappers/
# llvm-objcopy 按 argv[0] 是否以 strip 结尾切换为 strip 行为，直接以链接名提供。
RUN set -eu; for tool in /opt/flange-alpine/wrappers/*; do \
        chmod 0755 "$tool"; ln -s "$tool" "/usr/local/bin/$(basename "$tool")"; \
    done \
    && ln -s /opt/swift-embedded/bin/llvm-objcopy /usr/local/bin/armv7-alpine-linux-musleabihf-strip \
    && armv7-alpine-linux-musleabihf-gcc --version
