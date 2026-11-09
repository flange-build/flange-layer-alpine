// Alpine 发行版基线：不继承 Ubuntu 的包集合与账号默认值，字段语义见 flange
// components/rootfs/config.jsonnet；Alpine 专有参数在 extensions['distro:alpine']。
local variant = std.extVar('variant');

{
  distro: 'alpine',
  extensions+: {
    'distro:alpine': {
      release: '3.24.4',
      mirror: 'https://dl-cdn.alpinelinux.org/alpine',
      repositories: ['main', 'community'],
      // minirootfs 摘要按 flange 用户态架构名索引（armhf 对应 Alpine armv7）。
      minirootfs: {
        armhf: '2054061dafea7fe4cd38015701ee77119e780dd0382d0c32fad56986fe31b699',
        aarch64: '4b14c18f7e90a063b61462ea1462a5732c154bf6adad594974fe6487cd98a8de',
      },
      // OpenRC runlevel → 服务；构建期以符号链接启用，与 rc-update add 等价。
      services: {
        sysinit: ['devfs', 'dmesg', 'mdev', 'hwdrivers'],
        boot: ['modules', 'sysctl', 'hostname', 'bootmisc', 'syslog', 'networking', 'seedrng'],
        default: ['sshd', 'crond'],
        shutdown: ['mount-ro', 'killprocs', 'savecache'],
      },
      // 串口 getty；板级按实际 console 覆盖。
      consoles: [],
    },
  },
  rootfs: {
    root_password: null,
    disable_root_login: true,
    users: {
      flange: { password: 'flange', sudo: true, shell: '/bin/bash' },
    },
    default_user: 'flange',
    default_session: null,
    gnome_remote_desktop_login: false,
    install_recommends: false,
    groups: [
      'adm', 'dialout', 'cdrom', 'sudo', 'audio', 'video',
      'plugdev', 'users', 'netdev', 'input', 'render',
      'i2c', 'spi', 'gpio',
    ],
    custom_packages: [],
    package_sets: {
      // shadow/sudo/bash 让 flange 核心账号逻辑（useradd/chpasswd/visudo）原样复用。
      base: [
        'alpine-base', 'openrc', 'busybox-openrc', 'busybox-mdev-openrc',
        'shadow', 'sudo', 'bash', 'openssh', 'ca-certificates',
        'ifupdown-ng', 'iproute2', 'kmod', 'util-linux',
        'e2fsprogs', 'mtd-utils-ubi', 'chrony',
      ],
      debug: ['gdb', 'strace', 'tcpdump'],
      release: [],
    },
    package_set: ['base'] + (if variant == 'debug' then ['debug'] else ['release']),
  },
}
