#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <string.h>
#include <errno.h>

#define GPIO_NUM 27  // GPIO0_D3 = 0*32 + 3*8 + 3 = 27

// 导出 GPIO
int export_gpio(int gpio) {
    int fd = open("/sys/class/gpio/export", O_WRONLY);
    if (fd < 0) {
        perror("Failed to open /sys/class/gpio/export");
        return -1;
    }

    char buf[32];
    snprintf(buf, sizeof(buf), "%d", gpio);
    ssize_t ret = write(fd, buf, strlen(buf));
    close(fd);

    if (ret < 0) {
        if (errno == EBUSY) {
            printf("GPIO %d already exported.\n", gpio);
            return 0; // 已导出不算错误
        }
        perror("Failed to export GPIO");
        return -1;
    }
    return 0;
}

// 设置方向 ("in" 或 "out")
int set_direction(int gpio, const char* dir) {
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/direction", gpio);

    int fd = open(path, O_WRONLY);
    if (fd < 0) {
        perror("Failed to open direction file");
        return -1;
    }

    ssize_t ret = write(fd, dir, strlen(dir));
    close(fd);
    return (ret < 0) ? -1 : 0;
}

// 写入值 (0 or 1)
int write_value(int gpio, int value) {
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/value", gpio);

    int fd = open(path, O_WRONLY);
    if (fd < 0) {
        perror("Failed to open value file for writing");
        return -1;
    }

    char val = (value ? '1' : '0');
    ssize_t ret = write(fd, &val, 1);
    close(fd);
    return (ret < 0) ? -1 : 0;
}

// 读取值（返回 0/1，失败返回 -1）
int read_value(int gpio) {
    char path[64];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%d/value", gpio);

    int fd = open(path, O_RDONLY);
    if (fd < 0) {
        perror("Failed to open value file for reading");
        return -1;
    }

    char ch;
    ssize_t ret = read(fd, &ch, 1);
    close(fd);

    if (ret <= 0) return -1;
    return (ch == '1') ? 1 : 0;
}

// 取消导出 GPIO（可选）
void unexport_gpio(int gpio) {
    int fd = open("/sys/class/gpio/unexport", O_WRONLY);
    if (fd < 0) {
        perror("Failed to open unexport");
        return;
    }
    char buf[32];
    snprintf(buf, sizeof(buf), "%d", gpio);
    write(fd, buf, strlen(buf));
    close(fd);
}

// 延迟毫秒（使用 usleep）
void delay_ms(unsigned int ms) {
    usleep(ms * 1000);
}

int main() {
    printf("=== Controlling GPIO0_D3 (GPIO%d) ===\n", GPIO_NUM);

    // 1. 导出 GPIO
    if (export_gpio(GPIO_NUM) != 0) {
        fprintf(stderr, "Error: Could not export GPIO %d\n", GPIO_NUM);
        return 1;
    }

    // 2. 设置为输出
    if (set_direction(GPIO_NUM, "out") != 0) {
        fprintf(stderr, "Error: Could not set direction to 'out'\n");
        return 1;
    }

    // 3. 闪烁 3 次
    printf("Flashing GPIO%d (3 times)...\n", GPIO_NUM);
    for (int i = 0; i < 3; i++) {
        if (write_value(GPIO_NUM, 1) != 0) {
            fprintf(stderr, "Warning: Failed to write HIGH\n");
        }
        delay_ms(500);
		fprintf(stderr, "Successed to write HIGH for 500ms\n");

        if (write_value(GPIO_NUM, 0) != 0) {
            fprintf(stderr, "Warning: Failed to write LOW\n");
        }
        delay_ms(500);
		fprintf(stderr, "Successed to write Low for 500ms\n");
    }

    // 4. 读取当前值
    int val = read_value(GPIO_NUM);
    if (val >= 0) {
        printf("Current GPIO%d value: %d\n", GPIO_NUM, val);
    }

    // 5. （可选）取消导出
    // 取消下面的注释以自动取消导出
    // printf("Unexporting GPIO %d...\n", GPIO_NUM);
    // unexport_gpio(GPIO_NUM);

    printf("Done.\n");
    return 0;
}