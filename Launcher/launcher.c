#include <stdio.h>
#include <conio.h>
#include <string.h>
#include <6502.h>
#include "logo.h"

#define SERVER_MESSAGES     0
#define DEBUG_INTERACTIVE   0
#define RASTER_INTERRUPT    1
#define SEND_DELAY          2

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

/* 256 byte read/write buffers for rs232 device. */
/* (over-allocated to 512 bytes, due to manipulation of base pointer for page-alignment) */
char rs232_read_buf[512];
char rs232_write_buf[512];

/* Kernal rs232 input/output buffer pointers. */
char **RIBUF = (char**)0x00F7;
char **ROBUF = (char**)0x00F9;
char *rs232_out_current = (char *)0x029D;
char *rs232_out_top = (char *)0x029E;

#if SERVER_MESSAGES
#define MIN_ROW     0
#define MAX_ROW     24
#else
#define MIN_ROW     12
#define MAX_ROW     24
#endif /* SERVER_MESSAGES */

/* Globals for use by simple conio type screen control. */
static int row = MIN_ROW, col = 0;

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

#if 0
    /* Skip escape sequences of ESC+2 chars. */
    if (esc_count == 1)
    {
        if (!((c >= 0x30) && (c <= 0x39)))
            esc_count = 0;
    }
    else if (esc_count == 2)
    {
        if ((c == 0x1B) || (c == 0x5B))
            esc_count--;
        else
            esc_count = 0;
    }
#endif

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
    unsigned char i, j, c, flag;

    /* Set read channel to rs232, output to screen. */
    cbm_k_chkin(2);

    /* Read until no more data (flag is not set). */
    do
    {
        /* Repeat 100 times to cover most lag. */
        for (i = 0, flag = 0; i < 100; i++)
        {
            for (j = 0; j < 45; j++)
            {
                if (c = cbm_k_getin())
                {
#if SERVER_MESSAGES
                    petscii(c);
#else
                    if (server_messages)
                        petscii(c);
#endif /* SERVER_MESSAGES */
                    flag = 1;
                }
            }
        }
    } while (flag);
}

/* Send a string to the server. */
void put_rs232(const unsigned char *str)
{
    unsigned char i, c, delay;

    /* Switch output to rs232 device. */
    cbm_k_ckout(2);

    /* Add each character of string to send buffer (max 256 bytes). */
    for (i = 0; ; i++)
    {
        if ((c = str[i]) == 0)
            break;

        /* Delay for SEND_DELAY number of frames. */
        for (delay = 0; delay < SEND_DELAY; delay++)
        {
            while (*((unsigned char *)0xD012) != 0xFF)
                ;
        }

        /* Send character. */
        cbm_k_bsout(c);
    }

    /* Wait until output buffer empty. */
    while (*rs232_out_current != *rs232_out_top)
        ;
}

void clear_textbox(void)
{
    memset((unsigned char*)0x0540, 0x20, 679);
    /* memset((unsigned char*)0xD940, COLOR_GRAY3, 679); */
}

void draw_name(void)
{
    unsigned char j, c;

    gotox(9);
    for (j = 0; j < 12; j++)
    {
        if ((c = namestr[j]) > 0)
            putchar(c);
        else
            putchar(' ');
    }
}

void draw_login (void)
{
    clear_textbox();
    textcolor(COLOR_YELLOW);
    gotoxy(0, 24);
    //printf("   -=< Press [F1] to view credits >=-");
    printf(" [F1] View Credits   [F7] Terminal Mode");
    textcolor(COLOR_CYAN);
    gotoxy(0, 10);
    printf("            Habitat Launcher\n            ----------------\n\n");
    textcolor(COLOR_GRAY3);
    printf("[Type a name of less than 12 characters]\n\n");
    textcolor(COLOR_CYAN);
    printf("   Name: ");
    textcolor(COLOR_WHITE);
}

