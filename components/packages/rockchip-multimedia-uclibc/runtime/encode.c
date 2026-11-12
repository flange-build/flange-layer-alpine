/* 真机探针：厂商 MPI 头文件定义结构，libc 只使用不透明指针和标量接口。 */
#include <stddef.h>
#include "rk_mpi_mb.h"
#include "rk_mpi_venc.h"

extern int printf(const char *, ...);
extern int fflush(void *);
extern int creat(const char *, unsigned int);
extern int write(int, const void *, unsigned int);
extern int close(int);
extern int access(const char *, int);
extern void *memset(void *, int, size_t);
extern RK_S32 RK_MPI_SYS_Init(void);
extern RK_S32 RK_MPI_SYS_Exit(void);
extern RK_S32 RK_MPI_SYS_MmzAlloc_Cached(MB_BLK *, const char *, const char *, RK_U32);
extern RK_S32 RK_MPI_SYS_MmzFree(MB_BLK);
extern RK_S32 RK_MPI_SYS_MmzFlushCache(MB_BLK, RK_BOOL);

static int report(const char *name, int ret)
{
    printf("%s: %d (0x%x)\n", name, ret, (unsigned int)ret);
    fflush(NULL);
    return ret;
}

int main(int argc, char **argv)
{
    const unsigned int width = 320, height = 240, frames = 16;
    MB_BLK block = NULL;
    VENC_CHN_ATTR_S attr = {0};
    VENC_RECV_PIC_PARAM_S recv = {.s32RecvPicNum = -1};
    int initialized = 0, created = 0, started = 0, fd = -1, result = 1;
    unsigned int total = 0;
    if (argc != 2) {
        printf("usage: %s output.h264\n", argv[0]);
        return 2;
    }
    const char *nodes[] = {
        "/dev/mpi/valloc", "/dev/mpi/vsys", "/dev/mpi/venc", "/dev/vcodec",
    };
    for (unsigned int i = 0; i < sizeof(nodes) / sizeof(nodes[0]); ++i) {
        if (access(nodes[i], 6)) {
            printf("required device unavailable: %s\n", nodes[i]);
            return 1;
        }
    }
    if (report("SYS_Init", RK_MPI_SYS_Init()))
        goto cleanup;
    initialized = 1;
    if (report("MMZ_Alloc", RK_MPI_SYS_MmzAlloc_Cached(
            &block, NULL, NULL, width * height * 3 / 2)))
        goto cleanup;
    unsigned char *pixels = RK_MPI_MB_Handle2VirAddr(block);
    printf("MMZ: fd=%d size=%llu address=%p\n", RK_MPI_MB_Handle2Fd(block),
        (unsigned long long)RK_MPI_MB_GetSize(block), pixels);
    fflush(NULL);
    if (!pixels)
        goto cleanup;
    attr.stVencAttr.enType = RK_VIDEO_ID_AVC;
    attr.stVencAttr.enPixelFormat = RK_FMT_YUV420SP;
    attr.stVencAttr.u32Profile = H264E_PROFILE_BASELINE;
    attr.stVencAttr.bByFrame = RK_TRUE;
    attr.stVencAttr.u32PicWidth = attr.stVencAttr.u32MaxPicWidth = width;
    attr.stVencAttr.u32PicHeight = attr.stVencAttr.u32MaxPicHeight = height;
    attr.stVencAttr.u32VirWidth = width;
    attr.stVencAttr.u32VirHeight = height;
    attr.stVencAttr.u32StreamBufCnt = 2;
    attr.stVencAttr.u32BufSize = width * height * 3 / 2;
    attr.stRcAttr.enRcMode = VENC_RC_MODE_H264CBR;
    attr.stRcAttr.stH264Cbr.u32Gop = 30;
    attr.stRcAttr.stH264Cbr.u32BitRate = 512;
    attr.stRcAttr.stH264Cbr.u32SrcFrameRateNum = 30;
    attr.stRcAttr.stH264Cbr.u32SrcFrameRateDen = 1;
    attr.stRcAttr.stH264Cbr.fr32DstFrameRateNum = 30;
    attr.stRcAttr.stH264Cbr.fr32DstFrameRateDen = 1;
    attr.stRcAttr.stH264Cbr.u32StatTime = 1;
    attr.stGopAttr.enGopMode = VENC_GOPMODE_NORMALP;
    if (report("VENC_CreateChn", RK_MPI_VENC_CreateChn(0, &attr)))
        goto cleanup;
    created = 1;
    if (report("VENC_StartRecvFrame", RK_MPI_VENC_StartRecvFrame(0, &recv)))
        goto cleanup;
    started = 1;
    fd = creat(argv[1], 0644);
    if (fd < 0)
        goto cleanup;
    for (unsigned int i = 0; i < frames; ++i) {
        VIDEO_FRAME_INFO_S frame = {0};
        VENC_PACK_S pack = {0};
        VENC_STREAM_S stream = {.pstPack = &pack, .u32PackCount = 1};
        for (unsigned int y = 0; y < height; ++y)
            for (unsigned int x = 0; x < width; ++x)
                pixels[y * width + x] = 16 + ((x + y + i * 8) % 220);
        memset(pixels + width * height, 128, width * height / 2);
        if (report("MMZ_Flush", RK_MPI_SYS_MmzFlushCache(block, RK_FALSE)))
            goto cleanup;
        frame.stVFrame.pMbBlk = block;
        frame.stVFrame.u32Width = frame.stVFrame.u32VirWidth = width;
        frame.stVFrame.u32Height = frame.stVFrame.u32VirHeight = height;
        frame.stVFrame.enPixelFormat = RK_FMT_YUV420SP;
        frame.stVFrame.enCompressMode = COMPRESS_MODE_NONE;
        frame.stVFrame.u64PTS = (RK_U64)i * 1000000 / 30;
        frame.stVFrame.u32TimeRef = i;
        if (report("VENC_SendFrame", RK_MPI_VENC_SendFrame(0, &frame, 2000)))
            goto cleanup;
        if (report("VENC_GetStream", RK_MPI_VENC_GetStream(0, &stream, 2000)))
            goto cleanup;
        const unsigned char *data = RK_MPI_MB_Handle2VirAddr(pack.pMbBlk);
        /* RV1106 的 MB 映射已指向当前码流片段；长度是本片段字节数。 */
        int valid = data && pack.u32Len > 0;
        unsigned int size = valid ? pack.u32Len : 0;
        unsigned int written = 0;
        while (written < size) {
            int count = write(fd, data + written, size - written);
            if (count <= 0)
                break;
            written += (unsigned int)count;
        }
        int release = report("VENC_ReleaseStream", RK_MPI_VENC_ReleaseStream(0, &stream));
        if (!valid || written != size || release)
            goto cleanup;
        total += size;
        printf("frame=%u bytes=%u pts=%llu\n", i, size, (unsigned long long)pack.u64PTS);
        fflush(NULL);
    }
    printf("encoded %u frames %ux%u H264 bytes=%u\n", frames, width, height, total);
    result = 0;
cleanup:
    if (fd >= 0 && close(fd))
        result = 1;
    if (started && report("VENC_StopRecvFrame", RK_MPI_VENC_StopRecvFrame(0)))
        result = 1;
    if (created && report("VENC_DestroyChn", RK_MPI_VENC_DestroyChn(0)))
        result = 1;
    if (block && report("MMZ_Free", RK_MPI_SYS_MmzFree(block)))
        result = 1;
    if (initialized && report("SYS_Exit", RK_MPI_SYS_Exit()))
        result = 1;
    return result;
}
