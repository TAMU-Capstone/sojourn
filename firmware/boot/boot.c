/*
 * boot.c — Sojourn ROM bootloader (spec §5, §10).
 *
 * Lives in protected ROM.  Owns: the vector table (VTOR never leaves ROM,
 * so the watchdog cannot be patched away from the APP region), the
 * golden-image copy, the SysTick/watchdog service, and fault capture.
 *
 * Recovery is not a special case: EVERY reset re-copies the golden image.
 */
#include "probe.h"

#define SYST_CSR   (*(volatile uint32_t *)0xE000E010u)
#define SYST_RVR   (*(volatile uint32_t *)0xE000E014u)
#define SYST_CVR   (*(volatile uint32_t *)0xE000E018u)
#define AIRCR      (*(volatile uint32_t *)0xE000ED0Cu)
#define AIRCR_RESET 0x05FA0004u

#define SYSCLK_HZ   25000000u                /* MPS2 AN386 system clock      */
#define WDG_RELOAD  300u                     /* 3 s at 100 Hz                */

/* Golden image, embedded at ROM 0x4000 by the linker (see boot.ld). */
extern const uint8_t _app_image_start[];
extern const uint8_t _app_image_end[];

static void rom_reset(uint32_t fault)
{
    NOINIT->last_fault = fault;
    AIRCR = AIRCR_RESET;
    for (;;) { }
}

/* ---- ROM services, callable from the (patchable) application ---- */
static void svc_wdg_reload(void) { SYSBLK->wdg_counter = SYSBLK->wdg_reload; }
static uint32_t svc_get_ticks(void) { return SYSBLK->ticks; }

__attribute__((section(".romsvc"), used))
const rom_services_t rom_services = { svc_wdg_reload, svc_get_ticks };

/* ---- Protection table consulted by the app's POKE handler ---- */
__attribute__((section(".romprot"), used))
const prot_table_t rom_prot = {
    .count = 2,
    .range = {
        { ROM_BASE,    ROM_END  },           /* ROM incl. golden image      */
        { NOINIT_BASE, APP_BASE },           /* NOINIT + system block       */
    },
};

/* ---- SysTick: the ROM-owned heartbeat and watchdog (spec §10) ---- */
static void rom_systick(void)
{
    SYSBLK->ticks++;
    if (SYSBLK->wdg_counter == 0u || --SYSBLK->wdg_counter == 0u)
        rom_reset(FAULT_WDG);
}

static void rom_fault(void) { rom_reset(FAULT_HARD); }

/* ---- Reset: cold-init NOINIT, restore golden image, jump ---- */
void rom_start(void)
{
    if (NOINIT->magic != NOINIT_MAGIC) {     /* cold boot                    */
        NOINIT->magic = NOINIT_MAGIC;
        NOINIT->reboot_count = 0;
        NOINIT->last_fault = FAULT_NONE;
    } else {
        NOINIT->reboot_count++;
    }

    /* Golden image sanity (assertion, not a recovery branch — spec §5.3) */
    const apphdr_t *hdr = (const apphdr_t *)_app_image_start;
    uint32_t size = (uint32_t)(_app_image_end - _app_image_start);
    if (hdr->magic != APPHDR_MAGIC || hdr->size > size)
        rom_reset(FAULT_BADIMG);
    uint32_t crc = crc32_step(0xFFFFFFFFu,
                              _app_image_start + sizeof(apphdr_t),
                              hdr->size - sizeof(apphdr_t));
    if ((crc ^ 0xFFFFFFFFu) != hdr->crc32)
        rom_reset(FAULT_BADIMG);

    /* Restore the pristine application — unconditionally, every boot. */
    xmemcpy((void *)APP_BASE, _app_image_start, hdr->size);
    /* Clear app data/bss region and the injection zone. */
    xmemset((void *)APP_DATA_BASE, 0, SENS_BASE - APP_DATA_BASE);

    /* Start the heartbeat + watchdog. */
    SYSBLK->ticks = 0;
    SYSBLK->wdg_reload = WDG_RELOAD;
    SYSBLK->wdg_counter = WDG_RELOAD;
    SYST_RVR = (SYSCLK_HZ / TICK_HZ) - 1u;
    SYST_CVR = 0;
    SYST_CSR = 7u;                            /* enable | tickint | procclk  */

    /* Into the application (thumb bit from header entry). */
    ((void (*)(void))(hdr->entry | 1u))();
    rom_reset(FAULT_HARD);                    /* app returned: treat as fault */
}

/* ---- Vector table at ROM 0x0 (VTOR stays here forever) ---- */
typedef void (*vec_t)(void);
__attribute__((section(".vectors"), used))
const vec_t vectors[16 + 32] = {
    (vec_t)STACK_TOP,       /* 0: initial SP                                 */
    rom_start,              /* 1: Reset                                      */
    rom_fault,              /* 2: NMI                                        */
    rom_fault,              /* 3: HardFault                                  */
    rom_fault,              /* 4: MemManage                                  */
    rom_fault,              /* 5: BusFault                                   */
    rom_fault,              /* 6: UsageFault                                 */
    0, 0, 0, 0,             /* 7-10: reserved                                */
    rom_fault,              /* 11: SVCall                                    */
    rom_fault,              /* 12: DebugMon                                  */
    0,                      /* 13: reserved                                  */
    rom_fault,              /* 14: PendSV                                    */
    rom_systick,            /* 15: SysTick — the watchdog lives here         */
    /* 16..47: external IRQs, all unused                                     */
};
