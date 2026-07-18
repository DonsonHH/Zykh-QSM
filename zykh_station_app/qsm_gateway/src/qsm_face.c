#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <limits.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include <inspireface.h>

#define CAMERA_WIDTH 640
#define CAMERA_HEIGHT 480
#define CAMERA_BUFFERS 4
#define MAX_NAMES 1024
#define MAX_NAME_BYTES 63

typedef struct {
    void *start;
    size_t length;
} MMapBuffer;

typedef struct {
    int fd;
    unsigned width;
    unsigned height;
    unsigned stride;
    MMapBuffer buffers[CAMERA_BUFFERS];
    unsigned buffer_count;
    uint8_t *bgr;
} Camera;

typedef struct {
    HFaceId id;
    char name[MAX_NAME_BYTES + 1];
} NameEntry;

typedef struct {
    NameEntry entries[MAX_NAMES];
    size_t count;
} NameMap;

static volatile sig_atomic_t g_running = 1;

static void on_signal(int signal_number) {
    (void)signal_number;
    g_running = 0;
}

static long long monotonic_ms(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (long long)now.tv_sec * 1000LL + now.tv_nsec / 1000000LL;
}

static void wall_time(char *buffer, size_t size) {
    time_t now = time(NULL);
    struct tm local;
    localtime_r(&now, &local);
    strftime(buffer, size, "%Y-%m-%d %H:%M:%S", &local);
}

static int xioctl(int fd, unsigned long request, void *argument) {
    int result;
    do {
        result = ioctl(fd, request, argument);
    } while (result < 0 && errno == EINTR);
    return result;
}

static uint8_t clamp_u8(int value) {
    if (value < 0) return 0;
    if (value > 255) return 255;
    return (uint8_t)value;
}

static void yuyv_to_bgr(const uint8_t *source, unsigned stride, uint8_t *target,
                        unsigned width, unsigned height) {
    for (unsigned y = 0; y < height; ++y) {
        const uint8_t *row = source + (size_t)y * stride;
        uint8_t *out = target + (size_t)y * width * 3;
        for (unsigned x = 0; x < width; x += 2) {
            int y0 = row[0] - 16;
            int u = row[1] - 128;
            int y1 = row[2] - 16;
            int v = row[3] - 128;
            if (y0 < 0) y0 = 0;
            if (y1 < 0) y1 = 0;

            int r0 = (298 * y0 + 409 * v + 128) >> 8;
            int g0 = (298 * y0 - 100 * u - 208 * v + 128) >> 8;
            int b0 = (298 * y0 + 516 * u + 128) >> 8;
            int r1 = (298 * y1 + 409 * v + 128) >> 8;
            int g1 = (298 * y1 - 100 * u - 208 * v + 128) >> 8;
            int b1 = (298 * y1 + 516 * u + 128) >> 8;

            out[0] = clamp_u8(b0);
            out[1] = clamp_u8(g0);
            out[2] = clamp_u8(r0);
            out[3] = clamp_u8(b1);
            out[4] = clamp_u8(g1);
            out[5] = clamp_u8(r1);
            row += 4;
            out += 6;
        }
    }
}

static int write_u16_le(FILE *file, uint16_t value) {
    uint8_t bytes[2] = {(uint8_t)(value & 0xff), (uint8_t)((value >> 8) & 0xff)};
    return fwrite(bytes, sizeof(bytes), 1, file) == 1 ? 0 : -1;
}

static int write_u32_le(FILE *file, uint32_t value) {
    uint8_t bytes[4] = {
        (uint8_t)(value & 0xff),
        (uint8_t)((value >> 8) & 0xff),
        (uint8_t)((value >> 16) & 0xff),
        (uint8_t)((value >> 24) & 0xff),
    };
    return fwrite(bytes, sizeof(bytes), 1, file) == 1 ? 0 : -1;
}

