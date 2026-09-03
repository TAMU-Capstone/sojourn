/* command.c — the uplink command interpreter (spec §8).
 *
 *   VERB [args] *CCCC        CCCC = CRC-16/CCITT (hex) over text before '*'
 *
 * Verbs: PING PEEK POKE STAT SAFE NOOP.  There is deliberately no CALL
 * verb (spec §8): executing injected code requires understanding the
 * scheduler.  ACK/NAK reflects receipt+execution only, never objectives.
 *
 * Error codes: E01 bad CRC · E02 unknown verb · E03 unmapped address ·
 *              E04 protected region · E05 bad length/args · E06 busy.
 */
#include "app.h"

#define LINE_MAX 96
static char    line[LINE_MAX];
static uint32_t line_len;
static uint8_t line_over;
static char    pending[LINE_MAX];
static uint8_t pending_ready;

/* ---- parsing helpers ---- */
static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

static int parse_hex32(const char *s, uint32_t len, uint32_t *out)
{
    if (len == 0 || len > 10) return -1;
    if (len > 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { s += 2; len -= 2; }
    if (len == 0 || len > 8) return -1;
    uint32_t v = 0;
    for (uint32_t i = 0; i < len; i++) {
        int h = hexval(s[i]);
        if (h < 0) return -1;
        v = (v << 4) | (uint32_t)h;
    }
    *out = v;
    return 0;
}

static int parse_dec(const char *s, uint32_t len, uint32_t *out)
{
    if (len == 0 || len > 9) return -1;
    uint32_t v = 0;
    for (uint32_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '9') return -1;
        v = v * 10u + (uint32_t)(s[i] - '0');
    }
    *out = v;
    return 0;
}

/* ---- address windows ---- */
static int readable(uint32_t lo, uint32_t n)
{
    uint32_t hi = lo + n;
    if (hi < lo) return 0;
    if (hi <= ROM_END) return 1;              /* ROM window (base is 0)    */
    if (lo >= NOINIT_BASE && hi <= SRAM_END) return 1;
    return 0;
}

static int in_sram(uint32_t lo, uint32_t n)
{
    uint32_t hi = lo + n;
    return hi >= lo && lo >= NOINIT_BASE && hi <= SRAM_END;
}

static int protected_range(uint32_t lo, uint32_t n)
{
    uint32_t hi = lo + n;
    if (lo < ROM_END) return 1;               /* ROM window                */
    for (uint32_t i = 0; i < ROM_PROT->count; i++)
        if (lo < ROM_PROT->range[i].hi && hi > ROM_PROT->range[i].lo)
            return 1;
    return 0;
}

static void nak(const char *code) { uart_puts("NAK "); uart_puts(code); uart_puts("\r\n"); }

/* ---- tokenizer ---- */
typedef struct { const char *p; uint32_t len; } tok_t;
static uint32_t tokenize(char *s, tok_t *toks, uint32_t max)
{
    uint32_t n = 0;
    while (*s && n < max) {
        while (*s == ' ') s++;
        if (!*s) break;
        toks[n].p = s;
        while (*s && *s != ' ') s++;
        toks[n].len = (uint32_t)(s - toks[n].p);
        n++;
    }
    return n;
}

static int tok_is(const tok_t *t, const char *word)
{
    uint32_t i = 0;
    for (; word[i]; i++)
        if (i >= t->len || t->p[i] != word[i]) return 0;
    return i == t->len;
}

