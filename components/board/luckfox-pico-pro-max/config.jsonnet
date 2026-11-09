// 在 flange 核心的 luckfox-pico-pro-max 板上追加 Alpine product。
// 核心板（BSP）不知道 Alpine 存在；本文件只在 product=alpine 时切换发行版。
local product = std.extVar('product');

{
  products+: ['alpine'],
} + (if product == 'alpine' then {
  distro: 'alpine',
  extensions+: {
    // RV1106 串口由 fiq-debugger 以 ttyFIQ0 提供。
    'distro:alpine'+: { consoles: ['ttyFIQ0'] },
  },
  rootfs+: {
    // Rockchip 平台层追加的是 Debian 包名与 DEB 形态的 flange App
    // （recoveryctl、flange-rootfs-grow），在 Alpine 上一律重置。
    packages: [],
    custom_packages: [],
  },
} else {})
