/* 真机图像处理自检：MPI 连续内存经 DMA-BUF 交给 RGA，逐像素验证结果。 */
#include <stddef.h>
#include "rk_mpi_mb.h"
#include "librga/im2d.h"

extern int printf(const char *, ...);
extern int access(const char *, int);
extern void *memset(void *, int, size_t);
extern RK_S32 RK_MPI_SYS_Init(void);
extern RK_S32 RK_MPI_SYS_Exit(void);
extern RK_S32 RK_MPI_SYS_MmzAlloc_Cached(MB_BLK *, const char *, const char *, RK_U32);
extern RK_S32 RK_MPI_SYS_MmzFree(MB_BLK);
extern RK_S32 RK_MPI_SYS_MmzFlushCache(MB_BLK, RK_BOOL);

int main(void)
{
    const int width = 128, height = 96;
    const unsigned int bytes = width * height * 4;
    MB_BLK src_block = NULL, dst_block = NULL;
    int result = 1;
    if (access("/dev/rga", 6) || access("/dev/mpi/valloc", 6)) {
        printf("RGA/MPI device unavailable\n");
        return 1;
    }
    if (RK_MPI_SYS_Init())
        return 1;
    if (RK_MPI_SYS_MmzAlloc_Cached(&src_block, NULL, NULL, bytes) ||
        RK_MPI_SYS_MmzAlloc_Cached(&dst_block, NULL, NULL, bytes))
        goto cleanup;
    unsigned char *src = RK_MPI_MB_Handle2VirAddr(src_block);
    unsigned char *dst = RK_MPI_MB_Handle2VirAddr(dst_block);
    if (!src || !dst)
        goto cleanup;
    for (unsigned int i = 0; i < bytes; ++i)
        src[i] = (i * 37 + i / 128) & 255;
    memset(dst, 0, bytes);
    if (RK_MPI_SYS_MmzFlushCache(src_block, RK_FALSE) ||
        RK_MPI_SYS_MmzFlushCache(dst_block, RK_FALSE))
        goto cleanup;
    rga_buffer_t source = wrapbuffer_fd_t(RK_MPI_MB_Handle2Fd(src_block),
        width, height, width, height, RK_FORMAT_RGBA_8888);
    rga_buffer_t target = wrapbuffer_fd_t(RK_MPI_MB_Handle2Fd(dst_block),
        width, height, width, height, RK_FORMAT_RGBA_8888);
    IM_STATUS status = imcopy_t(source, target, 1);
    if (status != IM_STATUS_SUCCESS) {
        printf("RGA copy: %s\n", imStrError_t(status));
        goto cleanup;
    }
    if (RK_MPI_SYS_MmzFlushCache(dst_block, RK_TRUE))
        goto cleanup;
    for (unsigned int i = 0; i < bytes; ++i) {
        if (src[i] != dst[i]) {
            printf("RGA copy mismatch at byte %u: %u != %u\n", i, src[i], dst[i]);
            goto cleanup;
        }
    }
    printf("RGA copy: %ux%u RGBA, %u bytes verified\n", width, height, bytes);
    for (unsigned int i = 0; i < bytes / 4; ++i)
        ((unsigned int *)src)[i] = 0xff4925a3;
    memset(dst, 0, bytes);
    if (RK_MPI_SYS_MmzFlushCache(src_block, RK_FALSE) ||
        RK_MPI_SYS_MmzFlushCache(dst_block, RK_FALSE))
        goto cleanup;
    target = wrapbuffer_fd_t(RK_MPI_MB_Handle2Fd(dst_block), width / 2, height / 2,
        width / 2, height / 2, RK_FORMAT_RGBA_8888);
    status = imresize_t(source, target, 0, 0, INTER_NEAREST, 1);
    if (status != IM_STATUS_SUCCESS) {
        printf("RGA resize: %s\n", imStrError_t(status));
        goto cleanup;
    }
    if (RK_MPI_SYS_MmzFlushCache(dst_block, RK_TRUE))
        goto cleanup;
    for (unsigned int i = 0; i < bytes / 16; ++i) {
        if (((unsigned int *)dst)[i] != 0xff4925a3) {
            printf("RGA resize mismatch at pixel %u\n", i);
            goto cleanup;
        }
    }
    printf("RGA resize: %ux%u -> %ux%u, all pixels verified\n",
        width, height, width / 2, height / 2);
    result = 0;
cleanup:
    if (dst_block && RK_MPI_SYS_MmzFree(dst_block))
        result = 1;
    if (src_block && RK_MPI_SYS_MmzFree(src_block))
        result = 1;
    if (RK_MPI_SYS_Exit())
        result = 1;
    return result;
}
