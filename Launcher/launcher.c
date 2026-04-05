#include <stdbool.h>
#include <conio.h>
#include <stdint.h>
#include <string.h>
#include <6502.h>
#include "logo.h"

#define SERVER_MESSAGES     0
#define DEBUG_INTERACTIVE   0
#define RASTER_INTERRUPT    1
#define SEND_DELAY          2

/* ACIA (SwiftLink) registers at $DF80-$DF83.
   Relocated from $DE00 to avoid conflict with EasyFlash I/O1+I/O2. */
#define ACIA_DATA       (*(volatile unsigned char *)0xDF80)
#define ACIA_STATUS     (*(volatile unsigned char *)0xDF81)
#define ACIA_COMMAND    (*(volatile unsigned char *)0xDF82)
#define ACIA_CONTROL    (*(volatile unsigned char *)0xDF83)

/* ACIA control: 1200 baud, 8N1, internal clock */
#define ACIA_CTL_1200   0x18
/* ACIA command: DTR on, RX IRQ disabled, /RTS low, TX ready.
   Per 65C51 datasheet bits [3:2]: 00=/RTS low+TX ready. */
#define ACIA_CMD_POLL   0x03
/* ACIA command: DTR on, all IRQ disabled, /RTS high, TX disabled. */
#define ACIA_CMD_OFF    0x0B
/* ACIA status bits */
#define ACIA_ST_RDRF    0x08    /* Receive Data Register Full */
#define ACIA_ST_TDRE    0x10    /* Transmit Data Register Empty */

enum MODEM_TYPE { USER_PORT_MODEM=1, SWIFTLINK_MODEM=2 };

const unsigned char baud1200[] = { 0x08, 0x00, 0x00 };

/* JSON formatted login message. */
#define NAME_OFFSET 36
#define NAME_END    47
#define END_LENGTH  5

unsigned char login_json[] = {
    0x7b,0x22,0x74,0x6f,0x22,0x3a,0x22,0x62,0x72,0x69,0x64,0x67,0x65,0x22,0x2c,0x22,
    0x6f,0x70,0x22,0x3a,0x22,0x4c,0x4f,0x47,0x49,0x4e,0x22,0x2c,0x22,0x6e,0x61,0x6d,
    0x65,0x22,0x3a,0x22,0x31,0x32,0x33,0x34,0x35,0x36,0x37,0x38,0x39,0x30,0x31,0x22,
    0x7d,0x0D,0x0D,0x00
};

unsigned char namestr[] = { 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 };
unsigned char server_messages = 0;

/* KERNAL RS-232 buffers: page-aligned 256 bytes each.
   Placed at $C200/$C300 — free RAM during launcher phase.
   (Previously BSS arrays that pushed BSS past $8800 title screen.) */
#define RS232_READ_BUF   ((char *)0xC200)
#define RS232_WRITE_BUF  ((char *)0xC300)

/* KERNAL RS-232 buffer pointers (zero page). */
char **RIBUF = (char**)0x00F7;
char **ROBUF = (char**)0x00F9;

#if SERVER_MESSAGES
#define MIN_ROW     0
#define MAX_ROW     24
#else
#define MIN_ROW     12
#define MAX_ROW     24
#endif /* SERVER_MESSAGES */

/* Globals for use by simple conio type screen control. */
static int row = MIN_ROW, col = 0;

/* Globals used for configuration purposes. */
static int current_modem_type = SWIFTLINK_MODEM;
static bool serial_open;
static bool dial_enabled = true;

#define DIAL_HOST_MAX 30
/* Raw ASCII lowercase — cc65 string literals get PETSCII-mangled to uppercase. */
static unsigned char dial_host[DIAL_HOST_MAX + 1] = {
    0x61,0x70,0x70,0x2e,0x6e,0x65,0x6f,0x68,0x61,0x62,  /* app.neohab */
    0x69,0x74,0x61,0x74,0x2e,0x6f,0x72,0x67,0x3a,0x31,  /* itat.org:1 */
    0x39,0x38,0x36,0x00                                   /* 986\0      */
};
static unsigned char at_cmd[DIAL_HOST_MAX + 6]; /* "ATDT" + host + "\r\0" */

const char* serial_driver_name(void) {
    switch (current_modem_type) {
        case USER_PORT_MODEM:
            return "Userport 1200";
        case SWIFTLINK_MODEM:
            return "SwiftLink";
    }
    return "";
}

void clear_textbox(void)
{
    memset((unsigned char*)0x0540, 0x20, 679);
}

void error_message(char *msg)
{
    clear_textbox();
    textcolor(COLOR_YELLOW);
    gotoxy(0, 24);
    cputs("    -=< Press any key to return >=-");
    textcolor(COLOR_RED);
    gotoxy(0, 0);
    cputs("                 ERROR:\r\n");
    cputs(msg);
    /* Waits for any key. */
    while (cbm_k_getin() == 0)
        ;
}

void close_rs232(void) {
    if (serial_open) {
        if (current_modem_type == SWIFTLINK_MODEM) {
            ACIA_COMMAND = ACIA_CMD_OFF;
        } else {
            cbm_k_close(2);
        }
        serial_open = false;
    }
}

