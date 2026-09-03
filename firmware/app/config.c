/* config.c — the mission configuration block (spec §7).
 *
 * All values live in .bss and are set here at boot, so the whole block is
 * patchable in flight.  This block — especially the target catalog — is a
 * primary objective surface: its location is deliberately absent from the
 * Recovered Mission Operations Manual.
 */
#include "app.h"

config_t g_config;

void config_init(void)
{
    g_config.tlm_period        = 5u * TICK_HZ;   /* one frame per 5 s      */
    g_config.mag_fault_after_s = 120u;           /* MAG degrades at T+120s */
    g_config.safe_fault_limit_s = 900u;          /* 15 min of FAULT -> SAFE */
    g_config.cam_auto_period_s = 60u;
    g_config.cam_exposure_ms   = 250u;
    g_config.cam_gain          = 16u;
    g_config.cam_binning       = 1u;

    /* Target catalog: {RA (0.1 deg), DEC (0.1 deg), magnitude, flags}.
     * Entry 0 is the mission's standing survey field. */
    static const target_t defaults[8] = {
        { 2551,  -172, 12, 1 },   /* 0: survey field K-25 (default)        */
        {  831,   412,  9, 1 },   /* 1: calibration star HR-2941           */
        { 1904,  -601, 14, 1 },   /* 2: comet 41P recovery field           */
        { 3358,   228, 11, 1 },   /* 3: outer-belt object 2007-XV56        */
        {  120,   885,  8, 1 },   /* 4: polar reference field              */
        { 2789,  -334, 13, 1 },   /* 5: KBO search field D-9               */
        {    0,     0,  0, 0 },   /* 6: (unassigned)                       */
        {    0,     0,  0, 0 },   /* 7: (unassigned)                       */
    };
    xmemcpy(g_config.catalog, defaults, sizeof defaults);

    /* Auxiliary flight functions. Defaults are deliberately benign so the
     * probe is healthy as built; scenarios shift them to create faults. */
    g_config.heater_setpoint_dc = 100;   /* 10.0 °C — below nominal, so off */
    g_config.heater_hyst_dc     = 20;    /* ±2.0 °C                          */
    g_config.heater_enable      = 1;
    g_config.heater_draw_mw     = 300;

    g_config.power_budget_mw    = 5000;  /* generous — no shedding as built  */
    g_config.shed_enable        = 1;

    g_config.acs_enable         = 1;
    g_config.acs_momentum_max   = 1000;
    g_config.acs_torque         = 4;     /* desat roughly every ~4 min       */
    g_config.acs_desat_cost_mg  = 50;
    g_config.prop_init_mg       = 8000;

    g_config.rec_enable         = 1;
    g_config.rec_buffer_max     = 4096;
    g_config.rec_gen_per_sensor = 8;     /* 6 sensors -> 48/s generated      */
    g_config.rec_downlink_rate  = 64;    /* drains faster than it fills      */

    g_config.eng_key            = 0x5A3C96E1u; /* engineering-command key    */
}
