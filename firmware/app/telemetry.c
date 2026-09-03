/* telemetry.c — downlink frame encoder (spec §9).
 *
 * Frame:  SYNC(2)=EB90  LEN(1)  payload  CRC16(2)
 * Payload: FRAME_CNT(2) UPTIME(4) MODE(1) REBOOTS(1) LAST_FAULT(1)
 *          BUS_MV(2) LOAD_MW(2)  then TLV channels.
 * LEN = payload byte count.  CRC-16/CCITT over LEN + payload.
 * Emitted as an ASCII line: "TLM " + hex + CRLF.
 *
 * A sensor's channel is PRESENT only when it was staged by the polling
 * task (powered AND polled) — a disabled sensor VANISHES, it does not
 * read zero.  In SAFE mode only the header is sent.
 */
#include "app.h"

static uint16_t frame_cnt;
static uint8_t  frame[96];

uint16_t g_last_cmd_crc;

void telemetry_init(void) { frame_cnt = 0; }

static uint32_t put8(uint32_t o, uint8_t v)  { frame[o] = v; return o + 1; }
static uint32_t put16(uint32_t o, uint16_t v){ frame[o] = (uint8_t)(v >> 8); frame[o+1] = (uint8_t)v; return o + 2; }
static uint32_t put32(uint32_t o, uint32_t v){ o = put16(o, (uint16_t)(v >> 16)); return put16(o, (uint16_t)v); }

PATCH_ENTRY void task_telemetry(void)
{
    uint32_t o = 3;                            /* leave room for SYNC+LEN   */

    o = put16(o, frame_cnt++);
    o = put32(o, uptime_s());
    o = put8 (o, (uint8_t)g_mode);
    o = put8 (o, (uint8_t)NOINIT->reboot_count);
    o = put8 (o, (uint8_t)NOINIT->last_fault);
    o = put16(o, (uint16_t)g_bus_mv);
    o = put16(o, (uint16_t)g_load_mw);

    if (g_mode != MODE_SAFE) {
        /* Sensor channels: TLV {slot, 4, DATA} for each staged sensor. */
        for (uint8_t i = 0; i <= SLOT_STR; i++) {
            if (!tlm_valid[i]) continue;
            o = put8(o, i);
            o = put8(o, 4);
            o = put32(o, (uint32_t)tlm_stage[i]);
        }
        /* Camera metadata channel 0x43 (after first capture). */
        if ((SENSORS[SLOT_CAM].ctrl & SCTRL_POWER) && CAM->frame_id > 0) {
            o = put8(o, CH_CAM);
            o = put8(o, 12);
            o = put16(o, (uint16_t)CAM->frame_id);
            o = put16(o, (uint16_t)CAM->target);
            o = put16(o, (uint16_t)CAM->exposure_ms);
            o = put16(o, (uint16_t)CAM->hist_mean);
            o = put16(o, (uint16_t)CAM->sat_pct);
            o = put16(o, (uint16_t)CAM->stars);
        }
        /* Housekeeping channel 0x60 — auxiliary flight functions (§6.4). */
        o = put8(o, CH_HK);
        o = put8(o, 8);
        o = put8(o, g_heater_on);
        o = put8(o, g_shed_count);
        o = put16(o, g_propellant_mg);
        o = put16(o, (uint16_t)g_momentum);
        {
            uint32_t pct = g_config.rec_buffer_max
                ? (uint32_t)g_rec_fill * 100u / g_config.rec_buffer_max : 0u;
            o = put8(o, (uint8_t)pct);
        }
        o = put8(o, g_auth);

        /* AUX channel 0x5A — absent from the recovered manual (R10.2). */
        o = put8(o, CH_AUX);
        o = put8(o, 2);
        o = put16(o, g_last_cmd_crc);
    }

    uint32_t paylen = o - 3;
    frame[0] = (uint8_t)(TLM_SYNC >> 8);
    frame[1] = (uint8_t)TLM_SYNC;
    frame[2] = (uint8_t)paylen;
    uint16_t crc = crc16_ccitt(&frame[2], paylen + 1);
    o = put16(o, crc);

    uart_puts("TLM ");
    for (uint32_t i = 0; i < o; i++) uart_put_hex8(frame[i]);
    uart_puts("\r\n");
}
