/* util.c — freestanding helpers shared by bootloader and application. */
#include "probe.h"

void *xmemcpy(void *dst, const void *src, uint32_t n)
{
    uint8_t *d = dst; const uint8_t *s = src;
    while (n--) *d++ = *s++;
    return dst;
}

void *xmemset(void *dst, int c, uint32_t n)
{
    uint8_t *d = dst;
    while (n--) *d++ = (uint8_t)c;
    return dst;
}

/* CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF — uplink command checksum. */
uint16_t crc16_ccitt(const uint8_t *p, uint32_t n)
{
    uint16_t crc = 0xFFFFu;
    while (n--) {
        crc ^= (uint16_t)(*p++) << 8;
        for (int i = 0; i < 8; i++)
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u)
                                  : (uint16_t)(crc << 1);
    }
    return crc;
}

/* CRC-32 (IEEE, bitwise) — golden image integrity. Pass crc=0xFFFFFFFF,
 * xor the result with 0xFFFFFFFF when done. */
uint32_t crc32_step(uint32_t crc, const uint8_t *p, uint32_t n)
{
    while (n--) {
        crc ^= *p++;
        for (int i = 0; i < 8; i++)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return crc;
}

/* xorshift32 PRNG — deterministic sensor physics (spec §6, fixed seed). */
uint32_t xorshift32(uint32_t *state)
{
    uint32_t x = *state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    *state = x ? x : 0x53554A4Fu;
    return *state;
}

/* GCC may emit calls to these even with -nostdlib. */
void *memcpy(void *d, const void *s, unsigned long n) { return xmemcpy(d, s, (uint32_t)n); }
void *memset(void *d, int c, unsigned long n) { return xmemset(d, c, (uint32_t)n); }