void fix_keyboard(void) {
    /* Ensure CIA1 keyboard scanning registers are correct.
       Some cc65 operations or serial activity can corrupt $DC0E. */
    *((unsigned char *)0xDC0E) = 0x01;  /* CIA1 CRA: Timer A on, no PB6 output */
    *((unsigned char *)0xDC02) = 0xFF;  /* CIA1 DDRA: Port A all outputs (columns) */
    *((unsigned char *)0xDC03) = 0x00;  /* CIA1 DDRB: Port B all inputs (rows) */
}

void restore_interrupts(void) {
    SEI();
    *((unsigned short *)0x0314) = 0x5F00;   /* Raster interrupt handler */
    *((unsigned short *)0x0318) = 0xFE47;   /* KERNAL NMI handler */
    *((unsigned char *)0xD012) = 106;
    *((unsigned char *)0xD019) = 0xFF;      /* Acknowledge pending VIC interrupts */
    *((unsigned char *)0xD01A) = 0x01;      /* Enable raster interrupts */
    fix_keyboard();
    __asm__("jsr $FFCC");                   /* CLRCHN: reset I/O to keyboard/screen */
    CLI();
}

void load_and_open_serial(void) {
    if (current_modem_type == USER_PORT_MODEM) {
        if (!serial_open) {
            /* Use KERNAL RS-232 at 1200 baud for userport mode. */
            *RIBUF = RS232_READ_BUF;
            *ROBUF = RS232_WRITE_BUF;
            cbm_k_setlfs(2, 2, 3);
            cbm_k_setnam(baud1200);
            cbm_k_open();
            serial_open = true;
        }
        return;
    }
    /* SwiftLink: direct ACIA register access (no cc65 serial driver).
       The cc65 ser_load_driver allocates heap memory for the driver module,
       which overlaps the title screen data at $8800/$8C00, crashing the
       NMI handler into color data.  Direct register access avoids this. */
    if (!serial_open) {
        ACIA_STATUS = 0x00;             /* Programmatic reset (write any value) */
        ACIA_CONTROL = ACIA_CTL_1200;   /* 1200 baud, 8N1, internal clock */
        ACIA_COMMAND = ACIA_CMD_POLL;    /* DTR on, TX enabled, polled RX */
        (void)ACIA_STATUS;              /* Read to clear any pending flags */
        serial_open = true;
    }
}

void change_modem_type(void) {
    if (current_modem_type == 2) {
        current_modem_type = 1;
    } else current_modem_type++;
    close_rs232();
}

/* Put a character to the 40 column display. */
void putscr(unsigned char c)
{
    unsigned char *scr, *clr;
    int val = row * 40 + col;

    scr = (unsigned char *)(0x400 + val);
    clr = (unsigned char *)(0xD800 + val);
    *scr = c;
    *clr = COLOR_GRAY3;

    if (++col > 39)
    {
        if (++row >= MAX_ROW)
            row = MIN_ROW;
        col = 0;
    }
}

/* Move to new line, clear remainder of current line. */
void newline(void)
{
    while (col != 0)
        putscr(0x20);
}

/* Convert most ASCII and escape codes to PETSCII screen codes. */
void petscii(unsigned char c)
{
    static unsigned char esc_count = 0;
    /* Normal characters. */
    if ((esc_count == 0) && (c < 0x7B))
    {
        if (c >= 0x61)
            putscr(c - (unsigned char)0x60);
        else if (c == 0x5C)
            putscr(0x2F);   /* swap backslash with slash */
        else if (c >= 0x5B)
            putscr(c - (unsigned char)0x40);
        else if (c >= 0x41)
            putscr(c);
        else if ((c >= 0x20) && (c < 0x40))
            putscr(c);
        //else if (c == 0x1B) /* escape sequence */
        //    esc_count = 2;
        else if (c == 0x0A)
            newline();
    }
    else if (c == 0x7B)
        putscr('<');
    else if (c == 0x7D)
        putscr('>');
}

/* Read from server until data stops being received. */
void get_rs232(void)
{
    if (current_modem_type == USER_PORT_MODEM) {
        /* KERNAL RS-232: poll with timeout loop to cover serial latency. */
        unsigned char i, j, c, flag;
        cbm_k_chkin(2);
        do {
            for (i = 0, flag = 0; i < 100; i++) {
                for (j = 0; j < 45; j++) {
                    if (c = cbm_k_getin()) {
                        if (server_messages)
                            petscii(c);
                        flag = 1;
                    }
                }
            }
        } while (flag);
        return;
    }
    /* SwiftLink: poll ACIA directly with timeout. */
    {
        unsigned char i, j, c, flag;
        do {
            for (i = 0, flag = 0; i < 100; i++) {
                for (j = 0; j < 45; j++) {
                    if (ACIA_STATUS & ACIA_ST_RDRF) {
                        c = ACIA_DATA;
                        if (server_messages)
                            petscii(c);
                        flag = 1;
                    }
                }
            }
        } while (flag);
    }
}

