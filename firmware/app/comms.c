/*
 * comms.c — the two downlink antennas and the bandwidth they buy (spec §6.7).
 *
 * Real precedent: Galileo's high-gain antenna failed to unfurl in 1991 —
 * several ribs stuck in their sockets — and the mission was saved not by
 * freeing the dish but by reprogramming the spacecraft in flight to run
 * science through the low-gain antenna: new compression, and hard
 * decisions about which data was worth the bandwidth. This subsystem is
 * that scenario in miniature, and the dead end is modelled too.
 *
 * THE HARDWARE
 *
 *   HGA  a deployable high-gain dish, 34.5 dBi. Narrow beam, so it closes
 *        the link only while it is BOTH fully deployed AND held on
 *        boresight. Holding boresight needs an attitude reference: with
 *        the star tracker unpowered the pointing error drifts until the
 *        beam walks off Earth, exactly as the camera loses its reference.
 *        Steering the dish costs bus power on top of the transmitter.
 *
 *   LGA  a fixed low-gain omni, 8.0 dBi. Nothing to deploy, nothing to
 *        point, never unavailable — and a fraction of the data rate.
 *
 * THE LINK
 *
 * Each antenna carries a rate in bits per second. What the telemetry
 * encoder actually needs is a per-frame byte budget, and the cadence is
 * what converts one into the other:
 *
 *       budget = rate_bps * tlm_period / (TICK_HZ * 8)
 *
 * At the shipped 5 s cadence the high gain affords 100 bytes — the whole
 * frame, with room to spare — and the omni affords 40, which cannot hold
 * the header, housekeeping and six science channels together. Something
 * has to go, and tlm_priority[] decides what (telemetry.c).
 *
 * The rate ratio here (2.5:1) is far gentler than the gain difference
 * would imply; a true 26 dB drop is nearer 400:1, which is unplayable.
 * These figures are chosen so the squeeze is survivable and legible.
 *
 * WHAT THE GROUND CAN DO ABOUT IT
 *
 *   XCTRL_MANUAL          take the selection away from the autonomy — an
 *                         operational lever, no patching required
 *   XCTRL_DEPLOY          command another deployment attempt (it stalls
 *                         again at the jam; that is the point)
 *   tlm_priority[]        which data survives the squeeze — the Galileo
 *                         decision, as a byte array in RAM
 *   lga_rate_bps          the link budget figure itself
 *   tlm_period            a slower cadence buys a bigger budget
 *   hga_fail_after_s      the scripted failure the scenario schedules
 *   g_hga_ok              the fault verdict, overridable
 *   task_comms            the fallback logic itself (entry pad + patch
 *                         point, §6.5)
 */
#include "app.h"

uint8_t  g_antenna;                 /* ANT_HGA / ANT_LGA                  */
uint8_t  g_hga_ok;                  /* health verdict for the high gain   */
uint8_t  g_tlm_dropped;             /* channels dropped in the last frame */
uint16_t g_comms_mw;                /* transmitter + steering draw        */
uint8_t  tlm_priority[N_TLM_PRIORITY];