static int write_preview_bmp(const char *path, const uint8_t *bgr,
                             unsigned width, unsigned height) {
    if (!path || !*path || !bgr || width < 2 || height < 2) return 0;

    const unsigned scale = 2;
    const unsigned preview_width = width / scale;
    const unsigned preview_height = height / scale;
    const unsigned row_bytes = (preview_width * 3U + 3U) & ~3U;
    const uint32_t pixel_bytes = row_bytes * preview_height;
    const uint32_t file_bytes = 54U + pixel_bytes;
    char temporary[PATH_MAX];
    int written = snprintf(temporary, sizeof(temporary), "%s.%ld.tmp", path, (long)getpid());
    if (written < 0 || (size_t)written >= sizeof(temporary)) return -1;

    FILE *file = fopen(temporary, "wb");
    if (!file) return -1;
    int failed = 0;
    failed |= fwrite("BM", 2, 1, file) == 1 ? 0 : -1;
    failed |= write_u32_le(file, file_bytes);
    failed |= write_u16_le(file, 0);
    failed |= write_u16_le(file, 0);
    failed |= write_u32_le(file, 54);
    failed |= write_u32_le(file, 40);
    failed |= write_u32_le(file, preview_width);
    failed |= write_u32_le(file, preview_height);
    failed |= write_u16_le(file, 1);
    failed |= write_u16_le(file, 24);
    failed |= write_u32_le(file, 0);
    failed |= write_u32_le(file, pixel_bytes);
    failed |= write_u32_le(file, 2835);
    failed |= write_u32_le(file, 2835);
    failed |= write_u32_le(file, 0);
    failed |= write_u32_le(file, 0);

    const uint8_t padding[3] = {0, 0, 0};
    const unsigned padding_bytes = row_bytes - preview_width * 3U;
    for (unsigned output_y = 0; !failed && output_y < preview_height; ++output_y) {
        unsigned source_y = height - scale - output_y * scale;
        const uint8_t *source = bgr + (size_t)source_y * width * 3U;
        for (unsigned output_x = 0; output_x < preview_width; ++output_x) {
            if (fwrite(source + (size_t)output_x * scale * 3U, 3, 1, file) != 1) {
                failed = -1;
                break;
            }
        }
        if (!failed && padding_bytes && fwrite(padding, padding_bytes, 1, file) != 1) failed = -1;
    }

    if (!failed && (fflush(file) != 0 || fsync(fileno(file)) != 0)) failed = -1;
    if (fclose(file) != 0) failed = -1;
    if (!failed && rename(temporary, path) != 0) failed = -1;
    if (failed) unlink(temporary);
    return failed;
}

static void camera_close(Camera *camera) {
    if (camera->fd >= 0) {
        enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        xioctl(camera->fd, VIDIOC_STREAMOFF, &type);
    }
    for (unsigned i = 0; i < camera->buffer_count; ++i) {
        if (camera->buffers[i].start && camera->buffers[i].start != MAP_FAILED) {
            munmap(camera->buffers[i].start, camera->buffers[i].length);
        }
    }
    if (camera->fd >= 0) close(camera->fd);
    free(camera->bgr);
    memset(camera, 0, sizeof(*camera));
    camera->fd = -1;
}

