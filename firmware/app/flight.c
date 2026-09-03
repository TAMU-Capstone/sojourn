/*
 * flight.c — auxiliary flight functions (spec §6.4).
 *
 * Plausible spacecraft housekeeping tasks, each written to be a clean
 * reverse-engineering target for future scenarios. Every one is:
 *   - driven by values in the config block (data patches),
 *   - gated by a simple enable/threshold branch (code patches),
 *   - registered in the task table (disable-by-task-table), and
 *   - observable in the housekeeping telemetry channel (§9, ID 0x60),
 * so its behavior can be changed and the change verified from the ground.
 *
 * Defaults (config.c) keep the probe healthy as built; a scenario shifts
 * a threshold or clears an enable to manufacture the fault it is about.
 */
#include "app.h"

uint16_t g_heater_mw;
uint8_t  g_heater_on;
uint8_t  g_shed_count;
uint16_t g_propellant_mg;
int16_t  g_momentum;
uint8_t  g_desat_count;
uint16_t g_rec_fill;
uint8_t  g_auth;

void flight_init(void)
{
    g_heater_mw     = 0;
    g_heater_on     = 0;
    g_shed_count    = 0;
    g_propellant_mg = g_config.prop_init_mg;
    g_momentum      = 0;
    g_desat_count   = 0;
    g_rec_fill      = 0;
    g_auth          = 0;
}

/* ---- Thermal control: a hysteretic thermostat on the THM sensor. ----
 * Draws heater power (folded into the bus load by task_physics) when the
 * probe is cold. Scenario hooks: setpoint, hysteresis, enable, draw. */
void task_heater(void)
{
    if (!g_config.heater_enable) {
        g_heater_on = 0;
        g_heater_mw = 0;
        return;
    }
    int32_t t  = SENSORS[SLOT_THM].data;         /* deci-°C                */
    int32_t sp = g_config.heater_setpoint_dc;
    int32_t h  = g_config.heater_hyst_dc;
    if (t < sp - h)      g_heater_on = 1;
    else if (t > sp + h) g_heater_on = 0;
    g_heater_mw = g_heater_on ? g_config.heater_draw_mw : 0;
}

/* ---- Power management: autonomous load shedding. ----
 * When total bus load exceeds the budget, power down the lowest-priority
 * powered subsystem. THM and PWR are never shed. Scenario hooks: budget,
 * enable, or the shed-priority order below (a rodata table to patch). */
static const uint8_t shed_order[] = {
    SLOT_CAM, SLOT_RAD, SLOT_STR, SLOT_IMU, SLOT_MAG,
};

void task_power_mgr(void)
{
    if (!g_config.shed_enable)
        return;
    if (g_load_mw <= g_config.power_budget_mw)
        return;
    for (unsigned i = 0; i < sizeof shed_order; i++) {
        sensor_reg_t *s = &SENSORS[shed_order[i]];
        if (s->ctrl & SCTRL_POWER) {
            s->ctrl &= ~(uint32_t)SCTRL_POWER;   /* shed this load          */
            g_shed_count++;
            return;                              /* one per cycle           */
        }
    }
}

/* ---- Attitude control: reaction-wheel momentum management. ----
 * Momentum accrues from environmental torque each cycle; when it reaches
 * the limit the probe desaturates, spending propellant. If propellant is
 * exhausted the wheel saturates (momentum sticks high) — an observable
 * failure. Scenario hooks: enable, torque, momentum limit, desat cost. */
void task_acs(void)
{
    if (!g_config.acs_enable)
        return;
    g_momentum += (int16_t)g_config.acs_torque;
    if (g_momentum >= (int16_t)g_config.acs_momentum_max) {
        if (g_propellant_mg >= g_config.acs_desat_cost_mg) {
            g_propellant_mg -= g_config.acs_desat_cost_mg;
            g_momentum = 0;
            g_desat_count++;
        }
        /* else: cannot desaturate — momentum saturates (stuck wheel) */
    }
}

/* ---- Data recorder: onboard storage with scheduled downlink. ----
 * Fills with science data proportional to the number of reporting sensors
 * and drains at the downlink rate. If generation outpaces downlink the
 * buffer fills to capacity (data loss). Scenario hooks: enable, rates,
 * capacity. */
void task_recorder(void)
{
    if (!g_config.rec_enable)
        return;
    uint32_t gen = 0;
    for (int i = 0; i <= SLOT_STR; i++)
        if (poll_enable[i] && (SENSORS[i].ctrl & SCTRL_POWER))
            gen += g_config.rec_gen_per_sensor;

    uint32_t drain = g_config.rec_downlink_rate;
    if (gen > drain) {
        g_rec_fill += (uint16_t)(gen - drain);
    } else {
        uint16_t d = (uint16_t)(drain - gen);
        g_rec_fill = (g_rec_fill > d) ? (uint16_t)(g_rec_fill - d) : 0;
    }
    if (g_rec_fill > g_config.rec_buffer_max)
        g_rec_fill = g_config.rec_buffer_max;
}
