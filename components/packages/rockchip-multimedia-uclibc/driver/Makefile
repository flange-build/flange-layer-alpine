# 对当前内核编译 ABI（应用二进制接口）约束，再安装 SDK 原始模块。
obj-m += abi_check.o
.PHONY: all
all:
	$(MAKE) -C "$(KSRC)" M="$(CURDIR)" ARCH="$(ARCH)" CROSS_COMPILE="$(CROSS_COMPILE)" abi_check.o
	python3 prepare.py "$(SDK)" "$(CURDIR)"
