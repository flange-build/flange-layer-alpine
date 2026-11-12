// 在核心 RV1106 BSP 上安装匹配的厂商多媒体模块；内核来源由 SoC 配置统一声明。
local layer = import 'flange/layer.libsonnet';
{
  assert $.soc == 'rv1106': 'rockchip-multimedia-uclibc 仅支持 RV1106',
  sources+: {
    'luckfox-media-driver': {
      local_path: layer.path('components/packages/rockchip-multimedia-uclibc/driver'),
    },
  },
  kernel+: {
    oot_sources+: {
      'luckfox-media-sdk': { source: { name: 'luckfox-sdk', subpath: 'sysdrv/drv_ko' } },
      'luckfox-media-driver': { source: { name: 'luckfox-media-driver' } },
    },
    oot_modules+: [{
      dir: '{luckfox_media_driver_src}',
      label: 'Luckfox 官方 Rockit/KMPP（校验 ABI 后安装）',
      stage: true,
      make_args: ['KSRC={kernel_src_abs}', 'SDK={luckfox_media_sdk_src}',
                  'ARCH={arch}', 'CROSS_COMPILE={cross_compile}'],
      ko_pattern: ['{oot_build_dir}/rockit.ko', '{oot_build_dir}/mpp_vcodec.ko'],
    }],
  },
}
