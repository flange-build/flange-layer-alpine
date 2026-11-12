/* SPDX-License-Identifier: Apache-2.0
 * Copyright (c) 2021 by Rockchip Electronics Co., Ltd. All Rights Reserved.
 * YOLOv5 解码公式参考 Rockchip 2021 年 Apache-2.0 示例 postprocess.cc。
 * RV1106 静态图像推理：P6 RGB → 等比例缩放 → NPU → CPU 解码及同类 NMS。
 * 只支持标准 COCO 80 类、640×640、三输出头的 INT8 YOLOv5 模型。
 */
#include <stddef.h>
#include <stdint.h>
#include "rknn/rknn_api.h"

/* 仅声明 uClibc 的标量/不透明接口，不混用 musl 的 FILE 或时间结构体。 */
typedef struct vendor_file FILE;
extern FILE *fopen(const char *, const char *);
extern int fclose(FILE *);
extern int fgetc(FILE *);
extern int ungetc(int, FILE *);
extern size_t fread(void *, size_t, size_t, FILE *);
extern int fprintf(FILE *, const char *, ...);
extern int printf(const char *, ...);
extern void *malloc(size_t);
extern void free(void *);
extern void *memset(void *, int, size_t);
extern int strcmp(const char *, const char *);
extern void qsort(void *, size_t, size_t, int (*)(const void *, const void *));
/* 固定 SDK 的 ARM uClibc 1.0.31 使用 32 位 long/time_t。 */
struct vendor_timespec { long sec; long nsec; };
extern int clock_gettime(int, struct vendor_timespec *);

#define INPUT_SIZE 640
#define MAX_CANDIDATES 25200
#define MAX_RESULTS 128
#define CONFIDENCE 0.25f
#define NMS_THRESHOLD 0.45f

struct image { unsigned char *data; int width; int height; };
struct box { float x1, y1, x2, y2, score; int label; };
static struct box candidates[MAX_CANDIDATES];
static const int anchors[3][6] = {
    {10, 13, 16, 30, 33, 23}, {30, 61, 62, 45, 59, 119},
    {116, 90, 156, 198, 373, 326}
};

static int whitespace(int c)
{
    return c == ' ' || c == '\n' || c == '\r' || c == '\t' || c == '\v' || c == '\f';
}

static int token(FILE *file, char *out, size_t size)
{
    int c;
    size_t used = 0;
    for (;;) {
        c = fgetc(file);
        if (c == '#') {
            while (c != '\n' && c != -1)
                c = fgetc(file);
        }
        if (!whitespace(c))
            break;
    }
    while (c != -1 && !whitespace(c)) {
        if (used + 1 >= size)
            return -1;
        out[used++] = (char)c;
        c = fgetc(file);
    }
    if (c == '\r') {
        int next = fgetc(file);
        if (next != '\n' && next != -1)
            ungetc(next, file);
    }
    out[used] = 0;
    return used && c != -1 ? 0 : -1;
}

static int dimension(const char *s)
{
    int value = 0;
    if (!*s)
        return -1;
    for (; *s; ++s) {
        if (*s < '0' || *s > '9' || value > 4096)
            return -1;
        value = value * 10 + *s - '0';
    }
    return value > 0 && value <= 4096 ? value : -1;
}

static int read_ppm(const char *path, struct image *image)
{
    char text[24];
    FILE *file = fopen(path, "rb");
    int result = -1;
    if (!file)
        return -1;
    if (token(file, text, sizeof(text)) || strcmp(text, "P6"))
        goto done;
    if (token(file, text, sizeof(text)) || (image->width = dimension(text)) < 0)
        goto done;
    if (token(file, text, sizeof(text)) || (image->height = dimension(text)) < 0)
        goto done;
    if (token(file, text, sizeof(text)) || strcmp(text, "255"))
        goto done;
    size_t bytes = (size_t)image->width * image->height * 3;
    /* 控制 Cortex-A7 上的 CPU 图像内存占用。 */
    if (bytes > 16 * 1024 * 1024)
        goto done;
    image->data = malloc(bytes);
    if (!image->data || fread(image->data, 1, bytes, file) != bytes || fgetc(file) != -1)
        goto done;
    result = 0;
done:
    if (fclose(file))
        result = -1;
    return result;
}

