/* uart.c — polled CMSDK APB UART driver + tiny formatting helpers. */
#include "app.h"
#include "board.h"

void uart_init(void)
{
    UART_BAUDD = SYSCLK_HZ / BAUD;
    UART_CTRL  = UART_CTRL_TXEN | UART_CTRL_RXEN;
}

void uart_putc(char c)
{
    while (UART_STATE & UART_STATE_TXFULL) { }
    UART_DATA = (uint32_t)(uint8_t)c;
}

void uart_puts(const char *s) { while (*s) uart_putc(*s++); }

int uart_rx_ready(void) { return (UART_STATE & UART_STATE_RXFULL) != 0; }
char uart_getc(void)    { return (char)UART_DATA; }

static const char HEXD[] = "0123456789ABCDEF";

void uart_put_hex8(uint8_t b)
{
    uart_putc(HEXD[b >> 4]);
    uart_putc(HEXD[b & 0xF]);
}

void uart_put_hex16(uint16_t v) { uart_put_hex8((uint8_t)(v >> 8)); uart_put_hex8((uint8_t)v); }
void uart_put_hex32(uint32_t v) { uart_put_hex16((uint16_t)(v >> 16)); uart_put_hex16((uint16_t)v); }

void uart_put_u32(uint32_t v)
{
    char buf[11];
    int i = 10;
    buf[i] = '\0';
    do { buf[--i] = (char)('0' + v % 10u); v /= 10u; } while (v);
    uart_puts(&buf[i]);
}
