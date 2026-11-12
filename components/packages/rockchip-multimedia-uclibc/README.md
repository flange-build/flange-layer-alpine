# RV1106 uClibc 多媒体运行时

该包让 Luckfox RV1106 的厂商多媒体库运行在 Alpine 上。系统保留 musl；厂商应用和库在
独立进程中使用 uClibc，不把两种 libc 链接进同一进程。

## 内容与路径

| 内容 | 安装位置 | 用途 |
| --- | --- | --- |
| uClibc 1.0.31 加载器、libc、libgcc、libstdc++ | `/opt/rockchip-uclibc/lib` | 厂商程序的匹配运行库 |
| Rockit、MPP、RGA、RKAIQ | `/opt/rockchip-uclibc/usr/lib` | MPI、编解码、二维加速、ISP 图像处理接口 |
| 对应公开头文件 | `/opt/rockchip-uclibc/usr/include` | 厂商 uClibc 应用开发输入 |
| 加载检查程序 | `/opt/rockchip-uclibc/bin/rockchip-multimedia-check` | 加载四库并查找公开符号，不初始化外设 |
| 启动入口 | `/usr/bin/rockchip-uclibc-run` | 只为子进程设置私有库路径 |

不覆盖 `/lib`、`/usr/lib`、musl 加载器或系统 C++ 库，不设置全局 `LD_LIBRARY_PATH`。
默认使用 `librockit.so`，没有安装 full/tiny 变体、OpenCV、NPU/IVA、摄像头服务或传感器 IQ 文件。
运行包包含头文件，但不包含完整交叉编译器或 libc 开发 SDK。

## 构建与检查

