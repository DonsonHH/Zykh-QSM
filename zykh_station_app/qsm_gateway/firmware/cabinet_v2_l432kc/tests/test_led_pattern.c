#include <stdint.h>
#include <stdio.h>

uint32_t cabinet_v2_pixel_brightness(uint32_t led, uint32_t enabled);

int main(void) {
    static const uint8_t expected[64] = {
        30, 30, 30, 30, 30, 30, 30, 30,
         0,  0,  0,  0,  0,  0,  0,  0,
         0,  0,  0,  0,  0,  0,  0,  0,
         0,  0,  0,  0,  0,  0,  0,  0,
         0,  0,  0,  0,  0,  0,  0,  0,
        30, 30, 30, 30, 30, 30, 30, 30,
        30, 30, 30, 30, 30, 30, 30, 30,
        30, 30, 30, 30, 30, 30, 30, 30,
    };
    uint32_t active = 0u;
    uint32_t led;

    for (led = 0u; led < 64u; ++led) {
        uint32_t actual = cabinet_v2_pixel_brightness(led, 1u);
        if (actual != expected[led]) {
            fprintf(stderr,
                    "LED_PATTERN FAIL led=%lu expected=%u actual=%lu\n",
                    (unsigned long)led,
                    (unsigned int)expected[led],
                    (unsigned long)actual);
            return 1;
        }
        if (actual != 0u) {
            ++active;
        }
        if (cabinet_v2_pixel_brightness(led, 0u) != 0u) {
            fprintf(stderr, "LED_PATTERN FAIL disabled_led=%lu\n",
                    (unsigned long)led);
            return 1;
        }
    }

    if (active != 32u ||
        cabinet_v2_pixel_brightness(64u, 1u) != 0u ||
        cabinet_v2_pixel_brightness(UINT32_MAX, 1u) != 0u) {
        fprintf(stderr, "LED_PATTERN FAIL active=%lu bounds=invalid\n",
                (unsigned long)active);
        return 1;
    }

    puts("LED_PATTERN PASS active_leds=32 rows=1,6,7,8 brightness=30");
    return 0;
}
