/* app.ld — Sojourn application, linked to execute in place at APP RAM.
 * Code+rodata live in APP (copied from the golden image at boot); all
 * mutable state is .bss in DATA (zeroed by the bootloader).  Initialized
 * .data is forbidden — the boot copy would not cover it (init at runtime). */
ENTRY(app_main)

MEMORY
{
    APP  (rwx) : ORIGIN = 0x20001000, LENGTH = 96K
    DATA (rw)  : ORIGIN = 0x20019000, LENGTH = 16K
}

SECTIONS
{
    .apphdr : { KEEP(*(.apphdr)) } > APP
    .text   : { *(.text*) *(.rodata*) } > APP

    .data   : { *(.data*) } > DATA
    .bss    : { *(.bss*) *(COMMON) } > DATA

    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) }
}

ASSERT(SIZEOF(.data) == 0,
       "app must have no initialized .data — use .bss + runtime init")
