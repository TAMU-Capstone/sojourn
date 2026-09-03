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
 *
 * Channels are emitted in the order given by tlm_priority[] (comms.c)
 * and only while they fit the current antenna's payload budget, so a
 * low-gain fallback squeezes out whatever the priority table ranks last
 * (spec §6.7). Anything that did not fit is counted in g_tlm_dropped.
 */
#include "app.h"

static uint16_t frame_cnt;
static uint8_t  frame[128];

uint16_t g_last_cmd_crc;

void telemetry_init(void) { frame_cnt = 0; }

static uint32_t put8(uint32_t o, uint8_t v)  { frame[o] = v; return o + 1; }
static uint32_t put16(uint32_t o, uint16_t v){ frame[o] = (uint8_t)(v >> 8); frame[o+1] = (uint8_t)v; return o + 2; }
static uint32_t put32(uint32_t o, uint32_t v){ o = put16(o, (uint16_t)(v >> 16)); return put16(o, (uint16_t)v); }

/* Bytes this channel would add, or 0 if it has nothing to say. */
static uint32_t chan_size(uint8_t id)
{
    switch (id) {
    case SLOT_MAG: case SLOT_IMU: case SLOT_THM:
    case SLOT_PWR: case SLOT_RAD: case SLOT_STR:
        return tlm_valid[id] ? 6u : 0u;
    case CH_CAM:
        return ((SENSORS[SLOT_CAM].ctrl & SCTRL_POWER) && CAM->frame_id) ? 14u : 0u;
    case CH_HK:    return 10u;
    case CH_AUX:   return 4u;
    case CH_COMMS: return 6u;
    default:       return 0u;
    }
}

static uint32_t chan_emit(uint32_t o, uint8_t id)
{
    switch (id) {
    case SLOT_MAG: case SLOT_IMU: case SLOT_THM:
    case SLOT_PWR: case SLOT_RAD: case SLOT_STR:
        o = put8(o, id);
        o = put8(o, 4);
        return put32(o, (uint32_t)tlm_stage[id]);

    case CH_CAM:
        o = put8(o, CH_CAM);
        o = put8(o, 12);
        o = put16(o, (uint16_t)CAM->frame_id);
        o = put16(o, (uint16_t)CAM->target);
        o = put16(o, (uint16_t)CAM->exposure_ms);
        o = put16(o, (uint16_t)CAM->hist_mean);
        o = put16(o, (uint16_t)CAM->sat_pct);
        return put16(o, (uint16_t)CAM->stars);

    case CH_HK:
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
        return put8(o, g_auth);

    case CH_COMMS:
        o = put8(o, CH_COMMS);
        o = put8(o, 4);
        o = put8(o, g_antenna);
        o = put8(o, g_tlm_dropped);
        return put16(o, (uint16_t)comms_budget());

    case CH_AUX:
        o = put8(o, CH_AUX);
        o = put8(o, 2);
        return put16(o, g_last_cmd_crc);

    default:
        return o;
    }
}

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
        /* Emit in priority order while the antenna's budget lasts. What
         * does not fit is dropped, not truncated — a partial channel
         * would corrupt the frame. */
        uint32_t budget = comms_budget();
        uint32_t used = o - 3u;
        uint32_t dropped = 0;
        uint8_t  fits[N_TLM_PRIORITY];

        PATCH_POINT();      /* room to detour the bandwidth triage */

        /* Decide first, emit second: the COMMS channel reports the drop
         * count for THIS frame, and it is emitted before the loop that
         * would otherwise compute it. */
        for (uint32_t i = 0; i < N_TLM_PRIORITY; i++) {
            uint32_t sz = chan_size(tlm_priority[i]);
            if (sz == 0u) { fits[i] = 0; continue; }
            if (used + sz > budget) { fits[i] = 0; dropped++; continue; }
            used += sz;
            fits[i] = 1;
        }
        g_tlm_dropped = (uint8_t)dropped;

        for (uint32_t i = 0; i < N_TLM_PRIORITY; i++)
            if (fits[i])
                o = chan_emit(o, tlm_priority[i]);
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