/* Send a string to the server. */
void put_rs232(const unsigned char *str)
{
    unsigned char i, c, delay;

    if (current_modem_type == USER_PORT_MODEM) {
        /* KERNAL RS-232: send via BSOUT with per-byte delay. */
        cbm_k_ckout(2);
        for (i = 0; ; i++) {
            if ((c = str[i]) == 0)
                break;
            /* Delay for SEND_DELAY frames to avoid overrunning output buffer. */
            for (delay = 0; delay < SEND_DELAY; delay++) {
                while (*((unsigned char *)0xD012) != 0xFF)
                    ;
            }
            cbm_k_bsout(c);
        }
        /* Wait until output buffer is fully drained. */
        while (*((unsigned char *)0x029D) != *((unsigned char *)0x029E))
            ;
        return;
    }

    /* SwiftLink: write bytes directly to ACIA with per-byte delay.
       The WDC 65C51 has a TDRE bug where the flag reads set immediately
       after a write, even though the byte hasn't shifted out yet.
       Use a frame-based delay to avoid overwriting the transmit register.

       Strip bit 7: cc65 string constants are PETSCII ($C1-$DA for uppercase)
       but the modem expects ASCII ($41-$5A).  Masking with $7F converts
       PETSCII back to ASCII, matching what pipe_modem.py does on the
       receive side.  The BASIC dialer doesn't need this because CBM BASIC's
       default uppercase characters ($41-$5A) already match ASCII.

       Use a simple busy-wait delay (~10ms at 1 MHz) matching the
       BASIC dialer's FOR D=1 TO 50 loop, instead of raster line
       polling which may interact with the split-screen handler. */
    for (i = 0; ; i++)
    {
        if ((c = str[i]) == 0)
            break;
        /* Wait ~50ms per byte (3 raster frames at 60Hz NTSC).
           This matches the DMA write timing that's proven to work
           on real U64 hardware.  Reading the volatile raster register
           prevents cc65 from optimizing the delay away. */
        for (delay = 0; delay < 3; delay++) {
            while (*((volatile unsigned char *)0xD012) != 0xFE)
                ;
            while (*((volatile unsigned char *)0xD012) == 0xFE)
                ;
        }
        ACIA_DATA = c & 0x7F;
    }
}

/* NMI handler for ACIA receive during modem dialing.
   Reads incoming bytes into a circular buffer at $C040.
   $C030 = write index, $C031 = read index.
   Installed at $C000, invoked via $0318 vector. */
static const unsigned char acia_nmi_code[] = {
    0x48,                   /* PHA                     */
    0x8A,                   /* TXA                     */
    0x48,                   /* PHA                     */
    0xAD, 0x81, 0xDF,       /* LDA $DF81  (STATUS)     */
    0x29, 0x08,             /* AND #$08   (RDRF?)      */
    0xF0, 0x0D,             /* BEQ +13    (skip)       */
    0xAE, 0x30, 0xC0,       /* LDX $C030  (write idx)  */
    0xAD, 0x80, 0xDF,       /* LDA $DF80  (DATA)       */
    0x9D, 0x40, 0xC0,       /* STA $C040,X (buffer)    */
    0xE8,                   /* INX                     */
    0x8E, 0x30, 0xC0,       /* STX $C030  (save idx)   */
    /* skip: */
    0x68,                   /* PLA                     */
    0xAA,                   /* TAX                     */
    0x68,                   /* PLA                     */
    0x40,                   /* RTI                     */
};

#define NMI_HANDLER  0xC000
#define NMI_RX_WIDX  (*(volatile unsigned char *)0xC030)
#define NMI_RX_RIDX  (*(volatile unsigned char *)0xC031)
#define NMI_RX_BUF   ((volatile unsigned char *)0xC040)

/* Dial the modem using AT commands and wait for CONNECT response.
   Returns true if connected, false on timeout. */