static float minimum(float a, float b) { return a < b ? a : b; }
static float maximum(float a, float b) { return a > b ? a : b; }
static float clamp(float value, float high) { return minimum(maximum(value, 0), high); }

static void letterbox(const struct image *image, unsigned char *target, int stride,
                      int *resized_w, int *resized_h, int *left, int *top)
{
    float scale = minimum((float)INPUT_SIZE / image->width, (float)INPUT_SIZE / image->height);
    *resized_w = maximum(1, (int)(image->width * scale + 0.5f));
    *resized_h = maximum(1, (int)(image->height * scale + 0.5f));
    *left = (INPUT_SIZE - *resized_w) / 2;
    *top = (INPUT_SIZE - *resized_h) / 2;
    /* 双线性插值；填充色 114 与 YOLOv5 常规预处理一致。 */
    for (int y = 0; y < *resized_h; ++y) {
        float sy = clamp((y + 0.5f) * image->height / *resized_h - 0.5f, image->height - 1);
        int y0 = (int)sy, y1 = y0 + 1 < image->height ? y0 + 1 : y0;
        float fy = sy - y0;
        for (int x = 0; x < *resized_w; ++x) {
            float sx = clamp((x + 0.5f) * image->width / *resized_w - 0.5f, image->width - 1);
            int x0 = (int)sx, x1 = x0 + 1 < image->width ? x0 + 1 : x0;
            float fx = sx - x0;
            for (int c = 0; c < 3; ++c) {
                float a = image->data[(y0 * image->width + x0) * 3 + c];
                float b = image->data[(y0 * image->width + x1) * 3 + c];
                float d = image->data[(y1 * image->width + x0) * 3 + c];
                float e = image->data[(y1 * image->width + x1) * 3 + c];
                float value = (a + (b - a) * fx) * (1 - fy) + (d + (e - d) * fx) * fy;
                target[((y + *top) * stride + x + *left) * 3 + c] = (unsigned char)(value + 0.5f);
            }
        }
    }
}

static float dequant(int8_t value, const rknn_tensor_attr *attr)
{
    return (value - attr->zp) * attr->scale;
}

static int decode(const int8_t *data, const rknn_tensor_attr *attr, int head, int count)
{
    int grid = 80 >> head, stride = INPUT_SIZE / grid;
    for (int y = 0; y < grid; ++y) {
        for (int x = 0; x < grid; ++x) {
            for (int anchor = 0; anchor < 3; ++anchor) {
                const int8_t *p = data + (y * grid + x) * 255 + anchor * 85;
                float objectness = dequant(p[4], attr);
                if (objectness < CONFIDENCE)
                    continue;
                int label = 0;
                for (int c = 1; c < 80; ++c)
                    if (p[5 + c] > p[5 + label])
                        label = c;
                float score = objectness * dequant(p[5 + label], attr);
                if (score < CONFIDENCE)
                    continue;
                if (count >= MAX_CANDIDATES)
                    return -1;
                float cx = (dequant(p[0], attr) * 2 - 0.5f + x) * stride;
                float cy = (dequant(p[1], attr) * 2 - 0.5f + y) * stride;
                float w = dequant(p[2], attr) * 2, h = dequant(p[3], attr) * 2;
                w = w * w * anchors[head][anchor * 2];
                h = h * h * anchors[head][anchor * 2 + 1];
                candidates[count++] = (struct box){cx - w / 2, cy - h / 2,
                    cx + w / 2, cy + h / 2, score, label};
            }
        }
    }
    return count;
}

