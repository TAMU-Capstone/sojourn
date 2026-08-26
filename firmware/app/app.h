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
#define N_TASKS       9             /* 7 live + 2 empty hook slots         */
extern task_t task_table[N_TASKS];

/* ---- config block (spec §7): runtime-initialized tunables ---- */
typedef struct { uint16_t ra; int16_t dec; uint8_t mag; uint8_t flags; } target_t;
typedef struct {
    uint32_t tlm_period;            /* ticks between telemetry frames      */
    uint32_t mag_fault_after_s;     /* scripted magnetometer degradation   */
    uint32_t safe_fault_limit_s;    /* continuous-fault seconds before SAFE */
    uint32_t cam_auto_period_s;     /* auto-capture interval               */
    uint32_t cam_exposure_ms;       /* capture defaults                    */
    uint16_t cam_gain;
    uint16_t cam_binning;
    target_t catalog[8];            /* the target catalog (spec §6.1)      */
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
void task_camera(void);
void telemetry_init(void);
void task_telemetry(void);
void cmd_poll_rx(void);
void task_cmd(void);
void task_wdg_pet(void);

#endif