bool dial_modem(void)
{
    unsigned char resp[40];
    unsigned char resp_len = 0;
    unsigned int t;
    unsigned char i, j, k, c;
    bool got_data;
    bool result = false;

    textcolor(COLOR_CYAN);
    cputs("\r\nDialing NeoHabitat");

    /* Build AT command: "atdt" + dial_host + "\r"
       Raw ASCII lowercase — cc65 string literals become PETSCII uppercase
       and the U64 modem emulation requires lowercase. */
    at_cmd[0] = 0x61;  /* a */
    at_cmd[1] = 0x74;  /* t */
    at_cmd[2] = 0x64;  /* d */
    at_cmd[3] = 0x74;  /* t */
    at_cmd[4] = 0;
    strcat((char *)at_cmd, (char *)dial_host);
    i = strlen((char *)at_cmd);
    at_cmd[i] = 0x0D;      /* CR */
    at_cmd[i + 1] = 0x0D;  /* CR — terminal mode sends two, modem expects it */
    at_cmd[i + 2] = 0;

    /* Drain pending modem response (e.g. "OK" from DTR assertion) using
       the same polling timeout as get_rs232() / terminal mode. */
    get_rs232();

    /* Send AT command using already-initialized ACIA from load_and_open_serial().
       No ACIA reset — resetting drops DTR and confuses the U64 modem emulation. */
    put_rs232(at_cmd);

    textcolor(COLOR_GRAY3);

    for (t = 0; t < 600; t++) {
        if (current_modem_type == USER_PORT_MODEM)
            cbm_k_chkin(2);

        got_data = false;
        for (i = 0; i < 100; i++) {
            for (j = 0; j < 45; j++) {
                if (current_modem_type == USER_PORT_MODEM) {
                    c = cbm_k_getin();
                } else {
                    /* Poll RDRF directly — matches the working BASIC dialer. */
                    if (ACIA_STATUS & ACIA_ST_RDRF) {
                        c = ACIA_DATA;
                    } else {
                        c = 0;
                    }
                }
                if (c) {
                    got_data = true;
                    if (c == 0x0D || c == 0x0A) {
                        /* End of line — check for CONNECT. */
                        resp[resp_len] = 0;
                        if (resp_len >= 7) {
                            for (k = 0; k <= resp_len - 7; k++) {
                                /* Compare against ASCII values — cc65 char
                                   constants are PETSCII ($C3 not $43). */
                                if (resp[k]==0x43 && resp[k+1]==0x4F &&
                                    resp[k+2]==0x4E && resp[k+3]==0x4E &&
                                    resp[k+4]==0x45 && resp[k+5]==0x43 &&
                                    resp[k+6]==0x54) {
                                    result = true;
                                    goto dial_done;
                                }
                            }
                        }
                        resp_len = 0;
                    } else if (resp_len < 39) {
                        resp[resp_len++] = c;
                    }
                }
            }
        }
        /* Print progress dot every ~2 iterations (~2 seconds). */
        if ((t & 1) == 0)
            cputc('.');
    }

dial_done:
    if (result) {
        textcolor(COLOR_GREEN);
        cputs("\r\nConnected!\r\n");
    } else {
        error_message("Modem did not connect.\r\nCheck network connection.");
    }
    return result;
}

void draw_name(void)
{
    unsigned char j, c;

    gotoxy(9, 16);
    for (j = 0; j < 12; j++)
    {
        if ((c = namestr[j]) > 0)
            cputc(c);
        else
            cputc(' ');
    }
}

void draw_host(void)
{
    unsigned char j, c;
    gotoxy(9, 18);
    textcolor(COLOR_WHITE);
    for (j = 0; j < DIAL_HOST_MAX; j++) {
        if ((c = dial_host[j]) > 0)
            cputc(c);
        else
            cputc(' ');
    }
}

void draw_login (void)
{
    clear_textbox();
    textcolor(COLOR_YELLOW);
    gotoxy(0, 23);
    cputs("Modem: ");
    cputs(serial_driver_name());
    cputs(" | Dial: ");
    cputs(dial_enabled ? "ON " : "OFF");
    gotoxy(0, 24);
    cputs("F1:Credits F3:Modem F5:Dial F7:Terminal");
    textcolor(COLOR_CYAN);
    gotoxy(0, 10);
    cputs("            Habitat Launcher\r\n            ----------------\r\n\r\n");
    textcolor(COLOR_GRAY3);
    cputs("[Type a name of less than 12 characters]\r\n\r\n");
    textcolor(COLOR_CYAN);
    cputs("   Name: ");
    textcolor(COLOR_WHITE);
    if (dial_enabled) {
        gotoxy(0, 18);
        textcolor(COLOR_CYAN);
        cputs("   Host: ");
        draw_host();
    }
}

void terminal(void)
{
    unsigned char tosend[256], c, i;

    server_messages = 1;

    /* Load and open serial for terminal communication. */
    load_and_open_serial();
    /* Fix CIA1 so keyboard works alongside serial. */
    fix_keyboard();

    clear_textbox();
    textcolor(COLOR_YELLOW);
    gotoxy(0, 24);
    cputs(" -=< Press RUN/STOP or ESC to exit >=-");
    textcolor(COLOR_CYAN);
    gotoxy(0, 10);
    cputs("              Terminal Mode\r\n              -------------\r\n\r\n");

    /* Read server connection message, if present. */
    row = 13;
    col = 0;
    get_rs232();
    gotoxy(0, row+1);

    while (1)
    {
        cbm_k_chkin(0);
        textcolor(COLOR_WHITE);
        for (i = 0; i < 253; )
        {
            if (c = cbm_k_getin())
            {
                if (c == 0x03)  /* Run/Stop */
                {
                    i = 0;
                    tosend[0] = 0;
                    break;
                }
                else if (c == 0x0D)  /* Enter */
                {
                    if (i > 0)
                    {
                        tosend[i++] = c;
                        tosend[i++] = c;
                        tosend[i++] = 0;
                        cputc(c);
                        break;
                    }
                }
                else if (c == 0x14)  /* Backspace */
                {
                    if (i > 0)
                    {
                        i--;
                        /* cputc(0x14) would print 't' (screen code $14).
                           Manually erase: cursor left, space, cursor left. */
                        if (wherex() > 0) {
                            gotox(wherex() - 1);
                            cputc(' ');
                            gotox(wherex() - 1);
                        }
                    }
                    tosend[i] = 0;
                }
                else
                {

                    tosend[i++] = c;
                    cputc(c);
                }
            }
        }
        if (i > 0)
        {
            /* Convert to ASCII before sending. */
            for (i = 0; i < 255; i++)
            {
                c = tosend[i];
                if ((c >= 0x41) && (c <= 0x5A))
                    tosend[i] = c + 0x20;
                else if ((c >= 0xC1) && (c <= 0xDA))
                    tosend[i] = c - 0x80;
            }

            /* Send terminal input. */
            put_rs232(tosend);

            /* Get server response. */
            if ((row = wherey()) > 23)
                row = 14;
            col = 0;
            get_rs232();
            /* Sync conio cursor to where get_rs232 left off. */
            gotoxy(col, row);
        }
        else
            break;
    }

    server_messages = 0;

    /* Close serial and uninstall driver for clean return to login loop. */
    close_rs232();
    restore_interrupts();

    /* Restore logo to screen. */
    memcpy((unsigned char*)0x0400, logo_chars, sizeof(logo_chars));
    memcpy(COLOR_RAM, logo_colors, sizeof(logo_colors));
}

