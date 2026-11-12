/* 仅检查动态加载和公开符号，不初始化或操作多媒体硬件。
 * 以下是 uClibc dlfcn.h/stdio.h 的标量接口；无需引入另一套 libc 结构体。
 */
extern void *dlopen(const char *filename, int flags);
extern void *dlsym(void *handle, const char *symbol);
extern char *dlerror(void);
extern int puts(const char *text);

int main(void)
{
    const char *libraries[] = {
        "librockchip_mpp.so.1", "librga.so", "librkaiq.so", "librockit.so", "librknnmrt.so"
    };
    const char *symbols[] = {
        "mpp_create", "c_RkRgaInit", "rk_aiq_uapi2_sysctl_init", "RK_MPI_SYS_Init", "rknn_init"
    };
    unsigned int index;

    for (index = 0; index < sizeof(libraries) / sizeof(libraries[0]); ++index) {
        /* uClibc ARM 的 RTLD_NOW = 2，强制立即解析全部动态重定位。 */
        void *handle = dlopen(libraries[index], 2);
        if (!handle || !dlsym(handle, symbols[index])) {
            puts(libraries[index]);
            puts(dlerror());
            return 1;
        }
        puts(libraries[index]);
        /* 库保留至进程结束，同时验证五库及共享依赖能在一个进程内共存。 */
    }
    puts("Rockchip uClibc: 5 libraries loaded; hardware not tested");
    return 0;
}
