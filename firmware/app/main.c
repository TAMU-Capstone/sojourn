/* main.c — Sojourn application: cooperative scheduler over the task table.
 *
 * The task table (spec §7) lives in .bss at a stable, discoverable — but
 * undocumented — address.  Two entries are deliberately empty: hooking one
 * with a pointer to injected code is the intended (never required) path
 * for the code-injection objective.  The main loop validates nothing; a
 * bad pointer hard-faults into the ROM watchdog path and the golden image
 * comes back.  That is the game working as designed.
 */
#include "app.h"

task_t task_table[N_TASKS];
volatile uint32_t g_mode;

PATCH_ENTRY void task_wdg_pet(void) { ROM_SVC->wdg_reload(); }

/* Golden image header — patched with size+CRC by tools/fixup_app.py. */
void app_main(void);
__attribute__((section(".apphdr"), used))
const apphdr_t apphdr = { APPHDR_MAGIC, (uint32_t)app_main, 0, 0 };

static void sched_init(void)
{
    static const struct { void (*fn)(void); uint32_t period; } init[] = {
        { task_cmd,           1                    },
        { task_physics,       TICK_HZ / 10u        },
        { task_sensor_poll,   TICK_HZ / 2u         },
        { task_wdg_pet,       TICK_HZ              },
        { task_fault_monitor, TICK_HZ              },
        { task_camera,        TICK_HZ              },
        { task_telemetry,     0 /* from config */  },
        { task_heater,        TICK_HZ              },
        { task_power_mgr,     TICK_HZ / 2u         },
        { task_acs,           TICK_HZ              },
        { task_recorder,      TICK_HZ              },
        { task_comms,         TICK_HZ              },
    };
    for (uint32_t i = 0; i < sizeof init / sizeof init[0]; i++) {
        task_table[i].handler   = init[i].fn;
        task_table[i].period    = init[i].period ? init[i].period
                                                 : g_config.tlm_period;
        task_table[i].countdown = task_table[i].period;
        task_table[i].flags     = TASK_ENABLED;
    }
    /* Slots 12 and 13 stay empty: {NULL, 0, 0, 0} — injection hook slots. */
}

static void sched_tick(void)
{
    for (uint32_t i = 0; i < N_TASKS; i++) {
        task_t *t = &task_table[i];
        if (!t->handler || !(t->flags & TASK_ENABLED)) continue;
        if (t->countdown > 1) {
            t->countdown--;
        } else {
            t->countdown = t->period ? t->period : 1u;
            t->handler();
        }
    }
}

void app_main(void)
{
    g_mode = MODE_BOOT;
    uart_init();
    config_init();
    sensors_init();
    camera_init();
    flight_init();
    comms_init();
    telemetry_init();
    sched_init();

    uart_puts("\r\nSOJOURN FSW v1.0 boot  reboots=");
    uart_put_u32(NOINIT->reboot_count);
    uart_puts(" fault=");
    uart_put_u32(NOINIT->last_fault);
    uart_puts("\r\n");

    g_mode = MODE_NOMINAL;

    uint32_t last = ticks_now();
    for (;;) {
        cmd_poll_rx();                        /* responsive RX drain        */
        uint32_t now = ticks_now();
        while (last != now) {                 /* catch up, tick by tick     */
            last++;
            sched_tick();
        }
    }
}