static int camera_open(Camera *camera, const char *device) {
    memset(camera, 0, sizeof(*camera));
    camera->fd = -1;
    camera->fd = open(device, O_RDWR | O_NONBLOCK | O_CLOEXEC);
    if (camera->fd < 0) {
        fprintf(stderr, "Cannot open camera %s: %s\n", device, strerror(errno));
        return -1;
    }

    struct v4l2_capability capability;
    memset(&capability, 0, sizeof(capability));
    if (xioctl(camera->fd, VIDIOC_QUERYCAP, &capability) < 0) {
        fprintf(stderr, "VIDIOC_QUERYCAP failed: %s\n", strerror(errno));
        camera_close(camera);
        return -1;
    }
    if (!(capability.capabilities & V4L2_CAP_VIDEO_CAPTURE) ||
        !(capability.capabilities & V4L2_CAP_STREAMING)) {
        fprintf(stderr, "%s is not a streaming capture device\n", device);
        camera_close(camera);
        return -1;
    }

    struct v4l2_format format;
    memset(&format, 0, sizeof(format));
    format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    format.fmt.pix.width = CAMERA_WIDTH;
    format.fmt.pix.height = CAMERA_HEIGHT;
    format.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV;
    format.fmt.pix.field = V4L2_FIELD_ANY;
    if (xioctl(camera->fd, VIDIOC_S_FMT, &format) < 0) {
        fprintf(stderr, "VIDIOC_S_FMT failed: %s\n", strerror(errno));
        camera_close(camera);
        return -1;
    }
    if (format.fmt.pix.pixelformat != V4L2_PIX_FMT_YUYV) {
        fprintf(stderr, "Camera did not accept YUYV format\n");
        camera_close(camera);
        return -1;
    }
    camera->width = format.fmt.pix.width;
    camera->height = format.fmt.pix.height;
    camera->stride = format.fmt.pix.bytesperline;
    if (camera->stride < camera->width * 2) camera->stride = camera->width * 2;
    camera->bgr = malloc((size_t)camera->width * camera->height * 3);
    if (!camera->bgr) {
        fprintf(stderr, "Cannot allocate BGR frame buffer\n");
        camera_close(camera);
        return -1;
    }

    struct v4l2_streamparm parameters;
    memset(&parameters, 0, sizeof(parameters));
    parameters.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    parameters.parm.capture.timeperframe.numerator = 1;
    parameters.parm.capture.timeperframe.denominator = 30;
    xioctl(camera->fd, VIDIOC_S_PARM, &parameters);

    struct v4l2_requestbuffers request;
    memset(&request, 0, sizeof(request));
    request.count = CAMERA_BUFFERS;
    request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    request.memory = V4L2_MEMORY_MMAP;
    if (xioctl(camera->fd, VIDIOC_REQBUFS, &request) < 0 || request.count < 2) {
        fprintf(stderr, "VIDIOC_REQBUFS failed: %s\n", strerror(errno));
        camera_close(camera);
        return -1;
    }
    camera->buffer_count = request.count > CAMERA_BUFFERS ? CAMERA_BUFFERS : request.count;

    for (unsigned i = 0; i < camera->buffer_count; ++i) {
        struct v4l2_buffer buffer;
        memset(&buffer, 0, sizeof(buffer));
        buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buffer.memory = V4L2_MEMORY_MMAP;
        buffer.index = i;
        if (xioctl(camera->fd, VIDIOC_QUERYBUF, &buffer) < 0) {
            fprintf(stderr, "VIDIOC_QUERYBUF failed: %s\n", strerror(errno));
            camera_close(camera);
            return -1;
        }
        camera->buffers[i].length = buffer.length;
        camera->buffers[i].start = mmap(NULL, buffer.length, PROT_READ | PROT_WRITE,
                                        MAP_SHARED, camera->fd, buffer.m.offset);
        if (camera->buffers[i].start == MAP_FAILED) {
            fprintf(stderr, "mmap failed: %s\n", strerror(errno));
            camera_close(camera);
            return -1;
        }
        if (xioctl(camera->fd, VIDIOC_QBUF, &buffer) < 0) {
            fprintf(stderr, "VIDIOC_QBUF failed: %s\n", strerror(errno));
            camera_close(camera);
            return -1;
        }
    }

    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (xioctl(camera->fd, VIDIOC_STREAMON, &type) < 0) {
        fprintf(stderr, "VIDIOC_STREAMON failed: %s\n", strerror(errno));
        camera_close(camera);
        return -1;
    }
    fprintf(stderr, "Camera ready: %s %ux%u YUYV\n", device, camera->width, camera->height);
    return 0;
}

static int camera_next(Camera *camera) {
    struct pollfd descriptor = {.fd = camera->fd, .events = POLLIN};
    int ready;
    do {
        ready = poll(&descriptor, 1, 3000);
    } while (ready < 0 && errno == EINTR && g_running);
    if (ready == 0) {
        fprintf(stderr, "Camera frame timeout\n");
        return -1;
    }
    if (ready < 0) {
        fprintf(stderr, "Camera poll failed: %s\n", strerror(errno));
        return -1;
    }

    struct v4l2_buffer buffer;
    memset(&buffer, 0, sizeof(buffer));
    buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buffer.memory = V4L2_MEMORY_MMAP;
    if (xioctl(camera->fd, VIDIOC_DQBUF, &buffer) < 0) {
        if (errno == EAGAIN) return 1;
        fprintf(stderr, "VIDIOC_DQBUF failed: %s\n", strerror(errno));
        return -1;
    }
    if (buffer.index >= camera->buffer_count) {
        fprintf(stderr, "Camera returned invalid buffer index %u\n", buffer.index);
        return -1;
    }
    size_t minimum = (size_t)camera->stride * camera->height;
    if (buffer.bytesused < minimum) {
        fprintf(stderr, "Short YUYV frame: %u bytes, need %zu\n", buffer.bytesused, minimum);
        xioctl(camera->fd, VIDIOC_QBUF, &buffer);
        return 1;
    }
    yuyv_to_bgr(camera->buffers[buffer.index].start, camera->stride, camera->bgr,
                camera->width, camera->height);
    if (xioctl(camera->fd, VIDIOC_QBUF, &buffer) < 0) {
        fprintf(stderr, "VIDIOC_QBUF failed: %s\n", strerror(errno));
        return -1;
    }
    return 0;
}