void terminal(void)
{
    unsigned char tosend[256], c, i;

    server_messages = 1;

    clear_textbox();
    textcolor(COLOR_YELLOW);
    gotoxy(0, 24);
    printf(" -=< Press RUN/STOP or ESC to exit >=-");
    textcolor(COLOR_CYAN);
    gotoxy(0, 10);
    printf("              Terminal Mode\n              -------------\n\n");

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
                        putchar(c);
                        break;
                    }
                }
                else if (c == 0x14)  /* Backspace */
                {
                    if (i > 0)
                    {
                        i--;
                        putchar(c);
                    }
                    tosend[i] = 0;
                }
                else
                {

                    tosend[i++] = c;
                    putchar(c);
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
        }
        else
            break;
    }

    server_messages = 0;

    /* Restore logo to screen. */
    memcpy((unsigned char*)0x0400, logo_chars, sizeof(logo_chars));
    memcpy(COLOR_RAM, logo_colors, sizeof(logo_colors));
}

void draw_credits(void)
{
    clear_textbox();
    textcolor(COLOR_YELLOW);
    gotoxy(0, 24);
    printf("    -=< Press any key to return >=-");
    textcolor(COLOR_CYAN);
    gotoxy(0, 10);
    printf("          Neo-Habitat Credits\n          -------------------\n\n");
    textcolor(COLOR_WHITE);
    printf(" Randy Farmer, Chip Morningstar,         ");
    printf("Alex Handy, Stuart Cass, Keith Elkin,\n");
    printf(" Steve Salevan, David McIntyre,\n");
    printf(" Matt Post, Benj Edwards, Gary Lake,\n");
    printf(" Ricky Derocher, Jason Goodman.\n\n");
    printf(" The MADE, Fujitsu, SPI.NE hosting,\n");
    printf(" Quantum Link Reloaded\n\n");
    textcolor(COLOR_CYAN);
    printf(" Built on ELKO gaming platform.\n");
    /*printf("Museum of Art and Digital Entertainment ");*/
}

void main(void)
{
    unsigned char retval, i, j, c, mode = 0;
    void(*bootfunc)(void) = (void*)0x080D;

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
    //clrscr();

#if RASTER_INTERRUPT
    SEI();
    *((unsigned short *)0x0314) = 0x5F00;   /* Set raster interrupt routine. */
    *((unsigned char *)0xD012) = 106;       /* Set initial raster interrupt line to 106. */
    *((unsigned char *)0xD01A) = 0x01;      /* Enable raster interrupts. */
    CLI();
#endif /* RASTER_INTERRUPT */

    /* Copy logo to screen. */
    memcpy((unsigned char*) 0x0400, logo_chars, sizeof(logo_chars));
    memcpy(COLOR_RAM, logo_colors, sizeof(logo_colors));

    /* Set rs232 buffers, using page-aligned addresses. */
    *RIBUF = (char*)(((int)rs232_read_buf & 0xff00) + 256);
    *ROBUF = (char*)(((int)rs232_write_buf & 0xff00) + 256);

    /* open rs232 channel */
    cbm_k_setlfs(2, 2, 3);
    cbm_k_setnam(baud1200);
    retval = cbm_k_open();

    /* Initialize rs232 DCD (data carrier detect) value. */
    *((unsigned char *)0xDD01) = 0x51;

    draw_login();
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
            }
            else if (c == 0x88) /* F7 */
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

    textcolor(COLOR_GRAY3);
    printf("\n\nConnecting to server...\n\n");

    /* Read server connection message, if present. */
    get_rs232();

    /* Send JSON formatted string to the server. */
    put_rs232(login_json);

    textcolor(COLOR_WHITE);
    printf("Launching Habitat\n");

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

    SEI();
    *((unsigned char *) 0xD011) = 0x6B;     /* Blank the screen. */
    *((unsigned short *)0x0314) = 0xEA31;   /* Restore KERNAL interrupts. */
    *((unsigned char *) 0xD01A) = 0x00;     /* Disable raster interrupts. */
    *((unsigned char *) 0xD020) = 0x0E;     /* Seed border color to light blue for decruncher. */
    *((unsigned char *) 0x080D) = 0xA0;     /* Restore first byte of exomizer decrunch routine. */
    CLI();

    /* Set rs232 DCD (data carrier detect) value for Habitat init. */
    *((unsigned char *)0xDD01) = 0x51;
    
    /* Jump to MCM launcher. */
    (*bootfunc)();
}





