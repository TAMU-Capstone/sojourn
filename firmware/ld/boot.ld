/* boot.ld — Sojourn ROM image: bootloader + embedded golden application.
 * Layout is normative per Firmware Design Specification §4. */
ENTRY(rom_start)

MEMORY
{
    ROM (rx) : ORIGIN = 0x00000000, LENGTH = 256K
}

SECTIONS
{
    .vectors 0x00000000 : { KEEP(*(.vectors)) } > ROM

    .romsvc  0x00000200 : { KEEP(*(.romsvc))  } > ROM
    .romprot 0x00000280 : { KEEP(*(.romprot)) } > ROM

    .text    0x00000300 : { *(.text*) *(.rodata*) } > ROM

    /* Golden application image (spec: 0x4000). Restored to APP RAM on
     * every reset by the bootloader. */
    .app_image 0x00004000 : {
        _app_image_start = .;
        KEEP(*(.app_image))
        _app_image_end = .;
    } > ROM

    /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) *(.data*) *(.bss*) }
}

/* The bootloader must be stateless outside its fixed-address blocks. */
ASSERT(_app_image_start == 0x4000, "golden image must sit at ROM 0x4000")
