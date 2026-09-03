/*
 * probe.h — Sojourn flight firmware, shared address map and contracts.
 *
 * This header IS the memory-map contract from the Firmware Design
 * Specification §4/§6.  Addresses here are normative; the linker
 * scripts and the game daemon's memmap.json must agree with them.
 */
#ifndef PROBE_H
#define PROBE_H

#include <stdint.h>

/* ---------- Memory map (spec §4) ---------- */
#define ROM_BASE        0x00000000u
#define ROM_END         0x00040000u          /* 256 KiB, POKE-protected      */
#define GOLDEN_BASE     0x00004000u          /* golden application image     */

#define NOINIT_BASE     0x20000000u          /* survives watchdog reset      */
#define SYSBLK_BASE     0x20000100u          /* bootloader/system data       */
#define APP_BASE        0x20001000u          /* app code+rodata, from golden */
#define APP_DATA_BASE   0x20019000u          /* app .data/.bss               */
#define FREE_RAM_BASE   0x2001D000u          /* undocumented injection zone  */
#define SENS_BASE       0x2001E000u          /* sensor register block        */
#define CAM_BASE        0x2001E100u          /* camera extended registers    */
#define STACK_TOP       0x20020000u
#define FRAMEBUF_BASE   0x20020000u          /* 64x64x8bit camera frame      */
#define FRAMEBUF_SIZE   0x1000u
#define SRAM_END        0x20021000u

/* Writable window for POKE (everything else in SRAM is protected) */
#define POKE_LOW        APP_BASE
#define POKE_HIGH       SRAM_END

/* ---------- NOINIT persistent block (spec §5) ---------- */
typedef struct {
    uint32_t magic;                          /* NOINIT_MAGIC after first boot */
    uint32_t reboot_count;
    uint32_t last_fault;                     /* FAULT_* code of last reset    */
} noinit_t;
#define NOINIT          ((volatile noinit_t *)NOINIT_BASE)
#define NOINIT_MAGIC    0x534A524Eu          /* 'SJRN' */

#define FAULT_NONE      0u
#define FAULT_WDG       1u                   /* watchdog expiry               */
#define FAULT_HARD      2u                   /* hard/bus/usage fault          */
#define FAULT_BADIMG    3u                   /* golden image CRC mismatch     */

/* ---------- System block (bootloader-owned, spec §10) ---------- */
typedef struct {
    volatile uint32_t ticks;                 /* 100 Hz, incremented in ROM    */
    volatile uint32_t wdg_counter;           /* decremented in ROM SysTick    */
    uint32_t wdg_reload;                     /* ticks per pet (set by ROM)    */
} sysblk_t;
#define SYSBLK          ((volatile sysblk_t *)SYSBLK_BASE)
#define TICK_HZ         100u

/* ---------- ROM service table (fixed at 0x200) ---------- */
typedef struct {
    void (*wdg_reload)(void);                /* pet the watchdog              */
    uint32_t (*get_ticks)(void);
} rom_services_t;
#define ROM_SVC         ((const rom_services_t *)0x00000200u)

/* ---------- ROM protection table (fixed at 0x280) ---------- */
typedef struct { uint32_t lo, hi; } prot_range_t;
typedef struct {
    uint32_t count;
    prot_range_t range[4];
} prot_table_t;
#define ROM_PROT        ((const prot_table_t *)0x00000280u)

/* ---------- Golden image header (start of app image) ---------- */
typedef struct {
    uint32_t magic;                          /* APPHDR_MAGIC                  */
    uint32_t entry;                          /* thumb address of app entry    */
    uint32_t size;                           /* image size in bytes           */
    uint32_t crc32;                          /* over image after this header  */
} apphdr_t;
#define APPHDR_MAGIC    0x4E4A5253u          /* 'SRJN' */

/* ---------- Sensor register block (spec §6): 8 slots x 16 B ---------- */
typedef struct {
    volatile uint32_t ctrl;                  /* bit0 POWER                    */
    volatile uint32_t status;                /* bit0 READY, bit1 FAULT        */
    volatile int32_t  data;
    volatile uint32_t power_mw;
} sensor_reg_t;
#define SENSORS         ((sensor_reg_t *)SENS_BASE)
#define N_SENSORS       8