static int valid_name(const char *name) {
    size_t length = strlen(name);
    if (length == 0 || length > MAX_NAME_BYTES) return 0;
    for (size_t i = 0; i < length; ++i) {
        if (name[i] == '\t' || name[i] == '\r' || name[i] == '\n') return 0;
    }
    return 1;
}

static void load_names(const char *path, NameMap *map) {
    memset(map, 0, sizeof(*map));
    FILE *file = fopen(path, "r");
    if (!file) return;
    while (map->count < MAX_NAMES) {
        long id;
        char name[MAX_NAME_BYTES + 1];
        if (fscanf(file, "%ld\t%63[^\n]\n", &id, name) != 2) break;
        map->entries[map->count].id = (HFaceId)id;
        snprintf(map->entries[map->count].name, sizeof(map->entries[map->count].name), "%s", name);
        map->count++;
    }
    fclose(file);
}

static const char *lookup_name(const NameMap *map, HFaceId id) {
    for (size_t i = 0; i < map->count; ++i) {
        if (map->entries[i].id == id) return map->entries[i].name;
    }
    return "unmapped";
}

static int append_name(const char *path, HFaceId id, const char *name, NameMap *map) {
    FILE *file = fopen(path, "a");
    if (!file) {
        fprintf(stderr, "Cannot open %s: %s\n", path, strerror(errno));
        return -1;
    }
    if (fprintf(file, "%ld\t%s\n", (long)id, name) < 0 || fflush(file) != 0 ||
        fsync(fileno(file)) != 0) {
        fprintf(stderr, "Cannot persist name mapping: %s\n", strerror(errno));
        fclose(file);
        return -1;
    }
    fclose(file);
    if (map->count < MAX_NAMES) {
        map->entries[map->count].id = id;
        snprintf(map->entries[map->count].name, sizeof(map->entries[map->count].name), "%s", name);
        map->count++;
    }
    return 0;
}

static int remove_subject(const char *path, const char *subject, NameMap *map) {
    char temporary[PATH_MAX];
    int written = snprintf(temporary, sizeof(temporary), "%s.%ld.tmp", path, (long)getpid());
    if (written < 0 || (size_t)written >= sizeof(temporary)) return 1;
    FILE *file = fopen(temporary, "w");
    if (!file) {
        fprintf(stderr, "Cannot open %s: %s\n", temporary, strerror(errno));
        return 1;
    }

    int removed = 0;
    int failed = 0;
    for (size_t i = 0; i < map->count; ++i) {
        NameEntry *entry = &map->entries[i];
        if (strcmp(entry->name, subject) == 0) {
            HResult result = HFFeatureHubFaceRemove(entry->id);
            if (result != HSUCCEED) {
                fprintf(stderr, "Cannot remove face id=%ld: %ld\n", (long)entry->id, (long)result);
                failed = 1;
                break;
            }
            removed++;
            continue;
        }
        if (fprintf(file, "%ld\t%s\n", (long)entry->id, entry->name) < 0) {
            failed = 1;
            break;
        }
    }
    if (!failed && (fflush(file) != 0 || fsync(fileno(file)) != 0)) failed = 1;
    if (fclose(file) != 0) failed = 1;
    if (!failed && rename(temporary, path) != 0) failed = 1;
    if (failed) {
        unlink(temporary);
        return 1;
    }
    printf("Removed subject %s: %d feature records\n", subject, removed);
    return 0;
}

static int ensure_data_directory(void) {
    if (mkdir("data", 0750) < 0 && errno != EEXIST) {
        fprintf(stderr, "Cannot create data directory: %s\n", strerror(errno));
        return -1;
    }
    return 0;
}

