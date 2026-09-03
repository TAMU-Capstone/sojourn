/*
 * comms.c — downlink antenna and bandwidth management (spec §6.7).
 *
 * Real precedent: Galileo's high-gain antenna failed to unfurl in 1991,
 * and the mission was saved by reprogramming the spacecraft in flight to
 * run science through the low-gain antenna — new compression, and hard
 * decisions about which data was worth the bandwidth. This subsystem is
 * that scenario in miniature.
 *
 * Sojourn downlinks through one of two antennas:
 *
 *   HGA  high gain, narrow beam — the full telemetry frame fits
 *   LGA  low gain, wide beam    — a fraction of the payload budget, so
 *                                 channels must be dropped
 *
 * When the HGA is declared failed the probe falls back to the LGA on its
 * own, and the telemetry encoder (telemetry.c) starts emitting channels
 * in the order given by tlm_priority[] until the budget is exhausted,
 * counting what it had to drop. Everything a ground team could do about
 * that is a patch:
 *
 *   tlm_priority[]        which data survives the squeeze (the Galileo
 *                         decision, as a byte array in RAM)
 *   lga_max_payload       the bandwidth figure itself
 *   hga_fail_after_s      the scripted failure the scenario schedules
 *   g_hga_ok / g_antenna  the fault verdict and the antenna selection
 *   task_comms            the fallback logic itself (entry pad + patch
 *                         point, §6.5)
 */
#include "app.h"

uint8_t  g_antenna;                 /* ANT_HGA / ANT_LGA                 */
uint8_t  g_hga_ok;                  /* health verdict for the high gain  */
uint8_t  g_tlm_dropped;             /* channels dropped in the last frame */
uint8_t  tlm_priority[N_TLM_PRIORITY];

void comms_init(void)
{
    g_antenna    = ANT_HGA;
    g_hga_ok     = 1;
    g_tlm_dropped = 0;

    /* Emission order, most important first. Link state and spacecraft
     * health outrank science — which is exactly the judgement a scenario
     * may want the player to overrule. */
    static const uint8_t order[N_TLM_PRIORITY] = {
        CH_COMMS, CH_HK,
        SLOT_MAG, SLOT_IMU, SLOT_THM, SLOT_PWR, SLOT_RAD, SLOT_STR,
        CH_CAM, CH_AUX,
    };
    for (uint32_t i = 0; i < N_TLM_PRIORITY; i++)
        tlm_priority[i] = order[i];
}

/* Payload bytes the current antenna can carry. */
uint32_t comms_budget(void)
{
    return (g_antenna == ANT_LGA) ? g_config.lga_max_payload
                                  : g_config.hga_max_payload;
}

/* 1 Hz. Declares the high-gain antenna failed on the scenario's schedule
 * and falls back to the low gain. A ground team that disagrees with the
 * verdict can patch it — which is the whole objective. */
PATCH_ENTRY void task_comms(void)
{
    if (!g_config.comms_enable)
        return;

    if (g_config.hga_fail_after_s &&
        uptime_s() >= g_config.hga_fail_after_s)
        g_hga_ok = 0;

    PATCH_POINT();          /* room to detour the fallback decision */
    if (!g_hga_ok)
        g_antenna = ANT_LGA;
    else if (g_antenna == ANT_LGA && g_hga_ok)
        g_antenna = ANT_HGA;            /* recovers if the verdict clears */
}