void draw_credits(void)
{
    clear_textbox();
    textcolor(COLOR_YELLOW);
    gotoxy(0, 24);
    cputs("    -=< Press any key to return >=-");
    textcolor(COLOR_CYAN);
    gotoxy(0, 10);
    cputs("          Neo-Habitat Credits\r\n          -------------------\r\n\r\n");
    textcolor(COLOR_WHITE);
    cputs(" Randy Farmer, Chip Morningstar,         ");
    cputs("Alex Handy, Stuart Cass, Keith Elkin,\r\n");
    cputs(" Steve Salevan, David McIntyre,\r\n");
    cputs(" Matt Post, Benj Edwards, Gary Lake,\r\n");
    cputs(" Ricky Derocher, Jason Goodman.\r\n\r\n");
    cputs(" The MADE, Fujitsu, SPI.NE hosting,\r\n");
    cputs(" Quantum Link Reloaded\r\n\r\n");
    textcolor(COLOR_CYAN);
    cputs(" Built on ELKO gaming platform.\r\n");
}

void draw_logo(void)
{
    memcpy((unsigned char*) 0x0400, logo_chars, sizeof(logo_chars));
    memcpy(COLOR_RAM, logo_colors, sizeof(logo_colors));
}

void main(void)
{
    unsigned char i, j, c, mode = 0;

    /* Save the first 3 bytes of the Exomizer SFX decompressor at $080E-$0810.
       The KERNAL screen editor's 26th-row overflow zone ($07E8-$080F) will
       overwrite $080E-$080F during any text screen scroll operation that
       happens later in the launcher. We restore these bytes before jumping
       to the decompressor. */
    unsigned char sfx_save[3];
    sfx_save[0] = *((unsigned char *)0x080E);
    sfx_save[1] = *((unsigned char *)0x080F);
    sfx_save[2] = *((unsigned char *)0x0810);

    /* Copy bitmap color data to color RAM. */
    memcpy((unsigned char *)0xD800, (unsigned char *)0x8C00, 1000);

    /* Display splash screen bitmap. */
    bgcolor(COLOR_BLACK);
    bordercolor(COLOR_CYAN);
    *((unsigned char *)0xD011) = 0x3B;     /* Set bitmap mode. */
    *((unsigned char *)0xD016) = 0x18;     /* Set multi-color. */
    *((unsigned char *)0xD018) = 0x28;     /* Set screen RAM to $x+800, bitmap to $x+2000. */
    *((unsigned char *)0xDD00) = 0x01;     /* set VIC to bank 2, $8000. */

    /* Set input from device 0 (keyboard). */
    cbm_k_chkin(0);

    /* Get any key. */
    while (cbm_k_getin() == 0)
        ;

    *((unsigned char *)0xD011) = 0x1B;      /* Set 0xD011 raster high bit to 0 (upper screen). */
    *((unsigned char *)0xD016) = 0x08;      /* Set hi-res. */
#if RASTER_INTERRUPT
    *((unsigned char *)0xD018) = 0x15;      /* Set screen RAM to default $0400. */
#else
    *((unsigned char *)0xD018) = 0x17;      /* Set screen RAM to default $0400. */
#endif /* RASTER_INTERRUPT */
    *((unsigned char *)0xDD00) = 0x17;      /* set VIC back to default. */

    /* Draw login screen. */
    bgcolor(COLOR_BLACK);
    bordercolor(COLOR_BLACK);

    /* Do NOT install raster handler at $5F00 yet — it has a bug where CIA1
       interrupts during raster lines 72-107 exit via $EA7E without reading
       $DC0D, leaving the IRQ line asserted and trapping the CPU in an IRQ
       loop that prevents keyboard scanning. Install it only after login. */

    /* Copy logo to screen. */
    draw_logo();
    draw_login();

    /* Fully reinitialize CIA1 and IRQ system for keyboard scanning.
       cc65's conio installs its own IRQ handler at $0314 that prevents
       the KERNAL keyboard scan at $EA31 from running. We bypass cc65
       and point $0314 to the raster handler which chains to $EA31.

       The raster handler at $5F00 has a bug: CIA interrupts during raster
       lines 72-107 exit via JMP $EA7E without reading $DC0D, leaving the
       IRQ asserted and trapping the CPU. Patch: change JMP $EA7E to
       JMP $EA31 at $5F15 so ALL CIA interrupts reach the keyboard scan. */
    SEI();
    *((unsigned char *)0x5F16) = 0x31;      /* Patch $5F15: JMP $EA7E → JMP $EA31 */
    *((unsigned short *)0x0314) = 0x5F00;   /* Raster interrupt handler */
    *((unsigned char *)0xD012) = 106;       /* Initial raster line */
    *((unsigned char *)0xD019) = 0xFF;      /* Acknowledge pending VIC interrupts */
    *((unsigned char *)0xD01A) = 0x01;      /* Enable raster interrupts */
    *((unsigned char *)0xDC0E) = 0x00;      /* Stop Timer A */
    *((unsigned char *)0xDC04) = 0x25;      /* Timer A latch low (NTSC ~60Hz) */
    *((unsigned char *)0xDC05) = 0x40;      /* Timer A latch high */
    *((unsigned char *)0xDC0D) = 0x7F;      /* Disable all CIA1 interrupts */
    (void)*((volatile unsigned char *)0xDC0D);  /* Read to clear pending flags */
    *((unsigned char *)0xDC0D) = 0x81;      /* Enable Timer A interrupt */
    *((unsigned char *)0xDC0E) = 0x11;      /* Start Timer A + force load */
    *((unsigned char *)0xDC02) = 0xFF;      /* DDR A: all outputs (columns) */
    *((unsigned char *)0xDC03) = 0x00;      /* DDR B: all inputs (rows) */
    CLI();

login_loop:
    for (i = 0; i < 12; )
    {
        if (c = cbm_k_getin())
        {
            if (mode == 1)  /* Exit credit view mode if any key pressed. */
            {
                draw_login();
                draw_name();
                mode = 0;
                continue;
            }

            if (c == 0x85)  /* F1 */
            {
                draw_credits();
                mode = 1;
                continue;
            } else if (c == 0x86 && mode != 1) /* F3 */
            {
                change_modem_type();
                draw_logo();
                draw_login();
                draw_name();
                continue;
            } else if (c == 0x87) /* F5 */
            {
                dial_enabled = !dial_enabled;
                draw_login();
                draw_name();
                continue;
            } else if (c == 0x88) /* F7 */
            {
                terminal();
                draw_login();
                draw_name();
                mode = 0;
                continue;
            }

            if (c == 0x0D)  /* Enter */
            {
                if (i > 0)
                    break;
            }
            else if (c == 0x14)  /* Backspace */
            {
                if ((i == 10) && (namestr[i] != 0))
                {
                }
                else if (i > 0)
                    i--;
                namestr[i] = 0;
            }
            else if (c == ' ')
            {
                /* Accept spaces only after start. */
                if (i > 0)
                {
                    namestr[i] = c;
                    if (i < 10)
                        i++;
                }
            }
            else if (((c >= 'a') && (c <= 'z')) || ((c >= 'A') && (c <= 'Z')) || ((c >= '0') && (c <= '9')))
            {
                namestr[i] = c;
                if (i < 10)
                    i++;
            }

            draw_name();
        }
    }

    /* Trim trailing spaces. */
    for ( ; i > 0; i--)
    {
        if (!((namestr[i] == ' ') || (namestr[i] == 0)))
            break;
        namestr[i] = 0;
    }
    i++;

    /* Convert to ASCII and copy to login string. */
    for (j = 0; j < i; j++)
    {
        c = namestr[j];
        if ((c >= 0x41) && (c <= 0x5A))
            namestr[j] = c + 0x20;
        else if ((c >= 0xC1) && (c <= 0xDA))
            namestr[j] = c - 0x80;
        login_json[NAME_OFFSET + j] = namestr[j];
    }

    for (j = 0; j < END_LENGTH; j++)
    {
        login_json[NAME_OFFSET + i + j] = login_json[NAME_END + j];
    }

    /* If dialing is enabled, let user edit the host before connecting. */
    if (dial_enabled) {
        /* Find current host length. */
        i = strlen((char *)dial_host);

        gotoxy(0, 20);
        textcolor(COLOR_GRAY3);
        cputs("[Edit host or press RETURN to accept]");
        gotoxy(9, 18);
        textcolor(COLOR_WHITE);

        for (;;)
        {
            if (c = cbm_k_getin())
            {
                if (c == 0x0D)  /* Enter — accept host */
                    break;
                else if (c == 0x14)  /* Backspace */
                {
                    if (i > 0) {
                        i--;
                        dial_host[i] = 0;
                    }
                }
                else if (i < DIAL_HOST_MAX)
                {
                    /* Convert PETSCII to ASCII for host string. */
                    if (c >= 0xC1 && c <= 0xDA)
                        c = c - 0x80;       /* Shifted PETSCII → ASCII uppercase */
                    else if (c >= 0x41 && c <= 0x5A)
                        c = c + 0x20;       /* Unshifted PETSCII → ASCII lowercase */
                    else if (c < 0x20 || c >= 0x7B)
                        continue;           /* Skip non-printable */
                    dial_host[i] = c;
                    i++;
                    dial_host[i] = 0;
                }

                draw_host();
            }
        }
    }

    textcolor(COLOR_GRAY3);
    cputs("\r\n\r\nConnecting to server...\r\n");

    /* Now load driver and open serial port for server communication. */
    load_and_open_serial();

    /* Wake up U64 modem emulation.  Disable EasyFlash cart first —
       with the cart active on the bus, CPU writes to ACIA at $DF80
       may not reach the modem emulation layer.  Re-init ACIA with
       DTR assertion, send AT\r to wake modem, then re-enable cart. */
    if (current_modem_type == SWIFTLINK_MODEM) {
        volatile unsigned int dly;
        static const unsigned char at_wake[] = { 0x41, 0x54, 0x0D, 0x00 };
        *((unsigned char *)0xDE02) = 0x04;  /* EF_OFF: disable cart */
        ACIA_STATUS = 0x00;                 /* Programmatic reset */
        ACIA_CONTROL = ACIA_CTL_1200;
        ACIA_COMMAND = 0x0B;                /* DTR on, TX enabled */
        for (dly = 0; dly < 10000; dly++) ; /* ~500ms settle */
        put_rs232(at_wake);
        get_rs232();
        *((unsigned char *)0xDE02) = 0x03;  /* EF_8K: re-enable cart */
    }

    if (dial_enabled) {
        if (!dial_modem()) {
            close_rs232();
            restore_interrupts();
            draw_logo();
            draw_login();
            i = 0;
            draw_name();
            goto login_loop;
        }
    }

    /* Read server connection message, if present. */
    get_rs232();

    /* Send JSON formatted string to the server. */
    put_rs232(login_json);

    textcolor(COLOR_WHITE);
    cputs("Launching Habitat\r\n");

    /* Get server response. */
    get_rs232();

#if DEBUG_INTERACTIVE
    /* Interactive mode. */
    for (;;)
    {
        *((unsigned char *)0xD020) = *((unsigned char *)0xD020) + 1;

        /* look for a keyboard press */
        cbm_k_chkin(0);
        if (c = cbm_k_getin())
        {
            putscr(c);  // echo to screen
            if (c == '<')
                c = 0x7B;       /* Convert '<' into '{' for JSON purposes */
            else if (c == '>')
                c = 0x7D;       /* Convert '>' into '}' */
            cbm_k_ckout(2);
            cbm_k_bsout(c);
        }

        /* look for input on rs232 */
        cbm_k_chkin(2);
        if (c = cbm_k_getin())
            petscii(c);
    }
#endif /* DEBUG_INTERACTIVE */

    /* Clean up serial before handing off to game. */
    if (current_modem_type == SWIFTLINK_MODEM) {
        /* SwiftLink: keep DTR active so the modem connection stays alive
           until the game's acia_open takes over.  Already in polled mode
           (no NMI), so just ensure interrupts are off. */
        ACIA_COMMAND = ACIA_CMD_OFF;   /* DTR on, all interrupts disabled */
    } else {
        /* Userport: close the KERNAL RS-232 session (logical file 2).
           This clears KERNAL's RS-232 state variables so that when init_disk
           re-enables CIA2 NMIs, the KERNAL NMI handler doesn't try to
           transmit garbage from the overwritten TX buffer.
           The VICE RS-232 pipe stays alive — it's managed by the emulator,
           not by the KERNAL RS-232 driver. */
        cbm_k_close(2);
        __asm__("jsr $FFCC");  /* CLRCHN: reset I/O channels */
    }

    SEI();

    /* Restore interrupt vectors. */
    *((unsigned short *)0x0314) = 0xEA31;   /* IRQ: KERNAL default */
    *((unsigned short *)0x0318) = 0xFE47;   /* NMI: KERNAL default */

    /* Blank screen and set border for decruncher. */
    *((unsigned char *) 0xD011) = 0x6B;
    *((unsigned char *) 0xD01A) = 0x00;     /* Disable VIC raster interrupts. */
    *((unsigned char *) 0xD020) = 0x0E;     /* Seed border color to light blue. */

    fix_keyboard();                         /* Ensure CIA1 keyboard regs are clean. */

    /* Silence all NMI sources before Exomizer decompression.
       The KERNAL NMI handler modifies zero-page locations that can
       overlap with the Exomizer's zero-page decruncher code. */
    *((unsigned char *)0xDD0D) = 0x7F;      /* Disable all CIA2 NMI sources. */
    i = *((unsigned char *)0xDD0D);         /* Acknowledge any pending CIA2 NMI. */
    if (current_modem_type == SWIFTLINK_MODEM) {
        ACIA_COMMAND = ACIA_CMD_OFF;       /* Disable ACIA interrupts, keep DTR on. */
        (void)ACIA_STATUS;                 /* Read status to clear any pending state. */
    }

    /* Signal ACIA mode to the main game assembly.
       Uses $0210 (KERNAL input buffer) — safe because:
       - $0297: overwritten by KERNAL NMI handler during init_disk
       - $03FF: zeroed by Exomizer SFX decrunch table init ($0334-$03FF)
       - $0330-$0333: contains Exomizer SFX code residue
       - $0210: untouched by SFX (only writes $00FD-$01FB + target $0806+)
       No interrupts fire during decrunch (SEI + NMI disabled). */
    *((unsigned char *)0x0210) = (current_modem_type == SWIFTLINK_MODEM) ? 0xFF : 0x00;

    /* Set rs232 DCD (data carrier detect) value for user port mode only. */
    if (current_modem_type != SWIFTLINK_MODEM) {
        *((unsigned char *)0xDD01) = 0x51;
    }

    if (*((unsigned char *)0x0211) == 0xFF) {
        /* ── CRT mode: copy uncompressed game from cart banks ── */
        static const unsigned char game_copier[] = {
            0x78,                   /* $0100: SEI                      */
            0xA9, 0x37,             /* $0101: LDA #$37  (HIRAM=1)      */
            0x85, 0x01,             /* $0103: STA $01                  */
            0xA9, 0x03,             /* $0105: LDA #$03  (serve_rom ROML)*/
            0x8D, 0x02, 0xDE,      /* $0107: STA $DE02                */
            /* bank_loop: */
            0xA5, 0xFD,             /* $010A: LDA $FD                  */
            0x8D, 0x00, 0xDE,      /* $010C: STA $DE00                */
            0xA9, 0x80,             /* $010F: LDA #$80                 */
            0x8D, 0x1C, 0x01,      /* $0111: STA $011C                */
            0xA9, 0x20,             /* $0114: LDA #32                  */
            0x85, 0xFF,             /* $0116: STA $FF                  */
            0xA0, 0x00,             /* $0118: LDY #$00                 */
            /* inner_loop: */
            0xB9, 0x00, 0x80,      /* $011A: LDA $8000,Y              */
            0x91, 0xFB,             /* $011D: STA ($FB),Y              */
            0xC8,                   /* $011F: INY                      */
            0xD0, 0xF8,             /* $0120: BNE $011A                */
            0xE6, 0xFC,             /* $0122: INC $FC                  */
            0xEE, 0x1C, 0x01,      /* $0124: INC $011C                */
            0xC6, 0xFF,             /* $0127: DEC $FF                  */
            0xD0, 0xED,             /* $0129: BNE $0118                */
            0xE6, 0xFD,             /* $012B: INC $FD                  */
            0xC6, 0xFE,             /* $012D: DEC $FE                  */
            0xD0, 0xD9,             /* $012F: BNE $010A                */
            /* done: */
            0xA9, 0x04,             /* $0131: LDA #$04  (cart off)     */
            0x8D, 0x02, 0xDE,      /* $0133: STA $DE02                */
            0xA9, 0x37,             /* $0136: LDA #$37                 */
            0x85, 0x01,             /* $0138: STA $01                  */
            0x4C, 0x16, 0x08       /* $013A: JMP $0816                */
        };
        memcpy((unsigned char *)0x0100, game_copier, sizeof(game_copier));
        *((unsigned char *)0xFB) = 0x06;
        *((unsigned char *)0xFC) = 0x08;
        *((unsigned char *)0xFD) = *((unsigned char *)0x0213);
        *((unsigned char *)0xFE) = *((unsigned char *)0x0214);
        __asm__("ldx #$ff");
        __asm__("txs");
        __asm__("jmp $0100");
    }

    /* ── Disk mode: Exomizer SFX decompression ── */

    /* Restore Exomizer SFX decrunch bytes corrupted by KERNAL screen editor.
       $080D: main.asm skips 15 bytes of mcmg.exo (2-byte load addr + 13-byte
       BASIC stub), which drops the first decompressor byte ($A0 = LDY).
       $080E-$0810: KERNAL screen editor's 26th-row overflow zone ($07E8-$080F)
       overwrites these bytes during text scroll operations. */
    *((unsigned char *) 0x080D) = 0xA0;
    *((unsigned char *) 0x080E) = sfx_save[0];
    *((unsigned char *) 0x080F) = sfx_save[1];
    *((unsigned char *) 0x0810) = sfx_save[2];

    /* Exomizer SFX does INC $01 at $0810.  It expects the C64 default $37
       so INC yields $38 (all-RAM, no ROMs).  cc65 leaves $01=$36, which
       would INC to $37 (BASIC ROM visible at $A000-$BFFF), corrupting
       match copies that reference previously-decompressed data there. */
    *((unsigned char *) 0x0001) = 0x37;

    /* Reset hardware stack and jump to Exomizer SFX decompressor at $080D.
       It decompresses the game to $0806-$9A08, then JMPs to $0816.
       Use JMP (not JSR/call) since we never return. */
    __asm__("ldx #$ff");
    __asm__("txs");
    __asm__("jmp $080D");
}