void comms_init(void)
{
    g_antenna     = ANT_HGA;
    g_hga_ok      = 1;
    g_tlm_dropped = 0;
    g_comms_mw    = 0;

    xmemset((void *)&COMMS->xctrl, 0, sizeof(comms_reg_t));
    COMMS->xctrl          = XCTRL_TX_EN;
    COMMS->antenna        = ANT_HGA;
    /* The probe has been in cruise for years: the dish deployed long ago. */
    COMMS->hga_deploy_pct = 100u;
    COMMS->xstat          = XSTAT_HGA_DEPL | XSTAT_LINK;
    COMMS->hga_gain_cdb   = 3450u;              /* 34.50 dBi              */
    COMMS->lga_gain_cdb   = 800u;               /*  8.00 dBi              */

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

/* Payload bytes one telemetry frame may carry on the current antenna.
 * Derived from the link rate and the frame cadence, so a slower cadence
 * buys back bandwidth — a legitimate answer to the squeeze. */
uint32_t comms_budget(void)
{
    uint32_t bps    = (g_antenna == ANT_LGA) ? g_config.lga_rate_bps
                                             : g_config.hga_rate_bps;
    uint32_t period = g_config.tlm_period ? g_config.tlm_period : TICK_HZ;
    return (bps * period) / (TICK_HZ * 8u);
}

/* Dish travel. Runs while the deployment is short of full and the ground
 * has commanded the drive, and stalls for good at a jam. */
static void hga_deploy_step(void)
{
    uint32_t pct = COMMS->hga_deploy_pct;

    if (pct >= 100u) {
        COMMS->xstat |= XSTAT_HGA_DEPL;
        return;
    }
    COMMS->xstat &= ~(uint32_t)XSTAT_HGA_DEPL;

    if (!(COMMS->xctrl & XCTRL_DEPLOY))
        return;                                 /* no drive commanded     */

    /* A jammed rib does not free itself. Retrying the deployment is the
     * obvious move and the wrong one — Galileo's lesson is that the fix
     * was on the ground, in what the spacecraft chose to send. */
    if ((COMMS->xstat & XSTAT_HGA_JAM) &&
        pct >= (uint32_t)g_config.hga_jam_at_pct)
        return;

    pct += g_config.hga_deploy_rate_pct;
    if (pct > 100u) pct = 100u;
    COMMS->hga_deploy_pct = pct;

    if (pct >= 100u) {
        COMMS->xstat |= XSTAT_HGA_DEPL;
        COMMS->xctrl &= ~(uint32_t)XCTRL_DEPLOY;    /* self-clearing      */
    }
}

/* Boresight error. The dish is steered against the star tracker's
 * attitude solution; with no solution the error walks off, and past the
 * tolerance the beam no longer illuminates Earth. */
static void hga_pointing_step(void)
{
    sensor_reg_t *str = &SENSORS[SLOT_STR];
    uint32_t err = COMMS->point_err_mdeg;

    if ((str->ctrl & SCTRL_POWER) && (str->status & SSTAT_READY)) {
        err = err > g_config.hga_drift_mdeg_s          /* re-acquiring    */
            ? err - g_config.hga_drift_mdeg_s : 0u;
    } else {
        err += g_config.hga_drift_mdeg_s;              /* open loop       */
        if (err > 65000u) err = 65000u;
    }
    COMMS->point_err_mdeg = err;

    if (err > g_config.hga_point_tol_mdeg)
        COMMS->xstat |=  (uint32_t)XSTAT_POINTERR;
    else
        COMMS->xstat &= ~(uint32_t)XSTAT_POINTERR;
}

/* 1 Hz. Runs both antennas and decides which one carries the link. A
 * ground team that disagrees with any of it can patch — or, for the
 * selection alone, simply take manual control. */
PATCH_ENTRY void task_comms(void)
{
    if (!g_config.comms_enable)
        return;

    /* The scripted failure: a rib backs out, the dish falls out of full
     * deployment and stalls at the jam. */
    if (g_config.hga_fail_after_s &&
        uptime_s() >= g_config.hga_fail_after_s &&
        !(COMMS->xstat & XSTAT_HGA_JAM)) {
        COMMS->xstat |= XSTAT_HGA_JAM;
        COMMS->xstat &= ~(uint32_t)XSTAT_HGA_DEPL;
        COMMS->hga_deploy_pct = g_config.hga_jam_at_pct;
        g_hga_ok = 0;
    }

    hga_deploy_step();
    hga_pointing_step();

    /* The high gain is usable only if all three hold. */
    uint32_t hga_usable = g_hga_ok
                       && COMMS->hga_deploy_pct >= HGA_DEPLOY_MIN
                       && !(COMMS->xstat & XSTAT_POINTERR);

    PATCH_POINT();          /* room to detour the selection */

    if (COMMS->xctrl & XCTRL_MANUAL)
        g_antenna = (COMMS->xctrl & XCTRL_SEL_LGA) ? ANT_LGA : ANT_HGA;
    else
        g_antenna = hga_usable ? ANT_HGA : ANT_LGA;

    /* Publish the resulting link state for the ground. */
    COMMS->antenna  = g_antenna;
    COMMS->rate_bps = (g_antenna == ANT_LGA) ? g_config.lga_rate_bps
                                             : g_config.hga_rate_bps;
    COMMS->budget   = comms_budget();
    COMMS->dropped  = g_tlm_dropped;

    if (g_antenna == ANT_LGA) COMMS->xstat |=  (uint32_t)XSTAT_ON_LGA;
    else                      COMMS->xstat &= ~(uint32_t)XSTAT_ON_LGA;

    /* Power: the transmitter draws while keyed, and steering the dish
     * costs more on top. Folded into the bus load (sensors.c), so the
     * load-shed manager and the thermal model both see it. */
    if (COMMS->xctrl & XCTRL_TX_EN) {
        g_comms_mw = g_config.comms_tx_mw;
        if (g_antenna == ANT_HGA)
            g_comms_mw = (uint16_t)(g_comms_mw + g_config.hga_point_mw);
    } else {
        g_comms_mw = 0;
    }
    COMMS->tx_power_mw = g_comms_mw;

    /* A link exists only while the transmitter is on, the budget can carry
     * at least a bare frame header, and the selected antenna can actually
     * reach Earth. Manual selection overrides the software's judgement but
     * not the physics: forcing the dish while it is stowed or off
     * boresight simply drops the downlink. That is recoverable — the
     * uplink path is separate (§2), and a reset re-runs comms_init — but
     * it is a real way to go quiet. */
    if ((COMMS->xctrl & XCTRL_TX_EN) &&
        COMMS->budget >= TLM_HEADER_BYTES &&
        (g_antenna == ANT_LGA || hga_usable))
        COMMS->xstat |=  (uint32_t)XSTAT_LINK;
    else
        COMMS->xstat &= ~(uint32_t)XSTAT_LINK;
}
