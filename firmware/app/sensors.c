/* sensors.c — sensor register block, SIM-tier physics, polling, safing.
 *
 * SIM tier (spec §6): a physics task updates the register block each cycle
 * behind the HAL seam.  Deterministic: fixed PRNG seed, so runs replay
 * identically (spec open question #5 resolved: reproducible).
 *
 * Telemetry participation needs BOTH sensor power (CTRL.POWER) and the
 * polling flag (poll_enable[]) — the two-surface design of spec C5.
 */
#include "app.h"

uint8_t  poll_enable[N_SENSORS];
int32_t  tlm_stage[N_SENSORS];
uint8_t  tlm_valid[N_SENSORS];
uint32_t g_load_mw;
uint32_t g_bus_mv;

static uint32_t prng;
static int32_t  imu_walk;
static int32_t  thm_val;
static uint32_t rad_counts;
static uint32_t fault_secs;

/* quarter-wave sine, 0..90 deg in 16 steps, scaled x1000 */
static const int16_t qsin[17] = {
    0, 98, 195, 290, 383, 471, 556, 634, 707, 773, 831, 882, 924, 957, 981, 995, 1000
};
static int32_t isin1000(uint32_t phase64)   /* phase 0..63 -> -1000..1000 */
{
    uint32_t p = phase64 & 63u;
    uint32_t q = p & 15u;
    switch (p >> 4) {
    case 0:  return  qsin[q];
    case 1:  return  qsin[16u - q];
    case 2:  return -qsin[q];
    default: return -qsin[16u - q];
    }
}

static uint32_t nominal_power(int slot)
{
    switch (slot) {
    case SLOT_MAG: return 180u;
    case SLOT_IMU: return 90u;
    case SLOT_THM: return 40u;
    case SLOT_PWR: return 25u;
    case SLOT_RAD: return 70u;
    case SLOT_STR: return 310u;
    case SLOT_CAM: return 60u;    /* idle draw; camera.c may raise it */
    default:       return 0u;
    }
}

void sensors_init(void)
{
    prng = 0x534F4A4Fu;                       /* 'SOJO' — fixed seed        */
    thm_val = 180;
    for (int i = 0; i < N_SENSORS; i++) {
        SENSORS[i].ctrl = (i == SLOT_SPARE) ? 0u : SCTRL_POWER;
        SENSORS[i].status = 0;
        SENSORS[i].data = 0;
        SENSORS[i].power_mw = 0;
        poll_enable[i] = (i <= SLOT_STR) ? 1u : 0u;
    }
}

/* 10 Hz — the SIM-tier physics tick. */
void task_physics(void)
{
    uint32_t up = uptime_s();
    uint32_t load = 0;

    for (int i = 0; i < N_SENSORS; i++) {
        sensor_reg_t *s = &SENSORS[i];
        if (!(s->ctrl & SCTRL_POWER)) {
            s->status &= ~(uint32_t)SSTAT_READY;
            s->power_mw = 0;
            continue;
        }
        if (i != SLOT_CAM)                    /* camera.c owns CAM power */
            s->power_mw = nominal_power(i);
        s->status |= SSTAT_READY;
    }

    /* MAG: slow field sinusoid; scripted degradation after T+cfg seconds. */
    if (SENSORS[SLOT_MAG].ctrl & SCTRL_POWER) {
        int32_t base = (isin1000(up >> 2) * 300) / 1000;
        int32_t noise;
        if (up >= g_config.mag_fault_after_s) {
            SENSORS[SLOT_MAG].status |= SSTAT_FAULT;
            SENSORS[SLOT_MAG].power_mw = 420u;
            noise = (int32_t)(xorshift32(&prng) & 0x3FFu) - 512;
        } else {
            noise = (int32_t)(xorshift32(&prng) & 0xFu) - 8;
        }
        SENSORS[SLOT_MAG].data = base + noise;
    }

    /* IMU: bounded random walk (deg/s x100). */
    if (SENSORS[SLOT_IMU].ctrl & SCTRL_POWER) {
        imu_walk += (int32_t)(xorshift32(&prng) % 9u) - 4;
        if (imu_walk >  200) imu_walk =  200;
        if (imu_walk < -200) imu_walk = -200;
        SENSORS[SLOT_IMU].data = imu_walk;
    }

    /* RAD: Poisson-ish cosmic ray counter with rare bursts. */
    if (SENSORS[SLOT_RAD].ctrl & SCTRL_POWER) {
        if ((xorshift32(&prng) % 100u) < 8u) rad_counts++;
        if ((xorshift32(&prng) & 0xFFFu) < 2u) rad_counts += xorshift32(&prng) % 20u;
        SENSORS[SLOT_RAD].data = (int32_t)rad_counts;
    }

    /* STR: quaternion w-component x10000, slight jitter; lock == READY. */
    if (SENSORS[SLOT_STR].ctrl & SCTRL_POWER) {
        SENSORS[SLOT_STR].data =
            9063 + (isin1000(up) * 12) / 1000
                 + (int32_t)(xorshift32(&prng) & 0x7u) - 4;
    }

    /* Sum the true bus load (every powered device, camera included). */
    for (int i = 0; i < N_SENSORS; i++) load += SENSORS[i].power_mw;
    g_load_mw = load;

    /* THM: tracks load (deci-degC): idle 18.0 C + 1 C per 200 mW. */
    if (SENSORS[SLOT_THM].ctrl & SCTRL_POWER) {
        int32_t tgt = 180 + (int32_t)(load / 20u);
        thm_val += (tgt - thm_val) / 8;
        SENSORS[SLOT_THM].data = thm_val + (int32_t)(xorshift32(&prng) & 3u) - 2;
    }

    /* PWR: bus millivolts with small ripple. */
    if (SENSORS[SLOT_PWR].ctrl & SCTRL_POWER) {
        g_bus_mv = 3300u + (xorshift32(&prng) % 7u) - 3u;
        SENSORS[SLOT_PWR].data = (int32_t)g_bus_mv;
    }
}

/* 2 Hz — stage readings for the telemetry encoder (the "polling table"). */
void task_sensor_poll(void)
{
    for (int i = 0; i <= SLOT_STR; i++) {
        sensor_reg_t *s = &SENSORS[i];
        if (poll_enable[i] && (s->ctrl & SCTRL_POWER) && (s->status & SSTAT_READY)) {
            tlm_stage[i] = s->data;
            tlm_valid[i] = 1u;
        } else {
            tlm_valid[i] = 0u;
        }
    }
}

/* 1 Hz — persistent-fault safing (spec §10). */
void task_fault_monitor(void)
{
    int faulting = 0;
    for (int i = 0; i < N_SENSORS; i++)
        if ((SENSORS[i].ctrl & SCTRL_POWER) && (SENSORS[i].status & SSTAT_FAULT))
            faulting = 1;
    fault_secs = faulting ? fault_secs + 1u : 0u;

    if (g_config.safe_fault_limit_s && fault_secs >= g_config.safe_fault_limit_s)
        enter_safe();
}

void enter_safe(void)
{
    g_mode = MODE_SAFE;
    for (int i = 0; i < N_SENSORS; i++)
        if (i != SLOT_PWR && i != SLOT_THM)
            SENSORS[i].ctrl &= ~(uint32_t)SCTRL_POWER;
}
