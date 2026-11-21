/*
 * UnLeash 2.0 — Pico2 UVC+MSC composite dongle firmware
 *
 * Two-phase USB jailbreak for the Unitree Go2:
 *
 *   Phase 1 (USB enumeration):
 *     The 1469-byte config descriptor contains malformed UVC descriptors
 *     that trigger a heap overflow in the kernel's USB Video Class driver.
 *     This overwrites core_pattern and core_name_size in kernel .data
 *     with a pipe handler command. No network or AES key needed.
 *
 *   Phase 2 (MSC probing):
 *     The MSC interface presents an OracleCFS disk image. When udev
 *     triggers blkid, the OCFS1 prober crashes (SIGSEGV). The kernel
 *     dumps core, the overwritten core_pattern pipe handler fires as
 *     root, and the payload script executes.
 *
 * Both phases happen automatically on USB plug-in.
 *
 * Target: RP2350 (Pico 2), Cortex-M33
 * Build:  Pico SDK 2.x + TinyUSB
 */

#include <stdio.h>
#include "pico/stdlib.h"
#include "tusb.h"

extern bool msc_is_enumerated(void);

#define LED_PIN 25

static void led_init(void) {
    gpio_init(LED_PIN);
    gpio_set_dir(LED_PIN, GPIO_OUT);
}

static void led_blink(int count, int ms) {
    for (int i = 0; i < count; i++) {
        gpio_put(LED_PIN, 1);
        sleep_ms(ms);
        gpio_put(LED_PIN, 0);
        sleep_ms(ms);
    }
}

int main(void) {
    stdio_init_all();
    led_init();

    /* 1 blink = boot */
    led_blink(1, 300);

    tusb_init();

    bool enumerated_signaled = false;

    while (true) {
        tud_task();

        if (!enumerated_signaled && msc_is_enumerated()) {
            enumerated_signaled = true;
            /* 3 rapid blinks = MSC enumerated, exploit chain active */
            led_blink(3, 100);
            /* Solid LED = both phases complete, payload should fire */
            gpio_put(LED_PIN, 1);
        }

        sleep_ms(1);
    }

    return 0;
}
