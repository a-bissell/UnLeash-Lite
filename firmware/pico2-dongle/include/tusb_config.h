#ifndef TUSB_CONFIG_H
#define TUSB_CONFIG_H

#include "pico.h"

/* Board-agnostic — Pico SDK sets the right MCU */
#define CFG_TUSB_OS           OPT_OS_PICO
#define CFG_TUSB_RHPORT0_MODE OPT_MODE_DEVICE

#define CFG_TUD_ENDPOINT0_SIZE 64

/*
 * The exploit config descriptor declares 30 interfaces (UVC + vendor
 * placeholders + MSC). TinyUSB iterates through all of them during
 * SET_CONFIGURATION to find class drivers. Only MSC matches.
 */
#define CFG_TUD_INTERFACE_MAX 30

/*
 * Endpoints used in the exploit config descriptor:
 *   EP 0x81 — UVC Bulk IN (declared but unused by TinyUSB)
 *   EP 0x82 — MSC Bulk IN
 *   EP 0x83 — UVC Interrupt IN (declared but unused by TinyUSB)
 *   EP 0x02 — MSC Bulk OUT
 * TinyUSB only opens the MSC endpoints; the others are skipped.
 */
#define CFG_TUD_ENDPOINT_MAX 4

/* MSC only — Go2 kernel has no USB Ethernet host drivers */
#define CFG_TUD_MSC  1

/* MSC buffer sizes */
#define CFG_TUD_MSC_EP_BUFSIZE 512

#endif