static int initialize_feature_hub(const char *database, float threshold) {
    HFFeatureHubConfiguration configuration;
    memset(&configuration, 0, sizeof(configuration));
    configuration.primaryKeyMode = HF_PK_AUTO_INCREMENT;
    configuration.enablePersistence = 1;
    configuration.persistenceDbPath = (HString)database;
    configuration.searchThreshold = threshold;
    configuration.searchMode = HF_SEARCH_MODE_EXHAUSTIVE;
    HResult result = HFFeatureHubDataEnable(configuration);
    if (result != HSUCCEED) {
        fprintf(stderr, "HFFeatureHubDataEnable failed: %ld\n", (long)result);
        return -1;
    }
    return 0;
}

static int process_camera(const char *mode, const char *name, int target_samples,
                          long max_frames, const char *camera_device,
                          const char *names_path, float threshold) {
    HOption options = strcmp(mode, "detect") == 0 ? HF_ENABLE_NONE : HF_ENABLE_FACE_RECOGNITION;
    HFSession session = NULL;
    HResult result = HFCreateInspireFaceSessionOptional(
        options, HF_DETECT_MODE_ALWAYS_DETECT, 8, 320, -1, &session);
    if (result != HSUCCEED) {
        fprintf(stderr, "HFCreateInspireFaceSession failed: %ld\n", (long)result);
        return 1;
    }
    HFSessionSetFilterMinimumFacePixelSize(session, 80);

    Camera camera;
    if (camera_open(&camera, camera_device) != 0) {
        HFReleaseInspireFaceSession(session);
        return 1;
    }

    HFFaceFeature feature = {0};
    if (strcmp(mode, "detect") != 0) {
        result = HFCreateFaceFeature(&feature);
        if (result != HSUCCEED) {
            fprintf(stderr, "HFCreateFaceFeature failed: %ld\n", (long)result);
            camera_close(&camera);
            HFReleaseInspireFaceSession(session);
            return 1;
        }
    }

    NameMap names;
    load_names(names_path, &names);
    long frame_number = 0;
    int enrolled = 0;
    long long last_report = 0;
    long long last_sample = 0;
    long long last_preview = 0;
    long long started = monotonic_ms();
    const char *preview_path = getenv("QSM_FACE_PREVIEW_BMP");
    long preview_interval_ms = 250;
    const char *preview_interval_text = getenv("QSM_FACE_PREVIEW_INTERVAL_MS");
    if (preview_interval_text) preview_interval_ms = strtol(preview_interval_text, NULL, 10);
    if (preview_interval_ms < 120) preview_interval_ms = 120;
    if (preview_interval_ms > 1000) preview_interval_ms = 1000;

    while (g_running && (max_frames <= 0 || frame_number < max_frames)) {
        int capture = camera_next(&camera);
        if (capture < 0) break;
        if (capture > 0) continue;
        frame_number++;

        HFImageData image = {
            .data = camera.bgr,
            .width = (HInt32)camera.width,
            .height = (HInt32)camera.height,
            .format = HF_STREAM_BGR,
            .rotation = HF_CAMERA_ROTATION_0,
        };
        HFImageStream stream = NULL;
        result = HFCreateImageStream(&image, &stream);
        if (result != HSUCCEED) {
            fprintf(stderr, "HFCreateImageStream failed: %ld\n", (long)result);
            break;
        }
        HFMultipleFaceData faces;
        memset(&faces, 0, sizeof(faces));
        result = HFExecuteFaceTrack(session, stream, &faces);
        if (result != HSUCCEED) {
            fprintf(stderr, "HFExecuteFaceTrack failed: %ld\n", (long)result);
            HFReleaseImageStream(stream);
            break;
        }

        long long now = monotonic_ms();
        if (preview_path && now - last_preview >= preview_interval_ms) {
            if (write_preview_bmp(preview_path, camera.bgr, camera.width, camera.height) != 0 &&
                last_preview == 0) {
                fprintf(stderr, "Cannot write face preview %s: %s\n", preview_path, strerror(errno));
            }
            last_preview = now;
        }
        if (strcmp(mode, "detect") == 0) {
            if (now - last_report >= 500) {
                char timestamp[32];
                wall_time(timestamp, sizeof(timestamp));
                printf("[%s] faces=%d", timestamp, faces.detectedNum);
                for (int i = 0; i < faces.detectedNum; ++i) {
                    HFaceRect box = faces.rects[i];
                    printf(" #%d=(%d,%d,%d,%d,%.3f)", i, box.x, box.y, box.width,
                           box.height, faces.detConfidence[i]);
                }
                printf("\n");
                fflush(stdout);
                last_report = now;
            }
        } else if (strcmp(mode, "enroll") == 0) {
            if (faces.detectedNum == 1 && now - last_sample >= 400) {
                HFaceRect box = faces.rects[0];
                if (box.width >= 100 && box.height >= 100) {
                    result = HFFaceFeatureExtractTo(session, stream, faces.tokens[0], feature);
                    if (result == HSUCCEED) {
                        HFFaceFeatureIdentity identity = {.id = -1, .feature = &feature};
                        HFaceId allocated_id = -1;
                        result = HFFeatureHubInsertFeature(identity, &allocated_id);
                        if (result == HSUCCEED && append_name(names_path, allocated_id, name, &names) == 0) {
                            enrolled++;
                            printf("Enrolled sample %d/%d: name=%s id=%ld confidence=%.3f\n",
                                   enrolled, target_samples, name, (long)allocated_id,
                                   faces.detConfidence[0]);
                            fflush(stdout);
                            last_sample = now;
                        } else {
                            fprintf(stderr, "Cannot insert enrollment feature: %ld\n", (long)result);
                        }
                    } else {
                        fprintf(stderr, "HFFaceFeatureExtractTo failed: %ld\n", (long)result);
                    }
                }
            } else if (now - last_report >= 1000) {
                printf("Waiting for exactly one face (found %d), samples=%d/%d\n",
                       faces.detectedNum, enrolled, target_samples);
                fflush(stdout);
                last_report = now;
            }
        } else {
            if (now - last_report >= 500) {
                char timestamp[32];
                wall_time(timestamp, sizeof(timestamp));
                if (faces.detectedNum == 0) {
                    printf("[%s] no-face\n", timestamp);
                }
                for (int i = 0; i < faces.detectedNum; ++i) {
                    result = HFFaceFeatureExtractTo(session, stream, faces.tokens[i], feature);
                    if (result != HSUCCEED) {
                        printf("[%s] face=%d feature-error=%ld\n", timestamp, i, (long)result);
                        continue;
                    }
                    HFloat confidence = 0.0f;
                    HFFaceFeatureIdentity identity = {.id = -1, .feature = NULL};
                    result = HFFeatureHubFaceSearch(feature, &confidence, &identity);
                    HFaceRect box = faces.rects[i];
                    if (result == HSUCCEED && identity.id >= 0 && confidence >= threshold) {
                        printf("[%s] MATCH name=%s id=%ld score=%.4f box=%d,%d,%d,%d\n",
                               timestamp, lookup_name(&names, identity.id), (long)identity.id,
                               confidence, box.x, box.y, box.width, box.height);
                    } else {
                        printf("[%s] UNKNOWN score=%.4f box=%d,%d,%d,%d\n",
                               timestamp, confidence, box.x, box.y, box.width, box.height);
                    }
                }
                fflush(stdout);
                last_report = now;
            }
        }

        HFReleaseImageStream(stream);
        if (strcmp(mode, "enroll") == 0 && enrolled >= target_samples) break;
    }

    long long elapsed = monotonic_ms() - started;
    fprintf(stderr, "Processed %ld frames in %.2f seconds (%.2f fps)\n", frame_number,
            elapsed / 1000.0, elapsed > 0 ? frame_number * 1000.0 / elapsed : 0.0);
    if (feature.data) HFReleaseFaceFeature(&feature);
    camera_close(&camera);
    HFReleaseInspireFaceSession(session);
    if (strcmp(mode, "enroll") == 0 && enrolled < target_samples) return 2;
    return 0;
}