static int by_score(const void *a, const void *b)
{
    float left = ((const struct box *)a)->score, right = ((const struct box *)b)->score;
    return left < right ? 1 : left > right ? -1 : 0;
}

static float overlap(const struct box *a, const struct box *b)
{
    float w = maximum(0, minimum(a->x2, b->x2) - maximum(a->x1, b->x1));
    float h = maximum(0, minimum(a->y2, b->y2) - maximum(a->y1, b->y1));
    float area = (a->x2 - a->x1) * (a->y2 - a->y1) + (b->x2 - b->x1) * (b->y2 - b->y1);
    return area > w * h ? w * h / (area - w * h) : 0;
}

static int write_results(const char *path, const struct image *image, int count,
                         int width, int height, int left, int top, double milliseconds)
{
    struct box results[MAX_RESULTS];
    int used = 0;
    qsort(candidates, count, sizeof(candidates[0]), by_score);
    for (int i = 0; i < count && used < MAX_RESULTS; ++i) {
        int keep = 1;
        for (int j = 0; j < used; ++j)
            if (results[j].label == candidates[i].label &&
                overlap(&results[j], &candidates[i]) > NMS_THRESHOLD)
                keep = 0;
        if (keep)
            results[used++] = candidates[i];
    }
    FILE *file = fopen(path, "w");
    if (!file)
        return -1;
    int failed = fprintf(file, "{\"schema_version\":1,\"width\":%d,\"height\":%d,"
        "\"inference_ms\":%.3f,\"detections\":[", image->width, image->height, milliseconds) < 0;
    for (int i = 0; i < used; ++i) {
        struct box *b = &results[i];
        float x1 = clamp((b->x1 - left) * image->width / width, image->width);
        float y1 = clamp((b->y1 - top) * image->height / height, image->height);
        float x2 = clamp((b->x2 - left) * image->width / width, image->width);
        float y2 = clamp((b->y2 - top) * image->height / height, image->height);
        failed |= fprintf(file, "%s{\"class_id\":%d,\"score\":%.6f,\"box\":[%.2f,%.2f,%.2f,%.2f]}",
            i ? "," : "", b->label, b->score, x1, y1, x2, y2) < 0;
        printf("class=%d score=%.4f box=[%.1f,%.1f,%.1f,%.1f]\n", b->label, b->score, x1, y1, x2, y2);
    }
    failed |= fprintf(file, "]}\n") < 0;
    failed |= fclose(file) != 0;
    printf("NPU inference: %.3f ms; detections: %d\n", milliseconds, used);
    return failed ? -1 : 0;
}

