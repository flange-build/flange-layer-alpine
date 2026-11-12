// 校验厂商模块直接访问的内核布局；失配时禁止打包。
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/fs.h>
#include <linux/completion.h>
#include <linux/version.h>
#define INCLUDE_VERMAGIC
#include <linux/vermagic.h>

static_assert(LINUX_VERSION_CODE == KERNEL_VERSION(5, 10, 160));
static_assert(sizeof(struct platform_driver) == 104);
static_assert(offsetof(struct platform_driver, driver) == 20);
static_assert(offsetof(struct platform_driver, driver.of_match_table) == 44);
static_assert(sizeof(struct file_operations) == 128);
static_assert(offsetof(struct file_operations, unlocked_ioctl) == 40);
static_assert(offsetof(struct file, private_data) == 128);
static_assert(sizeof(struct completion) == 12);
MODULE_INFO(vermagic, VERMAGIC_STRING);
MODULE_LICENSE("GPL");
