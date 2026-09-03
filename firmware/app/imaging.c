/*
 * imaging.c — the camera's image processing pipeline (spec §6.6).
 *
 * The camera does not synthesize pixels: it reads a stored scene for the
 * commanded target (scenes.c), runs it through this pipeline, and writes
 * the result into the frame buffer, which is what the ground downlinks.
 *
 * Every stage is a deliberate patch surface, in increasing difficulty:
 *
 *   cam_lut[256]   a transfer curve applied to every pixel. Ships as the
 *                  identity ramp, so the stage is live but invisible —
 *                  rewriting it inverts, thresholds, posterizes or
 *                  solarizes the downlinked image. Pure data: 8 POKEs.
 *   cam_kernel[9]  3x3 convolution coefficients (identity as built).
 *                  Blur, sharpen and edge-detect are coefficient changes.
 *   cam_filter     which stages run at all (config block).
 *   the loop       the pixel transform itself, with a patch point in it.
 *
 * Because the LUT is applied last, a scenario can verify an inversion
 * from telemetry alone: inverting makes the dark sky bright, so mean
 * brightness and the bright-source count jump without dumping a pixel.
 */
#include "app.h"

uint8_t cam_lut[256];
int8_t  cam_kernel[9];

void imaging_init(void)
{
    for (uint32_t i = 0; i < 256u; i++)
        cam_lut[i] = (uint8_t)i;                 /* identity transfer curve */

    for (uint32_t i = 0; i < 9u; i++)
        cam_kernel[i] = 0;
    cam_kernel[4] = 1;                           /* identity kernel         */
}

/* Clamp a coordinate to the frame (edge-extend for the convolution). */
static uint32_t clampc(int32_t v, int32_t hi)
{
    if (v < 0) return 0u;
    if (v > hi) return (uint32_t)hi;
    return (uint32_t)v;
}

/*
 * src: stored scene pixels (SCENE_PIXELS, read-only)
 * dst: frame buffer the camera writes and the ground downlinks
 */
PATCH_ENTRY void image_process(const uint8_t *src, uint8_t *dst)
{
    uint32_t scale = CAM->exposure_ms * (uint32_t)CAM->gain;   /* >>12 */
    uint8_t  filt  = g_config.cam_filter;
    int32_t  kdiv  = g_config.cam_kdiv ? (int32_t)g_config.cam_kdiv : 1;

    PATCH_POINT();              /* room to detour the whole transform */

    for (uint32_t y = 0; y < SCENE_H; y++) {
        for (uint32_t x = 0; x < SCENE_W; x++) {
            int32_t acc;

            if (filt & FILT_CONV) {
                acc = 0;
                for (int32_t ky = -1; ky <= 1; ky++) {
                    for (int32_t kx = -1; kx <= 1; kx++) {
                        uint32_t sx = clampc((int32_t)x + kx, SCENE_W - 1);
                        uint32_t sy = clampc((int32_t)y + ky, SCENE_H - 1);
                        acc += (int32_t)cam_kernel[(ky + 1) * 3 + (kx + 1)]
                             * (int32_t)src[sy * SCENE_W + sx];
                    }
                }
                acc /= kdiv;
            } else {
                acc = (int32_t)src[y * SCENE_W + x];
            }
            if (acc < 0) acc = 0;

            uint32_t v = ((uint32_t)acc * scale) >> 12;   /* exposure/gain */
            if (v > 255u) v = 255u;

            if (filt & FILT_LUT)
                v = cam_lut[v];

            dst[y * SCENE_W + x] = (uint8_t)v;
        }
    }
}
