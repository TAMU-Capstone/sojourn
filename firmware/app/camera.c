/* camera.c — the imaging subsystem (spec §6.1).
 *
 * Captures render a deterministic procedural star field into the frame
 * buffer; the statistics registers are computed from the actual pixels, so
 * exposure objectives are verifiable from telemetry alone: overexposure
 * shows high SAT_PCT and few resolvable STARS.
 *
 * Capturing needs an attitude reference: the star tracker must be powered
 * and READY, else CSTAT.POINT_ERR is raised and no frame is taken.
 */
#include "app.h"

#define FB ((volatile uint8_t *)FRAMEBUF_BASE)
#define FB_W 64u
#define FB_H 64u

static uint32_t last_capture_s;

void camera_init(void)
{
    xmemset((void *)&CAM->cctrl, 0, sizeof(cam_reg_t));
    CAM->cctrl       = CCTRL_AUTO;
    CAM->target      = 0;
    CAM->exposure_ms = g_config.cam_exposure_ms;
    CAM->gain        = g_config.cam_gain;
    CAM->binning     = g_config.cam_binning;
    CAM->frame_addr  = FRAMEBUF_BASE;
    CAM->frame_len   = FRAMEBUF_SIZE;
    CAM->cstat       = CSTAT_READY;
    xmemset((void *)FB, 0, FRAMEBUF_SIZE);
}

static void plot(uint32_t x, uint32_t y, uint32_t v)
{
    if (x < FB_W && y < FB_H) {
        uint32_t p = (uint32_t)FB[y * FB_W + x] + v;
        FB[y * FB_W + x] = (p > 255u) ? 255u : (uint8_t)p;
    }
}

static void do_capture(void)
{
    /* Attitude reference required (cross-subsystem dependency). */
    sensor_reg_t *str = &SENSORS[SLOT_STR];
    if (!(str->ctrl & SCTRL_POWER) || !(str->status & SSTAT_READY)) {
        CAM->cstat |= CSTAT_POINTERR;
        return;
    }
    CAM->cstat &= ~(uint32_t)CSTAT_POINTERR;
    CAM->cstat |= CSTAT_BUSY;
    SENSORS[SLOT_CAM].power_mw = 240u;        /* imaging draw               */

    const target_t *t = &g_config.catalog[CAM->target & 7u];
    uint32_t seed = ((uint32_t)t->ra * 2654435761u)
                  ^ ((uint32_t)(uint16_t)t->dec * 40503u)
                  ^ 0x534A0000u;
    if (!seed) seed = 1;

    /* Background: faint deterministic sky noise. */
    uint32_t bgrng = seed ^ 0xBADC0DEu;
    for (uint32_t i = 0; i < FRAMEBUF_SIZE; i++)
        FB[i] = (uint8_t)(xorshift32(&bgrng) & 0x7u);

    /* Stars: count and placement fixed by the catalog entry; brightness
     * through the exposure chain.  scale = exposure_ms * gain / 4096. */
    uint32_t nstars = 6u + (seed % 10u);
    uint32_t resolvable = 0;
    for (uint32_t s = 0; s < nstars; s++) {
        uint32_t x = 2u + xorshift32(&seed) % (FB_W - 4u);
        uint32_t y = 2u + xorshift32(&seed) % (FB_H - 4u);
        uint32_t base = 30u + xorshift32(&seed) % 140u;
        uint32_t core = (base * CAM->exposure_ms * CAM->gain) >> 12;
        plot(x, y, core);
        plot(x - 1, y, core / 2u); plot(x + 1, y, core / 2u);
        plot(x, y - 1, core / 2u); plot(x, y + 1, core / 2u);
        uint32_t px = FB[y * FB_W + x];
        if (px >= 120u && px < 250u) resolvable++;
    }

    /* Statistics from the actual pixels. */
    uint32_t sum = 0, max = 0, sat = 0;
    for (uint32_t i = 0; i < FRAMEBUF_SIZE; i++) {
        uint32_t p = FB[i];
        sum += p;
        if (p > max) max = p;
        if (p >= 250u) sat++;
    }
    CAM->hist_mean = sum / FRAMEBUF_SIZE;
    CAM->hist_max  = max;
    CAM->sat_pct   = (sat * 100u) / FRAMEBUF_SIZE;
    CAM->stars     = resolvable;
    CAM->frame_id++;

    SENSORS[SLOT_CAM].power_mw = 60u;
    CAM->cstat &= ~(uint32_t)CSTAT_BUSY;
    last_capture_s = uptime_s();
}

/* 1 Hz task. */
void task_camera(void)
{
    sensor_reg_t *cam = &SENSORS[SLOT_CAM];
    if (!(cam->ctrl & SCTRL_POWER)) {
        CAM->cstat &= ~(uint32_t)CSTAT_READY;
        return;
    }
    CAM->cstat |= CSTAT_READY;
    if (cam->power_mw == 0)
        cam->power_mw = 60u;                  /* idle draw when powered */

    if (CAM->cctrl & CCTRL_CAPTURE) {
        CAM->cctrl &= ~(uint32_t)CCTRL_CAPTURE;   /* self-clearing */
        do_capture();
    } else if ((CAM->cctrl & CCTRL_AUTO) &&
               uptime_s() - last_capture_s >= g_config.cam_auto_period_s) {
        do_capture();
    }
}
