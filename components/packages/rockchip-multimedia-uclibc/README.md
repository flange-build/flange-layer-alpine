# RV1106 uClibc 多媒体运行时

为 Luckfox Pico Pro/Max 的 Alpine 产品提供 Rockit、MPP、RGA、RKAIQ、RKNN 与配套厂商模块，
复用 flange 核心统一提供的 Linux 5.10.160 BSP。
系统保留 musl；厂商应用在独立进程中使用 uClibc。已在 Max 上验证 MPI 连续内存、H.264 硬件编码、
RGA 图像处理和 NPU 图片推理；摄像头采集和 RKAIQ 算法尚待实际传感器验收。

## 内容与路径

| 内容 | 安装位置 |
| --- | --- |
| uClibc 1.0.31、libgcc、libstdc++ | `/opt/rockchip-uclibc/lib` |
| Rockit、MPP、RGA、RKAIQ、RKNN 与公开头文件 | `/opt/rockchip-uclibc/usr/lib`、`usr/include` |
| 五库加载检查、H.264 编码、RGA 自检程序 | `/opt/rockchip-uclibc/bin/rockchip-multimedia-{check,encode,rga}` |
| YOLOv5 图片推理程序 | `/opt/rockchip-uclibc/bin/rockchip-rknn-yolo` |
| 私有运行时启动入口 | `/usr/bin/rockchip-uclibc-run` |
| 官方 Rockit / KMPP 模块 | `/lib/modules/5.10.160/updates` |
| OpenRC 驱动服务、video 组设备规则 | `/etc/init.d/rockchip-multimedia`、`/etc/udev/rules.d/90-rockchip-multimedia.rules` |
| 配套 MCU 固件（当前不启用） | `/lib/firmware/rockchip/rv1106-hpmcu.bin` |

不覆盖系统 libc、C++ 库或全局库搜索路径。不包含 full/tiny 变体、OpenCV、IVA、摄像头服务、
传感器 IQ 标定文件或完整 uClibc 开发工具链。MPP 编码通过 Rockit MPI 与 `mpp_vcodec` 实现，
不代表通用 FFmpeg 的 Rockchip 编码后端已经适配。

## BSP 与启动约束

当前固定 SDK 的 RV1106 厂商模块与 Linux 5.10.160 绑定。已有 6.1 内核的驱动结构体布局不同，不能仅改
`vermagic`（模块版本标记）加载旧模块。核心 RV1106 配置固定官方 SDK 提交，本包校验模块 SHA256，并对目标内核编译
关键布局断言、比较原始模块的 vermagic；失配直接停止构建。模块本体保持官方内容，安装时仅去除调试信息。

Ubuntu 与 Alpine 共用核心声明的内核来源、设备树和通用驱动配置；本包追加 Rockit / KMPP 模块。
NPU、编码器、RGA、ISP、DVBM 与连续内存的板级支持随核心 BSP 提供。
板级设备树保持 flange 的 GPT / UBI 启动参数、固定 900 mV 供电和心跳灯；保留高精度定时器与
Rust USB 管理服务。厂商 MPI 使用专用 CMA（连续内存分配区），由设备树启动参数 `rk_dma_heap_cma=66M` 配置；
通用 CMA 大小设为 0，避免重复预留。仅修改 `CONFIG_CMA_SIZE_MBYTES` 不会扩大厂商池。
内置 `default` / Ubuntu 产品使用同一 5.10.160 BSP，但没有启用本包的厂商模块、运行库和服务。

服务在 OpenRC `default` 阶段加载模块，USB 调试在 `boot` 阶段已可用。
当前使用 `en_mcu=0`：普通帧缓冲编码和 RGA 不需要 MCU 卷绕功能；当前 TOS 下，官方驱动向
HPMCU 启动地址寄存器写入时发生总线异常。MCU 固件虽已固定和交付，该通路尚未完成适配，不能启用卷绕模式。

## 构建、烧录与运行

