/* app.h — Sojourn application internals. */
#ifndef APP_H
#define APP_H

#include "probe.h"

/* ---- task table (spec §7): the scheduler walks this in .bss ---- */
typedef struct {
    void (*handler)(void);
    uint32_t period;                /* ticks; 0 = every tick               */
    uint32_t countdown;
    uint32_t flags;                 /* bit0 ENABLED                        */
} task_t;
#define TASK_ENABLED  (1u << 0)
#define N_TASKS       14            /* 12 live + 2 empty hook slots         */
extern task_t task_table[N_TASKS];

/* ---- config block (spec §7): runtime-initialized tunables ---- */
typedef struct {
    uint16_t ra; int16_t dec; uint8_t mag; uint8_t flags;
    uint8_t  scene;                 /* which stored scene this target shows */
    uint8_t  rsv;
} target_t;                         /* 8 bytes                              */
typedef struct {
    uint32_t tlm_period;            /* ticks between telemetry frames      */
    uint32_t mag_fault_after_s;     /* scripted magnetometer degradation   */
    uint32_t safe_fault_limit_s;    /* continuous-fault seconds before SAFE */
    uint32_t cam_auto_period_s;     /* auto-capture interval               */
    uint32_t cam_exposure_ms;       /* capture defaults                    */
    uint16_t cam_gain;
    uint16_t cam_binning;
    target_t catalog[8];            /* the target catalog (spec §6.1)      */

    /* ---- auxiliary flight functions (spec §6.4): patch surfaces ---- */
    int16_t  heater_setpoint_dc;    /* thermostat setpoint, deci-°C        */
    int16_t  heater_hyst_dc;        /* on/off hysteresis, deci-°C          */
    uint8_t  heater_enable;         /* 0 disables the heater controller    */
    uint8_t  _rsv0;
    uint16_t heater_draw_mw;        /* bus load added while heating        */

    uint16_t power_budget_mw;       /* load-shed trips above this          */
    uint8_t  shed_enable;           /* 0 disables autonomous load shedding */
    uint8_t  _rsv1;

    uint8_t  acs_enable;            /* 0 disables attitude control         */
    uint8_t  _rsv2;
    uint16_t acs_momentum_max;      /* desat fires at this |momentum|       */
    uint16_t acs_torque;            /* momentum accrued per ACS cycle       */
    uint16_t acs_desat_cost_mg;     /* propellant spent per desaturation    */
    uint16_t prop_init_mg;          /* propellant loaded at boot            */
    uint16_t _rsv3;

    uint8_t  rec_enable;            /* 0 disables the data recorder         */
    uint8_t  _rsv4;
    uint16_t rec_buffer_max;        /* recorder storage capacity (units)   */
    uint16_t rec_gen_per_sensor;    /* data generated per active sensor/s   */
    uint16_t rec_downlink_rate;     /* recorder drain per second           */

    uint8_t  cam_filter;            /* imaging pipeline stages (FILT_*)     */
    uint8_t  cam_kdiv;              /* convolution divisor                  */
    uint16_t _rsv5;

    /* ---- downlink comms (spec §6.7) ---- */
    uint8_t  comms_enable;          /* 0 freezes antenna management         */
    uint8_t  _rsv6;
    uint16_t hga_max_payload;       /* payload bytes the high gain carries  */
    uint16_t lga_max_payload;       /* ... and the low gain (the squeeze)   */
    uint16_t _rsv7;
    uint32_t hga_fail_after_s;      /* scripted HGA failure; 0 = never      */

    uint32_t eng_key;               /* engineering-command auth key         */
} config_t;
extern config_t g_config;

/* ---- shared app state ---- */
extern volatile uint32_t g_mode;            /* MODE_BOOT/NOMINAL/SAFE      */
extern uint8_t  poll_enable[N_SENSORS];     /* per-sensor polling flags    */
extern int32_t  tlm_stage[N_SENSORS];       /* staged readings             */
extern uint8_t  tlm_valid[N_SENSORS];
extern uint32_t g_load_mw;                  /* summed bus load             */
extern uint32_t g_bus_mv;
extern uint16_t g_last_cmd_crc;             /* AUX channel payload         */

/* ---- auxiliary flight-function state (.bss; all patchable) ---- */
extern uint16_t g_heater_mw;                /* heater draw, folded into load */
extern uint8_t  g_heater_on;
extern uint8_t  g_shed_count;               /* autonomous shed events        */
extern uint16_t g_propellant_mg;            /* remaining propellant          */
extern int16_t  g_momentum;                 /* accumulated angular momentum  */
extern uint8_t  g_desat_count;
extern uint16_t g_rec_fill;                 /* recorder buffer occupancy     */
extern uint8_t  g_auth;                     /* engineering command unlocked  */

/* ---- imaging pipeline (imaging.c): all patchable ----
 * Scene geometry and the ROM store live in probe.h (spec §6.4a). */

/* cam_filter stages, OR-ed together */
#define FILT_NONE     0x00u
#define FILT_LUT      0x01u         /* map every pixel through cam_lut[]    */
#define FILT_CONV     0x02u         /* 3x3 convolution with cam_kernel[]    */

extern uint8_t cam_lut[256];        /* transfer curve — invert lives here   */
extern int8_t  cam_kernel[9];       /* 3x3 convolution coefficients         */

extern uint8_t g_cam_egg_pct;   /* easter-egg rate, percent */

void imaging_init(void);
void image_process(const uint8_t *src, uint8_t *dst);

static inline uint32_t ticks_now(void) { return ROM_SVC->get_ticks(); }
static inline uint32_t uptime_s(void)  { return ticks_now() / TICK_HZ; }

/* uart.c */
void uart_init(void);
void uart_putc(char c);
void uart_puts(const char *s);
void uart_put_u32(uint32_t v);              /* decimal                     */
void uart_put_hex8(uint8_t b);
void uart_put_hex16(uint16_t v);
void uart_put_hex32(uint32_t v);
int  uart_rx_ready(void);
char uart_getc(void);

/* modules */
void config_init(void);
void sensors_init(void);
void task_physics(void);
void task_sensor_poll(void);
void task_fault_monitor(void);
void enter_safe(void);
void camera_init(void);
const uint8_t *scene_for_target(uint32_t target);
void task_camera(void);
void telemetry_init(void);
void task_telemetry(void);
extern uint8_t g_dump_enable;   /* bulk downlink gate (ships 0) */
extern uint8_t g_call_enable;   /* one-shot execution gate (ships 0) */

/* ---- comms.c: antenna and downlink bandwidth ---- */
extern uint8_t g_antenna;                    /* ANT_HGA / ANT_LGA         */
extern uint8_t g_hga_ok;                     /* high-gain health verdict  */
extern uint8_t g_tlm_dropped;                /* channels squeezed out     */
extern uint8_t tlm_priority[N_TLM_PRIORITY]; /* emission order (patchable)*/
void     comms_init(void);
uint32_t comms_budget(void);
void     task_comms(void);
void cmd_poll_rx(void);
void task_cmd(void);
void task_wdg_pet(void);

/* flight.c — auxiliary flight functions */
void flight_init(void);
void task_heater(void);
void task_power_mgr(void);
void task_acs(void);
void task_recorder(void);

#endif
