# flange-layer-alpine

flange 的 Alpine Linux 发行版层：musl + apk + OpenRC + busybox。
基于 flange 的多层组合（`main` 分支，`docs/layers.md`），本层只提供发行版相关内容，
板级 BSP 留在 flange 核心。

## 提供的策略

| 种类 | 名称 | 内容 |
| --- | --- | --- |
| `distro` | `alpine` | Alpine 3.24 minirootfs（按架构 SHA256 固定）+ qemu chroot `apk add`；账号、主机名、串口 getty、OpenRC runlevel；apk 包清单 |
| `environment` | `alpine` | `flange-build` 镜像 + `apk.static`（摘要校验）+ 验签的 armv7 musl SDK；编译器复用镜像随 Swift 提供的 clang/lld |
| `toolchain` | `alpine` | `armv7-alpine-linux-musleabihf-*` 包装脚本，SDK 位于 `/opt/flange-sdk/armv7` |
| `packaging` | `apk` | `apk mkpkg` 生成 apk v3 包；OpenRC `auto_start` 经 post-install `rc-update add` |

发行版基线在 `components/distro/alpine/config.jsonnet`，不继承 Ubuntu 的包集合；
Alpine 专有参数在 `extensions['distro:alpine']`（版本、镜像站、minirootfs 摘要、runlevel 服务、串口）。

## 已支持的板卡

| 板卡 | product | 说明 |
| --- | --- | --- |
| `luckfox-pico-pro-max`（RV1106G2/G3） | `alpine` | SPI NAND + UBI rootfs，串口 `ttyFIQ0`，默认装 adbd + usbmoded |

其他板卡按同样方式在本层 `components/board/<board>/config.jsonnet` 追加 product：

```jsonnet
local product = std.extVar('product');
{ products+: ['alpine'] } + (if product == 'alpine' then {
  distro: 'alpine',
  extensions+: { 'distro:alpine'+: { consoles: ['ttyS0'] } },
  // 平台层追加的 Debian 包名与 DEB 形态 App 在 Alpine 上要重置
  rootfs+: { packages: [], custom_packages: ['adbd'] },
} else {})
```

依赖厂商 glibc 用户态（Mali、RGA/MPP、fastrpc、L4T 等）的功能在 musl 上不可用。

## 使用

工作区（示例 `../flange-alpine-ws/flange.toml`）：

```toml
schema_version = 2
tool_root = "../flange"
build_dir = ".build"
layers = ["../flange-layer-alpine"]
```

```bash
source ../flange/envsetup.sh
flange -C ../flange-alpine-ws layer check
flange -C ../flange-alpine-ws target select luckfox-pico-pro-max-alpine-release
flange -C ../flange-alpine-ws docker build      # 构建 flange-alpine:3.24 环境镜像
flange -C ../flange-alpine-ws build             # 完整镜像
flange -C ../flange-alpine-ws app build musl-check
```

## App 约定

- 服务 App 声明 `openrc.script`（安装到 `/etc/init.d/`），可与 `systemd.unit` 并存；
  构建时只打包目标 init 对应的文件。
- OpenRC 脚本 pidfile 用 `/run/<服务名>.pid`，日志写 `/var/log/<服务名>.log`，
  `flange app debug/log` 依赖这两个路径。
- apk 依赖用 `packaging.depends.apk` 声明；顶层 `depends` 是 Debian 包名，不用于 apk。
- `components/app/musl-check` 是端到端验证 App（C++、线程、动态 zlib）。

## 测试

```bash
FLANGE_TOOL_ROOT=../flange ../flange/.venv/bin/python -m pytest tests
```
