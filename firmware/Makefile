# Sojourn flight firmware — reference build (spec §3, §11).
# Builds and tests identically on Linux and macOS (GNU make >= 3.81).
#
#   make check      verify the toolchain is installed (per-OS install hints)
#   make            build build/probe_rom.elf (+ player + author artifacts)
#   make run        boot it under QEMU (Ctrl-A X to quit)
#   make gdbserver  boot halted, GDB stub on :3333
#   make gdb        attach a cross-gdb to a running gdbserver
#   make tlm        boot the probe and stream DECODED telemetry
#   make run-tcp    boot with UART on tcp:5599 (attach decoder/console to it)
#   make test       run the 36-check end-to-end suite
#   make clean

CROSS    ?= arm-none-eabi-
CC       := $(CROSS)gcc
OBJCOPY  := $(CROSS)objcopy
QEMU_BIN ?= qemu-system-arm
PYTHON   ?= python3
# first cross-gdb we can find: arm-none-eabi-gdb (macOS/brew, ARM toolchain)
# or gdb-multiarch (debian/ubuntu)
GDB      ?= $(shell command -v $(CROSS)gdb 2>/dev/null || command -v gdb-multiarch 2>/dev/null || echo $(CROSS)gdb)
UNAME    := $(shell uname -s)

BUILD   := build
CFLAGS  := -mcpu=cortex-m4 -mthumb -Os -g -ffreestanding -fno-builtin \
           -Wall -Wextra -Wno-array-bounds -Iinclude -Iapp
LDFLAGS := -nostdlib -Wl,--build-id=none

APP_SRC  := app/main.c app/uart.c app/config.c app/sensors.c app/camera.c \
            app/telemetry.c app/command.c common/util.c
BOOT_SRC := boot/boot.c common/util.c

QEMU     := $(QEMU_BIN) -M mps2-an386 -nographic
ROM_ELF  := $(BUILD)/probe_rom.elf

all: $(ROM_ELF) $(BUILD)/probe_rom.bin $(BUILD)/symbols.json

$(BUILD):
	mkdir -p $(BUILD)

# 1. Application, linked to execute in place at APP RAM.
$(BUILD)/probe_app.elf: $(APP_SRC) include/probe.h app/app.h app/board.h ld/app.ld | $(BUILD)
	$(CC) $(CFLAGS) $(LDFLAGS) -T ld/app.ld $(APP_SRC) -o $@ -lgcc \
	      -Wl,-Map=$(BUILD)/probe_app.map

# 2. Raw image -> golden image with size+CRC header (the player's probe.bin).
$(BUILD)/probe_app.bin: $(BUILD)/probe_app.elf
	$(OBJCOPY) -O binary $< $(BUILD)/probe_app_raw.bin
	python3 tools/fixup_app.py $(BUILD)/probe_app_raw.bin $@

# 3. Wrap the golden image as a linkable object in section .app_image.
$(BUILD)/app_image.o: $(BUILD)/probe_app.bin
	cd $(BUILD) && $(OBJCOPY) -I binary -O elf32-littlearm -B arm \
	    --rename-section .data=.app_image,alloc,load,readonly,data,contents \
	    probe_app.bin app_image.o

# 4. ROM: bootloader + embedded golden image.
$(ROM_ELF): $(BOOT_SRC) include/probe.h ld/boot.ld $(BUILD)/app_image.o
	$(CC) $(CFLAGS) $(LDFLAGS) -T ld/boot.ld $(BOOT_SRC) \
	      $(BUILD)/app_image.o -o $@ -lgcc -Wl,-Map=$(BUILD)/probe_rom.map

$(BUILD)/probe_rom.bin: $(ROM_ELF)
	$(OBJCOPY) -O binary $< $@

# 5. Scenario-author artifacts (instructor side only — never ship to players).
$(BUILD)/symbols.json: $(ROM_ELF) $(BUILD)/probe_app.elf tools/gen_symbols.py
	python3 tools/gen_symbols.py $(BUILD)/probe_app.elf $(ROM_ELF) $(BUILD)

run: all
	$(QEMU) -kernel $(ROM_ELF) -serial mon:stdio

gdbserver: all
	$(QEMU) -kernel $(ROM_ELF) -serial mon:stdio -S -gdb tcp::3333

gdb:
	$(GDB) -ex 'target remote :3333' $(ROM_ELF)

tlm: all
	$(PYTHON) tools/tlm_decode.py --spawn $(ROM_ELF)

run-tcp: all
	$(QEMU) -kernel $(ROM_ELF) -serial tcp:127.0.0.1:5599,server=on,wait=off

test: all
	$(PYTHON) tools/e2e_test.py

check:
	@ok=1; \
	for t in $(CC) $(OBJCOPY) $(QEMU_BIN) $(PYTHON); do \
	  if command -v $$t >/dev/null 2>&1; then \
	    echo "  found:   $$t"; \
	  else \
	    echo "  MISSING: $$t"; ok=0; \
	  fi; \
	done; \
	if command -v $(GDB) >/dev/null 2>&1; then \
	  echo "  found:   $(GDB) (optional, for make gdb)"; \
	else \
	  echo "  missing: cross-gdb (optional, for make gdb)"; \
	fi; \
	if [ $$ok -eq 0 ]; then \
	  echo ""; \
	  if [ "$(UNAME)" = "Darwin" ]; then \
	    echo "Install on macOS (Homebrew):"; \
	    echo "  brew install arm-none-eabi-gcc arm-none-eabi-binutils qemu"; \
	    echo "or ARM's official toolchain bundle (includes gdb):"; \
	    echo "  brew install --cask gcc-arm-embedded   # then add its bin/ to PATH"; \
	  else \
	    echo "Install on Debian/Ubuntu:"; \
	    echo "  sudo apt install gcc-arm-none-eabi binutils-arm-none-eabi \\"; \
	    echo "                   qemu-system-arm gdb-multiarch"; \
	  fi; \
	  exit 1; \
	fi; \
	echo "toolchain OK ($(UNAME))"

clean:
	rm -rf $(BUILD)

.PHONY: all run gdbserver gdb test check clean
