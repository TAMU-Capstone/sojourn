/* board.h — MPS2 AN386 board glue (QEMU -M mps2-an386).
 * The only board-specific knowledge in the application: the CMSDK APB UART.
 * Swap this file for the LM3S (PL011) fallback build. */
#ifndef BOARD_H
#define BOARD_H

#include <stdint.h>

#define UART0_BASE  0x40004000u
#define UART_DATA   (*(volatile uint32_t *)(UART0_BASE + 0x00u))
#define UART_STATE  (*(volatile uint32_t *)(UART0_BASE + 0x04u))
#define UART_CTRL   (*(volatile uint32_t *)(UART0_BASE + 0x08u))
#define UART_BAUDD  (*(volatile uint32_t *)(UART0_BASE + 0x10u))

#define UART_STATE_TXFULL  (1u << 0)
#define UART_STATE_RXFULL  (1u << 1)
#define UART_CTRL_TXEN     (1u << 0)
#define UART_CTRL_RXEN     (1u << 1)

#define SYSCLK_HZ   25000000u
#define BAUD        115200u

#endif