前提是按[层 README](../../../README.md#使用)创建工作区，启用本层，并使用支持
`packaging.isolated_runtime` 的 flange。以下命令在 `flange-layer-alpine` 根目录执行：

```bash
source ../flange/envsetup.sh
flange -C ../flange-alpine-ws --target luckfox-pico-pro-max-alpine-release docker build
flange -C ../flange-alpine-ws --target luckfox-pico-pro-max-alpine-release app build rockchip-multimedia-uclibc
```

输出为工作区
`.build/target/luckfox-pico-pro-max/alpine/release/apps/rockchip-multimedia-uclibc-<资源摘要>/artifacts/rockchip-multimedia-uclibc-1.0.0-r0.apk`，
对应 `install/` 保存完整 SDK 安装树。完整日志位于该 target 的 `build.log`。
该包已由本层 `luckfox-pico-pro-max` 的 `alpine` product 启用，后续正常构建 rootfs 会安装此 APK。
内置 `default`/Ubuntu 产品不启用它。

如需部署到已启动的对应 Alpine 设备，可在确认设备身份后运行：

```bash
flange -C ../flange-alpine-ws --target luckfox-pico-pro-max-alpine-release app deploy rockchip-multimedia-uclibc
```

在设备终端运行：

```sh
rockchip-uclibc-run /opt/rockchip-uclibc/bin/rockchip-multimedia-check
```

预期依次显示 `librockchip_mpp.so.1`、`librga.so`、`librkaiq.so`、`librockit.so`，
最后显示 `4 libraries loaded; hardware not tested`，退出码为 0。
它使用 `RTLD_NOW`（立即解析符号），可发现缺失库和符号；这不代表摄像头或硬件编解码通过。

## 编写厂商应用

使用 Luckfox 官方 ARM hard-float uClibc 工具链在 Docker 中编译，头文件和链接库取自上述私有 SDK。
链接时指定 `-Wl,--dynamic-linker=/opt/rockchip-uclibc/lib/ld-uClibc.so.0`，安装到
`/opt/rockchip-uclibc/bin/`，再用 `rockchip-uclibc-run` 启动。现有程序须在构建副本中用
`patchelf --set-interpreter /opt/rockchip-uclibc/lib/ld-uClibc.so.0 <程序>` 重定位加载器。
附加动态依赖也须来自匹配的 uClibc 工具链，放入私有 `lib/` 或 `usr/lib/`。

Alpine 原生 musl App 不可直接链接或 `dlopen` 这些库；跨 ABI 交互使用独立进程与 IPC（进程间通信）。
本包不改变 `build.deps` 的默认工具链。检查程序使用容器内 Clang 的 ARM hard-float 代码生成，
仅链接固定的厂商 CRT（C 运行时启动对象）和运行库，不引入 Alpine libc。

## 来源、缓存与许可

- 多媒体库与头文件来自 [Luckfox 官方 RK-MPI 示例 SDK](https://github.com/LuckfoxTECH/luckfox_pico_rkmpi_example/tree/55178250c05542b156ac94c8c08cecef46589abf)。
- uClibc、GCC 运行库、启动对象和许可来自 [Luckfox 官方工具链](https://github.com/LuckfoxTECH/luckfox-pico/tree/824b817f889c2cbff1d48fcdb18ab494a68f69d1/tools/linux/toolchain/arm-rockchip830-linux-uclibcgnueabihf)。
- 所有下载由 [sources.json](runtime/sources.json) 固定提交与 SHA256，缓存位于工作区
  `.build/sources/rockchip-multimedia-uclibc/`，按摘要加锁、校验后原子发布。
  首次需要联网，完整缓存可离线重建。库在构建副本中去除调试信息，uClibc 自身的解释器路径也重定位。
- 许可与来源清单安装到 `/usr/share/licenses/rockchip-multimedia-uclibc/`。
  uClibc 的 LGPL、GCC 的运行库例外及厂商头文件声明保持原归属；本层不改变厂商二进制的授权条件。

## 验证范围与排障

2026-11-12，target 为 `luckfox-pico-pro-max-alpine-release`，基线为 Alpine 3.24.4、
musl 1.2.6、Linux 6.1.115+，验证结果如下。私有运行时及头文件约 8.4 MiB。

| 验证 | 实际结果 |
| --- | --- |
| Docker 构建 | APK 与包含该包的完整镜像构建通过；当前使用 Rust usbmoded 的 rootfs 共 110 个 APK |
| QEMU 安装与加载 | Alpine armv7 minirootfs 上安装成功；提供 RV1106 procfs 身份夹具后四库可加载；未模拟外设 |
| 实机烧录与启动 | RV1106G3 Max、W25N02KV 256MB SPI NAND，Maskrom 全量烧录并启动成功，USB/网络 ADB 可连接 |
| 实机库加载 | 四库的 `RTLD_NOW` 加载和公开符号解析通过，退出码 0；前后 BusyBox 可运行，musl 加载器摘要相同 |
| 实机 H.264 探针 | 缺少 `/dev/mpi/*`；内存分配时厂商库断言中止，退出码 134，未生成码流 |
| RGA / RKAIQ 硬件功能 | 当前无 `/dev/rga`、`/dev/video*`、`/dev/media*`，未完成图像处理或摄像头采集验收 |

H.264 探针使用本包的厂商头文件与 CRT，仅链接私有 uClibc 和 Rockit。
`RK_MPI_SYS_Init()` 虽返回 0，日志已报告缺少 `/dev/mpi/valloc`、`vsys`、`venc` 等节点；
随后 `RK_MPI_SYS_MmzAlloc_Cached()` 在 `RTDmaStore::fetchDma` 中断言失败。
当前板级设备树未启用多媒体节点，内核也未集成与本套用户态匹配的厂商 MPI/编码驱动。
安装运行库不能补齐这些 BSP 依赖，不能把初始化返回 0 当作硬件通过。

配套 flange 的 USB 管理层使用 Rust 静态程序，不依赖 Python/PyYAML。
板级内核还须启用 `CONFIG_HIGH_RES_TIMERS=y`：低精度定时器使 NAND 每页的微秒级轮询
退化到约 10 毫秒。仅更新 boot 后，UBI 扫描从约 35.7 秒降到 0.4 秒。
配套 OpenRC 服务将 usbmoded 提前到 `boot` 的网络初始化之前，adbd 按需启动后标记为
`hotplugged`，跨运行级别保持连接。该 Max / SPI NAND 目标正常重启到 USB ADB shell
实测约 12–14 秒；测量条件、对照与范围统一见下方板卡说明。
新内核下 3 次软断连、5 次幂等 reload、非特权拒绝通过；Rust 版本另已验证串口场景与 host 自动回滚。
当前完整镜像已构建并通过清单校验，实机结论来自原 rootfs 上的 APK 升级与 boot 分区更新；
尚未重新全量烧录。UBIFS 空闲空间修复保留；旧内核首启约 148 秒的修复耗时不代表新内核，
新版完整 rootfs 首次挂载及真实数据线插拔未测。具体启动诊断见配套 flange 的
[Luckfox 板卡说明](../../../../flange/docs/boards/luckfox-pico-pro-max.md#首次启动与-adb-排障)。

Rockit 的构造函数读取 SoC 身份；在没有 Rockchip 设备树的通用主机/QEMU 上可能崩溃，
因此不能把普通 x86 主机上的加载失败归结为 libc 不兼容。
RKAIQ 仍需要与实际传感器、ISP32、内核 BSP 匹配的 IQ 标定文件和设备节点，须由板级配置提供。

| 现象 | 处理 |
| --- | --- |
| `isolated_runtime` 未知字段 | 更新配套 flange，重新执行构建 |
| 缺少 patchelf | 重新运行上述 `flange ... docker build` |
| SHA256 不匹配 | 检查代理/下载来源，移除报错的单个缓存文件后重试，不绕过校验 |
| 文件存在但执行时报找不到文件 | 检查 ELF 解释器是否指向私有加载器，并确认完整 APK 已安装 |
| 缺少共享库或符号 | 使用启动入口，核对整套厂商库版本及私有依赖；不要从 musl 的 `/usr/lib` 补库 |
| `fetchDma` 断言或缺少 `/dev/mpi/*` | 集成匹配当前内核的厂商 MPI 驱动并启用板级节点；只安装 APK 不足以执行硬件调用 |
| 加载检查通过但无图像/编码失败 | 核对内核驱动、设备树、设备权限、实际传感器和 IQ 文件，按硬件路径排查 |

层内逻辑测试入口见[测试说明](../../../README.md#测试)；包格式与私有 ABI 契约见配套 flange 的
[包格式后端参考](../../../../flange/docs/package-backends.md#独立-libc-运行时)。
