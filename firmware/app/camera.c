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

/* Roughly one capture in a hundred returns something the catalog cannot
 * command. Advanced per capture from a fixed seed rather than from the
 * clock, so a replayed command log reproduces it exactly — the platform's
 * saves are command-log replays. */
static uint32_t cam_roll;

/* Percentage of captures that return the easter-egg scene. Scenario- and
 * test-controllable: 0 disables it, 100 forces it. */
uint8_t g_cam_egg_pct;

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
    imaging_init();
    cam_roll = 0x4D1A5A17u;
    g_cam_egg_pct = 1u;
    xmemset((void *)FB, 0, FRAMEBUF_SIZE);
}

/* Which stored scene the commanded target shows (scenes.c). */
const uint8_t *scene_for_target(uint32_t target)
{
    const target_t *t = &g_config.catalog[target & 7u];
    uint32_t idx = t->scene;
    if (idx >= SCENE_COUNT) idx = 0u;
    return SCENE_AT(idx);                 /* read straight from ROM store */
}

static int easter_roll(uint32_t target)
{
    if (g_cam_egg_pct == 0u) return 0;
    cam_roll ^= target * 2654435761u;
    return (xorshift32(&cam_roll) % 100u) < g_cam_egg_pct;
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

    /* Read the stored scene for this target, run it through the imaging
     * pipeline, and write the result into the frame buffer (imaging.c). */
    const uint8_t *src = easter_roll(CAM->target)
                       ? SCENE_AT(SCENE_EASTER)
                       : scene_for_target(CAM->target);
    image_process(src, (uint8_t *)FB);

    /* Statistics computed from the pixels actually written to the frame
     * buffer, so they describe the downlinked product, not the source. */
    uint32_t sum = 0, max = 0, sat = 0, bright = 0;
    for (uint32_t i = 0; i < SCENE_PIXELS; i++) {
        uint32_t p = FB[i];
        sum += p;
        if (p > max) max = p;
        if (p >= 250u) sat++;                 /* clipped                   */
    }
    /* Resolved sources: bright, unclipped LOCAL MAXIMA. A flat bright
     * field — an overexposed frame — has none, so this counts real point
     * sources rather than merely bright pixels. */
    for (uint32_t y = 1; y < SCENE_H - 1u; y++) {
        for (uint32_t x = 1; x < SCENE_W - 1u; x++) {
            uint32_t p = FB[y * SCENE_W + x];
            if (p < 180u || p >= 250u) continue;
            if (p >  FB[y * SCENE_W + x - 1] &&
                p >= FB[y * SCENE_W + x + 1] &&
                p >  FB[(y - 1) * SCENE_W + x] &&
                p >= FB[(y + 1) * SCENE_W + x])
                bright++;
        }
    }
    CAM->hist_mean = sum / SCENE_PIXELS;
    CAM->hist_max  = max;
    CAM->sat_pct   = (sat * 100u) / SCENE_PIXELS;
    CAM->stars     = bright;
    CAM->frame_id++;

    SENSORS[SLOT_CAM].power_mw = 60u;
    CAM->cstat &= ~(uint32_t)CSTAT_BUSY;
    last_capture_s = uptime_s();
}

/* 1 Hz task. */
PATCH_ENTRY void task_camera(void)
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
