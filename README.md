# flange-layer-alpine

flange 的 Alpine Linux 发行版层：musl + apk + OpenRC + busybox。
基于 flange 的多层组合（`main` 分支，`docs/layers.md`），本层只提供发行版相关内容，
板级 BSP 留在 flange 核心；RV1106 的 Ubuntu 与 Alpine 产品共用核心提供的 5.10.160 内核。

## 提供的策略

| 种类 | 名称 | 内容 |
| --- | --- | --- |
| `distro` | `alpine` | Alpine 3.24 minirootfs（按架构 SHA256 固定）+ qemu chroot `apk add`；账号、主机名、串口 getty、OpenRC runlevel；apk 包清单 |
| `environment` | `alpine` | `flange-build` 镜像 + `apk.static`（摘要校验）+ 验签的 armv7 musl SDK + patchelf；编译器复用镜像随 Swift 提供的 clang/lld |
| `toolchain` | `alpine` | `armv7-alpine-linux-musleabihf-*` 包装脚本，SDK 位于 `/opt/flange-sdk/armv7` |
| `packaging` | `apk` | `apk mkpkg` 生成 apk v3 包；导入时校验包架构；OpenRC 安装和升级时兑现 `auto_start` |

发行版基线在 `components/distro/alpine/config.jsonnet`，不继承 Ubuntu 的包集合；
Alpine 专有参数在 `extensions['distro:alpine']`（版本、镜像站、minirootfs 摘要、runlevel 服务、串口）。

## 已支持的板卡

| 板卡 | product | 说明 |
| --- | --- | --- |
| `luckfox-pico-pro-max`（RV1106G2/G3） | `alpine` | SPI NAND + UBI rootfs，串口 `ttyFIQ0`，默认装 adbd、usbmoded 和独立 uClibc 多媒体运行时 |

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

RV1106 的 Rockit、MPP、RGA、RKAIQ、RKNN 通过[独立 uClibc 多媒体包](components/packages/rockchip-multimedia-uclibc/README.md)
运行在 Alpine 上。厂商库与 uClibc 位于 `/opt/rockchip-uclibc`，应用使用匹配的 uClibc ABI；
系统和常规 App 继续使用 musl。其他 SoC、Mali、fastrpc、L4T 不在该包支持范围内。
已在 RV1106G3 Max 上验证五库加载、MPI 连续内存、H.264 硬件编码、RGA 图像复制/缩放及 NPU YOLOv5 图片推理；
摄像头与 RKAIQ 算法尚待传感器验收，MCU 卷绕功能关闭。详见上述包说明的实机验证表。

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
flange -C ../flange-alpine-ws app build rockchip-multimedia-uclibc
```

需要配套 flange 的 RV1106 5.10.160 BSP、`packaging.isolated_runtime` 和源码子目录补丁支持。
已有构建环境须重新运行 `docker build` 安装 patchelf。库的用法、产物和验证范围见
[多媒体包说明](components/packages/rockchip-multimedia-uclibc/README.md)。

## App 约定

- 服务 App 声明 `openrc.script`（安装到 `/etc/init.d/`），可与 `systemd.unit` 并存；
  构建时只打包目标 init 对应的文件。
  选中 Alpine target 后，`flange app/package create --type service` 生成 OpenRC 脚本和声明；
  原生服务文件名不做架构后缀裁剪，`camera-armhf` 仍安装为同名服务。
- 安装和升级都会创建 `data_dirs`；`auto_start: true` 将服务加入声明的 runlevel。
  注册前创建 runlevel 目录，支持基础系统尚未定义的自定义级别。
  `auto_start: false` 不撤销用户启用，卸载时始终尝试停止服务并清理所有 runlevel 的链接。
- OpenRC 脚本 pidfile 用 `/run/<服务名>.pid`，日志写 `/var/log/<服务名>.log`，
  `flange app debug/log` 依赖这两个路径。
  start-stop-daemon 的 pidfile 直接指向服务进程；supervise-daemon 的服务 PID 从 OpenRC 状态读取，
  验证父子关系，监督程序升级后出现 ` (deleted)` 也不会附加到监督进程。
- 省略 `packaging.format` 时使用目标发行版的 `apk`，包括 `packaging.outputs` 声明的完整外部包。
  导入 v2/v3 包时，包头架构必须匹配目标或为 `noarch`；提取后的用户态 ELF 校验机器类型、
  加载器、SDK 提供的 libc 依赖及 ARM 浮点 ABI，拒绝混入 glibc 动态程序或共享库。
  检查不覆盖全部运行库和符号版本，不能替代设备运行验证。
  rootfs 安装前统一检查报告的发行版和用户态 ABI 身份。
  不同 App 的同名 APK 使用独立暂存路径，避免互相覆盖。
- apk 依赖用 `packaging.depends.apk` 声明；顶层 `depends` 是 Debian 包名，不用于 apk。
- `components/app/musl-check` 是端到端验证 App（C++、线程、动态 zlib）。

基础缓存通过 flange 的公共发行版入口纳入活树存储、快照和 chroot 等配方；
公共实现变化会使 Alpine 的基础缓存失效，层内只维护发行版专属输入。

## 测试

```bash
FLANGE_TOOL_ROOT=../flange ../flange/.venv/bin/python -m pytest tests
```