先按[层 README](../../../README.md#使用)创建工作区；配套 flange 需要包含统一的 RV1106
5.10.160 BSP、私有运行时及 `source.subpath` 下的组件补丁支持。以下命令在 `flange-layer-alpine` 根目录执行：

```bash
source ../flange/envsetup.sh
flange -C ../flange-alpine-ws --target luckfox-pico-pro-max-alpine-release docker build
flange -C ../flange-alpine-ws --target luckfox-pico-pro-max-alpine-release build
```

首次下载官方 SDK 需要联网。产物根为工作区
`.build/target/luckfox-pico-pro-max/alpine/release/`：`boot/boot.img` 是内核镜像，
`kernel/modules/` 是配套模块，`rootfs/rootfs.ubi` 是系统镜像，`apps/*/artifacts/` 保存 APK。
完整日志在 `build.log`。当前运行包为 `rockchip-multimedia-uclibc-1.2.0-r0.apk`，
启动服务为 `rockchip-multimedia-service-1.1.0-r0.apk`。

首次使用应备份板上数据，让板卡进入 Maskrom（芯片下载模式），然后全量烧录匹配的镜像：

```bash
flange -C ../flange-alpine-ws --target luckfox-pico-pro-max-alpine-release flash
```

已有同版 5.10.160 BSP 只升级用户态时：

```bash
flange -C ../flange-alpine-ws --target luckfox-pico-pro-max-alpine-release app build rockchip-multimedia-service
flange -C ../flange-alpine-ws --target luckfox-pico-pro-max-alpine-release app deploy rockchip-multimedia-service --no-build --serial <USB序列号>
adb -s <USB序列号> shell 'sync; reboot'
```

服务的依赖闭包会一起部署私有运行时。6.1 系统只升级 APK 不够，必须同时更换内核及模块。
若手工修改过 OpenRC 文件，升级后检查 `.apk-new` 并合并配置。

重启后在板卡终端执行；自检可使用属于 `video` 组的 `flange` 用户：

```sh
rc-service rockchip-multimedia status
ls -l /dev/mpi/valloc /dev/mpi/venc /dev/vcodec /dev/rga /dev/rknpu
rockchip-uclibc-run /opt/rockchip-uclibc/bin/rockchip-multimedia-check
rockchip-uclibc-run /opt/rockchip-uclibc/bin/rockchip-multimedia-rga
rockchip-uclibc-run /opt/rockchip-uclibc/bin/rockchip-multimedia-encode /tmp/output.h264
```

加载检查只验证五库和公开符号。RGA 自检逐字节比较 128×96 RGBA 复制结果，再逐像素比较
缩到 64×48 的结果。编码自检把 16 帧 320×240 合成 NV12 图像送入 VENC，保存 H.264 码流；
成功打印 `encoded 16 frames 320x240 H264`，各命令退出码均为 0。
程序先检查必要设备权限，避免缺驱动时进入厂商库内部断言。

主机安装 FFmpeg 后，可拉回并解码核对帧数；该工具只做验收，不属于板卡运行依赖：

```sh
adb -s <USB序列号> pull /tmp/output.h264 ./output.h264
ffprobe -v error -count_frames -show_entries stream=codec_name,width,height,nb_read_frames -of json ./output.h264
ffmpeg -v error -xerror -i ./output.h264 -f null -
```

预期为 `h264`、320×240、16 帧，解码无错误。合成数据不是摄像头采集结果。

## NPU 图片推理

当前 RKNN（Rockchip 神经网络运行时）为 SDK 自带的 1.6.0，RKNPU 驱动为 0.9.2，
NPU 沿用设备树默认 420 MHz。`rockchip-multimedia` 自动加载 `rknpu`，
`/dev/rknpu` 设置为 `root:video 0660`。已有系统必须同时更新本包和启用 NPU 设备树的 boot；
只有 APK 或 `modprobe rknpu` 不能启用设备树中关闭的硬件。

`rockchip-rknn-yolo` 使用 RV1106 零拷贝 API（应用编程接口），接受官方 INT8 YOLOv5
COCO 80 类、640×640、三个 NHWC 输出头的模型。程序读取 P6 RGB 图片，在板端进行
双线性缩放、居中填充、NPU 推理和 CPU 上的 NMS（非极大值抑制），输出原图坐标及置信度。
阈值为 0.25，NMS 阈值为 0.45，最多返回 128 个检测框；输入每边最多 4096 像素、RGB 数据最多 16 MiB。
JSON 的 `inference_ms` 仅计 `rknn_run`，不包含模型加载、图像预处理、后处理或 ADB 传输。

模型和图片按 [demo/sources.json](demo/sources.json) 固定来源与 SHA256，按需下载，
不增加默认 rootfs 的模型数据。宿主需要 Python 3.12+、Pillow 和 ADB；以下在本层根目录执行，
`<USB序列号>` 用 `adb devices` 的实际值替换：

```sh
python3 -m venv ../flange-alpine-ws/.build/rknn-demo-venv
../flange-alpine-ws/.build/rknn-demo-venv/bin/pip install 'Pillow>=10.1'
../flange-alpine-ws/.build/rknn-demo-venv/bin/python components/packages/rockchip-multimedia-uclibc/demo/demo.py prepare ../flange-alpine-ws/.build/rknn-demo
adb -s <USB序列号> shell 'mkdir -p /var/lib/rknn-demo'
adb -s <USB序列号> push ../flange-alpine-ws/.build/rknn-demo/yolov5.rknn ../flange-alpine-ws/.build/rknn-demo/input.ppm /var/lib/rknn-demo/
adb -s <USB序列号> shell 'rockchip-uclibc-run /opt/rockchip-uclibc/bin/rockchip-rknn-yolo /var/lib/rknn-demo/yolov5.rknn /var/lib/rknn-demo/input.ppm /var/lib/rknn-demo/result.json'
adb -s <USB序列号> pull /var/lib/rknn-demo/result.json ../flange-alpine-ws/.build/rknn-demo/result.json
../flange-alpine-ws/.build/rknn-demo-venv/bin/python components/packages/rockchip-multimedia-uclibc/demo/demo.py render ../flange-alpine-ws/.build/rknn-demo
```

结果图为工作区 `.build/rknn-demo/result.png`，原始结果为同目录 `result.json`。
默认公交车图片实测检测出公交车（类别 5）和行人（类别 0）；置信度不是模型整体准确率。
`prepare` 追加 `--image /path/to/image.jpg` 可改用自己的图片，随后重复上传、推理和绘图。
宿主只做图片格式转换和结果绘制，神经网络在板上执行。

若需要普通用户运行，先将 `/var/lib/rknn-demo` 的结果目录设为该用户可写，并确保用户属于 `video` 组。
命令参数错误退出 2，输入/模型/推理失败退出 1，成功退出 0（空图没有检测框也是成功）。
失败时先查看退出码和 RKNN 日志；`Unsupported model` 表示不符合上述示例模型布局，
其他 RKNN 网络需要按其输入输出契约编写程序，不能直接套用 YOLOv5 的解码器。

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

- 用户态库和头文件来自 [Luckfox RK-MPI SDK](https://github.com/LuckfoxTECH/luckfox_pico_rkmpi_example/tree/55178250c05542b156ac94c8c08cecef46589abf)。
- 图片来自 [Rockchip Model Zoo](https://github.com/airockchip/rknn_model_zoo/tree/837db8e992815ff8647eadb709f07067f4bc3a71/examples/yolov5)；模型和 COCO 标签来自上述 RK-MPI SDK，保持原归属，示例资源不随 APK 分发。
- 内核、模块、MCU 固件和 uClibc 工具链来自 [Luckfox 固定 SDK](https://github.com/LuckfoxTECH/luckfox-pico/tree/824b817f889c2cbff1d48fcdb18ab494a68f69d1)。
- [核心 RV1106 配置](../../../../flange/components/platform/rockchip/rv1106/config.jsonnet)固定 Git 源码；
  [包配置](config.jsonnet)引用同一 SDK 的模块目录；[模块清单](driver/modules.json)和
  [运行时来源](runtime/sources.json)固定下载摘要。Git 缓存在工作区 `.build/sources/repos/`，
  运行库缓存位于 `.build/sources/rockchip-multimedia-uclibc/`；下载按摘要加锁、校验后发布。
- 许可和来源安装到 `/usr/share/licenses/rockchip-multimedia-uclibc/`。uClibc 的 LGPL、GCC
  运行库例外、内核模块和厂商头文件声明保持原归属，本层不改变第三方授权条件。

## 实机验证与限制

2026-11-12，在 RV1106G3 Max、256 MB W25N02KV SPI NAND 上验证
`luckfox-pico-pro-max-alpine-release`，系统为 Alpine 3.24.4 / musl 1.2.6 / Linux 5.10.160。
完整镜像构建通过；实机采用原系统上的 APK、模块更新与 boot 分区烧录，boot 读回内容与构建产物一致。
这不代表新版完整 rootfs 已重新全量烧录。

| 项目 | 实际结论 |
| --- | --- |
| 私有运行时 | 五库加载与符号解析通过；系统继续使用 musl |
| 内核驱动 | Rockit、KMPP、RGA、ISP、DVBM、RKNPU 加载，MPI / vcodec / rga 节点可用 |
| 连续内存 | 厂商专用池实测为 66 MiB（`CmaTotal: 67584 kB`）；MPI 分配、映射、缓存同步及释放通过 |
| H.264 | 16 帧 320×240 合成输入，主机完整解码；按完整色彩范围比较，逐帧亮度平均绝对误差 0.53–0.73 |
| RGA | 128×96 RGBA 复制的 49,152 字节一致；64×48 缩放结果逐像素一致 |
| 重启恢复 | 连续两次正常重启，驱动自动加载、权限恢复且普通用户 RGA 通过；无内核 Oops / BUG |
| NPU 图片推理 | RKNN 1.6.0 / RKNPU 0.9.2 / 420 MHz；公交车图片得到 1 个公交车框和 4 个行人框，10 次检测结果一致，`rknn_run` 为 80.91–81.12 ms |
| NPU 恢复与边界 | 正常重启后自动加载且 video 组普通用户推理通过；480×640 非方形图片坐标还原通过，空图返回零检测，超限/截断 PPM 拒绝；无内核 Oops / BUG |
| 普通用户 | `flange` 用户属于 video 组，H.264、RGA 和 RKNN 推理均通过 |
| RKAIQ、摄像头 | 仅库加载通过；未提供实际传感器型号、链路与 IQ 文件，未验收采集和算法 |
| MCU 卷绕 | 当前关闭，未支持；普通帧缓冲编码不依赖它 |
| 其他范围 | 未验收 Pro 128 MB、H.265/JPEG、长时间压力、实际摄像头分辨率或物理断电启动 |

常见故障：

| 现象 | 处理 |
| --- | --- |
| 缺少 patchelf | 重新运行 `docker build` |
| `vermagic` 或布局断言失败 | 核对固定 SDK 与内核配置；不要修改模块版本字符串或强制加载 |
| `/dev/mpi/*` 或 `/dev/vcodec` 缺失 | 检查 5.10.160 配套模块、OpenRC 服务和 `dmesg`；只安装 APK 不够 |
| `/dev/rknpu` 缺失 | 核对 boot 中 `npu@ff660000` 已启用、`rknpu` 模块和 OpenRC 状态；用新 boot 更新设备树 |
| 普通用户被拒绝 | 检查 `id` 中的 video 组及 udev 规则；修改组后重新登录 |
| 有节点但无摄像头图像 | 配置实际传感器的 CSI/I2C/供电连接和 IQ 文件，不能用加载检查代替采集验证 |
| `vmcu_probe` 内核异常 | 核对服务保持 `en_mcu=0`，随后重启清除失败的模块初始化状态 |

Rockit 构造函数读取 SoC 身份，通用主机/QEMU 缺少 Rockchip 设备树时的崩溃不等于 libc 不兼容。
启动优化及 USB 排障见配套 flange 的 [Luckfox 板卡说明](../../../../flange/docs/boards/luckfox-pico-pro-max.md)。