#define SCTRL_POWER     (1u << 0)
#define SSTAT_READY     (1u << 0)
#define SSTAT_FAULT     (1u << 1)

enum { SLOT_MAG = 0, SLOT_IMU, SLOT_THM, SLOT_PWR, SLOT_RAD, SLOT_STR,
       SLOT_CAM, SLOT_SPARE };

/* ---------- Camera extended registers (spec §6.1) ---------- */
typedef struct {
    volatile uint32_t cctrl;                 /* bit0 CAPTURE_NOW, bit1 AUTO   */
    volatile uint32_t cstat;                 /* bit0 READY,1 BUSY,2 POINT_ERR */
    volatile uint32_t target;                /* index into target catalog     */
    volatile uint32_t exposure_ms;
    volatile uint16_t gain;
    volatile uint16_t binning;
    volatile uint32_t frame_id;
    volatile uint32_t frame_addr;
    volatile uint32_t frame_len;
    volatile uint32_t hist_mean;
    volatile uint32_t hist_max;
    volatile uint32_t sat_pct;
    volatile uint32_t stars;
} cam_reg_t;
#define CAM             ((cam_reg_t *)CAM_BASE)

#define CCTRL_CAPTURE   (1u << 0)
#define CCTRL_AUTO      (1u << 1)
#define CSTAT_READY     (1u << 0)
#define CSTAT_BUSY      (1u << 1)
#define CSTAT_POINTERR  (1u << 2)

/* ---------- Telemetry (spec §9) ---------- */
#define TLM_SYNC        0xEB90u
#define CH_CAM          0x43u
#define CH_HK           0x60u
#define CH_AUX          0x5Au

#define MODE_BOOT       0u
#define MODE_NOMINAL    1u
#define MODE_SAFE       2u

/* ---------- In-flight patching support (spec §6.5) ----------
 *
 * Real missions patch running software that has no room for the new code, so
 * the fix is a DETOUR: overwrite a few bytes with a jump to spare memory, run
 * the new instructions there, then jump back into the original function. The
 * hard part is that overwriting real instructions means relocating them,
 * which breaks any PC-relative operand. This firmware removes that hazard by
 * pre-planting space that is safe to overwrite:
 *
 *   1. PATCH_ENTRY   — 8 bytes of NOPs at a function's entry, ahead of its
 *      prologue. Overwrite them with a jump; return to <func>+8 and the
 *      original body runs untouched. Hooks the whole function.
 *   2. PATCH_POINT() — 8 bytes of NOPs inside a body, before a decision.
 *      Same trick, but alters one branch rather than the whole function.
 *   3. The code cave — free RAM (below), where the new instructions live.
 *
 * The 8-byte absolute jump idiom (no offset arithmetic; the Thumb bit must be
 * set in the target word):
 *
 *      DF F8 00 F0    LDR.W PC, [PC, #0]
 *      <target|1>     .word
 */
#define PATCH_ENTRY       __attribute__((patchable_function_entry(4)))
#define PATCH_PAD_BYTES   8u
#define PATCH_POINT()     __asm__ volatile("nop\n\tnop\n\tnop\n\tnop" ::: "memory")

/* Code cave: uncommitted RAM for player/scenario-authored instructions,
 * conventionally divided into slots so several hooks can coexist. */
#define PATCH_CAVE_BASE   FREE_RAM_BASE
#define PATCH_CAVE_SIZE   0x1000u
#define PATCH_SLOT_SIZE   0x80u
#define PATCH_SLOT_COUNT  (PATCH_CAVE_SIZE / PATCH_SLOT_SIZE)   /* 32 slots */
#define PATCH_SLOT(n)     (PATCH_CAVE_BASE + (n) * PATCH_SLOT_SIZE)

/* ---------- Freestanding helpers ---------- */
void *xmemcpy(void *dst, const void *src, uint32_t n);
void *xmemset(void *dst, int c, uint32_t n);
uint16_t crc16_ccitt(const uint8_t *p, uint32_t n);
uint32_t crc32_step(uint32_t crc, const uint8_t *p, uint32_t n);
uint32_t xorshift32(uint32_t *state);

#endif /* PROBE_H */