/* ---- execution ---- */
static void cmd_execute(char *cmd)
{
    /* Split off and verify the checksum. */
    char *star = 0;
    for (char *p = cmd; *p; p++) if (*p == '*') star = p;
    if (!star) { nak("E01"); return; }
    uint16_t want;
    {
        uint32_t v;
        uint32_t clen = 0;
        while (star[1 + clen]) clen++;
        if (parse_hex32(star + 1, clen, &v) || v > 0xFFFFu) { nak("E01"); return; }
        want = (uint16_t)v;
    }
    /* CRC over everything before '*' (trailing space included if typed). */
    uint16_t got = crc16_ccitt((const uint8_t *)cmd, (uint32_t)(star - cmd));
    if (got != want) { nak("E01"); return; }
    *star = '\0';

    tok_t t[8];
    uint32_t n = tokenize(cmd, t, 8);
    if (n == 0) { nak("E02"); return; }

    if (tok_is(&t[0], "PING")) {
        uart_puts("ACK PING\r\n");
    } else if (tok_is(&t[0], "NOOP")) {
        uart_puts("ACK NOOP\r\n");
    } else if (tok_is(&t[0], "STAT")) {
        uart_puts("ACK STAT mode=");  uart_put_u32(g_mode);
        uart_puts(" up=");            uart_put_u32(uptime_s());
        uart_puts("s reboots=");      uart_put_u32(NOINIT->reboot_count);
        uart_puts(" fault=");         uart_put_u32(NOINIT->last_fault);
        uart_puts(" load=");          uart_put_u32(g_load_mw);
        uart_puts("mW\r\n");
    } else if (tok_is(&t[0], "SAFE")) {
        enter_safe();
        uart_puts("ACK SAFE\r\n");
    } else if (tok_is(&t[0], "PEEK")) {
        uint32_t addr, len;
        if (n != 3 || parse_hex32(t[1].p, t[1].len, &addr)) { nak("E05"); return; }
        if (parse_dec(t[2].p, t[2].len, &len) || len < 1 || len > 64) { nak("E05"); return; }
        if (!readable(addr, len)) { nak("E03"); return; }
        uart_puts("ACK PEEK ");
        for (uint32_t i = 0; i < len; i++)
            uart_put_hex8(*(volatile uint8_t *)(addr + i));
        uart_puts("\r\n");
    } else if (tok_is(&t[0], "POKE")) {
        uint32_t addr;
        uint8_t bytes[32];
        uint32_t nb = 0;
        if (n < 3 || parse_hex32(t[1].p, t[1].len, &addr)) { nak("E05"); return; }
        for (uint32_t i = 2; i < n; i++) {
            if (t[i].len == 0 || (t[i].len & 1u)) { nak("E05"); return; }
            for (uint32_t j = 0; j + 1 < t[i].len + 1; j += 2) {
                int hh = hexval(t[i].p[j]), hl = hexval(t[i].p[j + 1]);
                if (hh < 0 || hl < 0 || nb >= 32) { nak("E05"); return; }
                bytes[nb++] = (uint8_t)((hh << 4) | hl);
            }
        }
        if (nb == 0) { nak("E05"); return; }
        if (!in_sram(addr, nb)) {
            /* ROM is a known address that is protected; all else unmapped. */
            nak(addr < ROM_END ? "E04" : "E03");
            return;
        }
        if (protected_range(addr, nb)) { nak("E04"); return; }
        for (uint32_t i = 0; i < nb; i++)
            *(volatile uint8_t *)(addr + i) = bytes[i];
        uart_puts("ACK POKE ");
        uart_put_u32(nb);
        uart_puts("\r\n");
    } else if (tok_is(&t[0], "AUTH")) {
        /* Undocumented engineering-command unlock. Not in the recovered
         * manual — discovered by reverse engineering. Match the key held
         * in the config block to raise the privilege flag. */
        uint32_t k;
        if (n != 2 || parse_hex32(t[1].p, t[1].len, &k)) { nak("E05"); return; }
        if (k == g_config.eng_key) {
            g_auth = 1;
            uart_puts("ACK AUTH\r\n");
        } else {
            g_auth = 0;
            nak("E07");                          /* unauthorized              */
            return;
        }
    } else if (tok_is(&t[0], "TRIM")) {
        /* Privileged: manual reaction-wheel desaturation. Requires AUTH. */
        if (!g_auth) { nak("E07"); return; }
        if (g_propellant_mg >= g_config.acs_desat_cost_mg)
            g_propellant_mg -= g_config.acs_desat_cost_mg;
        g_momentum = 0;
        uart_puts("ACK TRIM\r\n");
    } else {
        nak("E02");
        return;
    }
    g_last_cmd_crc = want;                     /* AUX channel: last good cmd */
}

/* Called every main-loop iteration: drain RX into a line buffer. */
void cmd_poll_rx(void)
{
    while (uart_rx_ready()) {
        char c = uart_getc();
        if (c == '\r' || c == '\n') {
            if (line_len > 0 && !pending_ready) {
                if (line_over) {
                    nak("E05");
                } else {
                    line[line_len] = '\0';
                    xmemcpy(pending, line, line_len + 1);
                    pending_ready = 1;
                }
            }
            line_len = 0;
            line_over = 0;
        } else if (line_len < LINE_MAX - 1) {
            line[line_len++] = c;
        } else {
            line_over = 1;
        }
    }
}

/* Scheduler task: execute at most one pending command per tick. */
void task_cmd(void)
{
    if (pending_ready) {
        cmd_execute(pending);
        pending_ready = 0;
    }
}