static void print_usage(const char *program) {
    printf("QSM368ZP standalone face recognition\n\n");
    printf("Usage:\n");
    printf("  %s detect [frames]\n", program);
    printf("  %s enroll NAME [samples]\n", program);
    printf("  %s recognize [frames]\n", program);
    printf("  %s list\n", program);
    printf("  %s remove NAME\n", program);
    printf("  %s clear\n\n", program);
    printf("frames=0 means run until SIGINT/SIGTERM. Default enrollment samples: 10.\n");
}

int main(int argc, char **argv) {
    if (argc < 2 || strcmp(argv[1], "--help") == 0 || strcmp(argv[1], "-h") == 0) {
        print_usage(argv[0]);
        return argc < 2 ? 2 : 0;
    }
    const char *mode = argv[1];
    const char *model = getenv("QSM_FACE_MODEL");
    const char *camera = getenv("QSM_FACE_CAMERA");
    const char *database = getenv("QSM_FACE_DB");
    const char *names_path = getenv("QSM_FACE_NAMES");
    const char *threshold_text = getenv("QSM_FACE_THRESHOLD");
    if (!model) model = "./Gundam_RK356X";
    if (!camera) camera = "/dev/video23";
    if (!database) database = "./data/features.db";
    if (!names_path) names_path = "./data/names.tsv";
    float threshold = threshold_text ? strtof(threshold_text, NULL) : 0.45f;

    if (strcmp(mode, "clear") == 0) {
        int db_result = unlink(database);
        int db_errno = errno;
        int names_result = unlink(names_path);
        int names_errno = errno;
        if (db_result < 0 && db_errno != ENOENT) {
            fprintf(stderr, "Cannot remove %s: %s\n", database, strerror(db_errno));
            return 1;
        }
        if (names_result < 0 && names_errno != ENOENT) {
            fprintf(stderr, "Cannot remove %s: %s\n", names_path, strerror(names_errno));
            return 1;
        }
        printf("Face database cleared.\n");
        return 0;
    }

    const char *subject_name = NULL;
    int samples = 10;
    long max_frames = 0;
    if (strcmp(mode, "enroll") == 0) {
        if (argc < 3 || !valid_name(argv[2])) {
            fprintf(stderr, "enroll requires a name of 1-%d bytes without tabs/newlines\n", MAX_NAME_BYTES);
            return 2;
        }
        subject_name = argv[2];
        if (argc >= 4) samples = atoi(argv[3]);
        if (samples < 1 || samples > 100) {
            fprintf(stderr, "samples must be between 1 and 100\n");
            return 2;
        }
    } else if (strcmp(mode, "remove") == 0) {
        if (argc < 3 || !valid_name(argv[2])) {
            fprintf(stderr, "remove requires a name of 1-%d bytes without tabs/newlines\n", MAX_NAME_BYTES);
            return 2;
        }
        subject_name = argv[2];
    } else if (strcmp(mode, "detect") == 0 || strcmp(mode, "recognize") == 0) {
        if (argc >= 3) max_frames = strtol(argv[2], NULL, 10);
        if (max_frames < 0) {
            fprintf(stderr, "frames must be 0 or greater\n");
            return 2;
        }
    } else if (strcmp(mode, "list") != 0) {
        print_usage(argv[0]);
        return 2;
    }

    if (ensure_data_directory() != 0) return 1;
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    HFSetLogLevel(HF_LOG_WARN);
    HResult result = HFLaunchInspireFace(model);
    if (result != HSUCCEED) {
        fprintf(stderr, "HFLaunchInspireFace(%s) failed: %ld\n", model, (long)result);
        return 1;
    }
    result = HFSwitchImageProcessingBackend(HF_IMAGE_PROCESSING_CPU);
    if (result != HSUCCEED) {
        fprintf(stderr, "Cannot select CPU image backend: %ld\n", (long)result);
        HFTerminateInspireFace();
        return 1;
    }

    int exit_code = 0;
    if (strcmp(mode, "detect") != 0) {
        if (initialize_feature_hub(database, threshold) != 0) {
            HFTerminateInspireFace();
            return 1;
        }
    }

    if (strcmp(mode, "list") == 0) {
        NameMap names;
        load_names(names_path, &names);
        HInt32 database_count = 0;
        HFFeatureHubGetFaceCount(&database_count);
        printf("Feature records: %d\n", database_count);
        if (names.count == 0) printf("No enrolled names.\n");
        for (size_t i = 0; i < names.count; ++i) {
            printf("id=%ld name=%s\n", (long)names.entries[i].id, names.entries[i].name);
        }
    } else if (strcmp(mode, "remove") == 0) {
        NameMap names;
        load_names(names_path, &names);
        exit_code = remove_subject(names_path, subject_name, &names);
    } else {
        exit_code = process_camera(mode, subject_name, samples, max_frames, camera,
                                   names_path, threshold);
    }

    if (strcmp(mode, "detect") != 0) HFFeatureHubDataDisable();
    HFTerminateInspireFace();
    return exit_code;
}