int main(int argc, char **argv)
{
    rknn_context ctx = 0;
    rknn_tensor_mem *input = NULL, *outputs[3] = {NULL, NULL, NULL};
    rknn_tensor_attr in = {0}, out[3] = {{0}};
    rknn_input_output_num number;
    rknn_sdk_version version;
    struct image image = {0};
    int result = 1, width, height, left, top, count = 0;
    struct vendor_timespec begin, end;
    if (argc != 4) {
        printf("Usage: %s model.rknn image.ppm result.json\n", argv[0]);
        return 2;
    }
    if (read_ppm(argv[2], &image)) {
        printf("Invalid P6 RGB image (max 4096 per dimension, 16 MiB pixels)\n");
        goto cleanup;
    }
    if (rknn_init(&ctx, argv[1], 0, 0, NULL) < 0) {
        printf("rknn_init failed\n");
        goto cleanup;
    }
    if (rknn_query(ctx, RKNN_QUERY_SDK_VERSION, &version, sizeof(version)) < 0 ||
        rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &number, sizeof(number)) < 0)
        goto cleanup;
    printf("RKNN runtime %s; driver %s\n", version.api_version, version.drv_version);
    if (number.n_input != 1 || number.n_output != 3 ||
        rknn_query(ctx, RKNN_QUERY_NATIVE_INPUT_ATTR, &in, sizeof(in)) < 0)
        goto incompatible;
    if (in.n_dims != 4 || in.dims[0] != 1 || in.dims[1] != INPUT_SIZE ||
        in.dims[2] != INPUT_SIZE || in.dims[3] != 3 || in.fmt != RKNN_TENSOR_NHWC)
        goto incompatible;
    int stride = in.w_stride ? in.w_stride : INPUT_SIZE;
    if (stride < INPUT_SIZE || stride > 4096 ||
        in.size_with_stride < (uint32_t)(stride * INPUT_SIZE * 3) ||
        in.size_with_stride > 16 * 1024 * 1024)
        goto incompatible;
    in.type = RKNN_TENSOR_UINT8;
    input = rknn_create_mem(ctx, in.size_with_stride);
    if (!input || rknn_set_io_mem(ctx, input, &in) < 0)
        goto cleanup;
    for (int i = 0; i < 3; ++i) {
        out[i].index = i;
        if (rknn_query(ctx, RKNN_QUERY_NATIVE_NHWC_OUTPUT_ATTR, &out[i], sizeof(out[i])) < 0)
            goto cleanup;
        int grid = 80 >> i;
        printf("output %d: dims=[%u,%u,%u,%u] type=%d fmt=%d size=%u stride=%u zp=%d scale=%f\n",
            i, out[i].dims[0], out[i].dims[1], out[i].dims[2], out[i].dims[3],
            out[i].type, out[i].fmt, out[i].size, out[i].size_with_stride, out[i].zp, out[i].scale);
        if (out[i].n_dims != 4 || out[i].dims[0] != 1 ||
            out[i].dims[1] != (uint32_t)grid || out[i].dims[2] != (uint32_t)grid ||
            out[i].dims[3] != 255 || out[i].type != RKNN_TENSOR_INT8 ||
            out[i].fmt != RKNN_TENSOR_NHWC || out[i].qnt_type != RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC ||
            !(out[i].scale > 0) || out[i].size != (uint32_t)(grid * grid * 255) ||
            out[i].size_with_stride < out[i].size ||
            out[i].size_with_stride > (uint32_t)(grid * grid * 256))
            goto incompatible;
        outputs[i] = rknn_create_mem(ctx, out[i].size_with_stride);
        if (!outputs[i] || rknn_set_io_mem(ctx, outputs[i], &out[i]) < 0)
            goto cleanup;
    }
    memset(input->virt_addr, 114, input->size);
    letterbox(&image, input->virt_addr, stride, &width, &height, &left, &top);
    /* RV1106 零拷贝 API 在 rknn_run 内同步输入/输出缓存。 */
    if (clock_gettime(1, &begin) || rknn_run(ctx, NULL) < 0 || clock_gettime(1, &end))
        goto cleanup;
    for (int i = 0; i < 3; ++i) {
        count = decode(outputs[i]->virt_addr, &out[i], i, count);
        if (count < 0)
            goto cleanup;
    }
    double milliseconds = (end.sec - begin.sec) * 1000.0 + (end.nsec - begin.nsec) / 1000000.0;
    if (write_results(argv[3], &image, count, width, height, left, top, milliseconds))
        goto cleanup;
    result = 0;
    goto cleanup;
incompatible:
    printf("Unsupported model: require RV1106 INT8 YOLOv5 COCO 640x640, 3 dense NHWC heads\n");
cleanup:
    for (int i = 0; i < 3; ++i)
        if (outputs[i] && rknn_destroy_mem(ctx, outputs[i]) < 0)
            result = 1;
    if (input && rknn_destroy_mem(ctx, input) < 0)
        result = 1;
    if (ctx && rknn_destroy(ctx) < 0)
        result = 1;
    free(image.data);
    if (result)
        printf("RKNN image inference failed\n");
    return result;
}
