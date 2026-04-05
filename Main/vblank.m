; 	Vblank may have NO temporary variables
; 	AND MUST BE INTERRUPTABLE! (irq from rs232)


define	IRQ_routine		=	0xfffe
define	NMI_routine		=	0xfffa
define	BRK_routine		=	0xfffc

define	opcode_nop		=	0xea
define	opcode_jmp		=	0x4c

graphics_mode::			byte	0	;  0=bitmap ff=text
sprites_enabled::		byte	0	; a shadow reg

init_vblank::
	sei					; init NMI

	lda	0xdd02
	ora	#0b00000011
	sta	0xdd02

	lda	0xdd00
	and	#0b11111100
	ora	#vic_bank_bits			; for bank 2
	sta	0xdd00				; this is our page control

	moveb	#special_mode,	graphics_mode
	moveb	#0b00010000,	current_screen

	; Write NMI vector to RAM at $FFFA-$FFFB.
	; Cannot use movew here — Macross makeFirstByte extracts the
	; low byte of the address constant ($FA), generating STA $FA
	; (zero-page) instead of the intended STA $FFFA (absolute).
	lda	#/normal_NMI
	sta	0xfffa
	sta	0x0318
	lda	#?normal_NMI
	sta	0xfffb
	sta	0x0319
	; Write BRK/RESET vector to RAM at $FFFC-$FFFD.
	lda	#/Normal_BRK
	sta	0xfffc
	sta	0x0316
	lda	#?Normal_BRK
	sta	0xfffd
	sta	0x0317
	moveb	#0b00011011,	VIC_control	; allow VBLANK
	jsr	set_bitmap_on_vector
	moveb	#0b10000001,	IRQ_flag
	sta			IRQ_mask
	lda			interrupt_control	; let IRQs go
	moveb	#0b00001000,	IRQ_timer_a
	sta			IRQ_timer_b
	lda			NMI_interrupt		; clear any pending

	cli
	rts

bitmap_on_IRQ:
	pha						; 3
	txa						; 2
	pha						; 3
	tya						; 2
	pha						; 3

	save_and_bank_IO_in				; 11

mif (0) {
	moveb	#0,		sprite_enable		; 6
} melse {
    	nop
	nop
	nop
}

top_interrupt_delay::
	nop						; 2
	nop						; 2
	nop						; 2

	repeat	4 {nop}					; 8

bitmap_on_start::
	repeat	4 {nop}					; 6
	moveb	#black,		background_color	; 6
	moveb	#0b00011000,	vic_control_2		; 6
	moveb	#0b00111011,	vic_control		; 6
	moveb	current_screen,	vic_memory_control
	moveb	#blue,		background_color
	movew	#bitmap_off_IRQ,IRQ_routine
	moveb	#252,		IRQ_scanline
	moveb	#0xff,		bitmap_on_flag
	moveb	sprites_enabled,	sprite_enable
	moveb	#1,		IRQ_flag
	lda	interrupt_control

standard_interrupt_exit::

	restore_IO

	pla
	tay
	pla
	tax
	pla
	rti


bitmap_off_IRQ:
	pha
	txa
	pha
	tya
	pha

	save_and_bank_IO_in

	ldy	#0
	sty	sprite_enable

interrupt_delay::
	nop
	nop
	nop

	repeat 4 {nop}

bitmap_off_start::
	sty	background_color
	nop
	moveb	#0b00011011,	vic_control		; to text!
	moveb	#0b00011000,	vic_memory_control	; charset at +x2000
	moveb	#0b00001000,	vic_control_2		; to text mode
	sty	background_color
	sty	bitmap_on_flag
	lda	screen_is_off
	if (!zero) {					; screen got shut off!
	    jmp		turn_screen_off
	}
	moveb	#0b00011000,	vic_memory_control	; prevent flicker
	bit	graphics_mode
	if (plus) {					; dont do this if
	    jsr	set_bitmap_on_vector
	}

	moveb	sprites_enabled,	sprite_enable

;	ldy	cursor_y
;	cpy	#cursor_over_interrupt
;	if (!carry) {
;	    lda	#opcode_nop
;	    tax
;	    tay
;	} else {
;	    lda	#opcode_jmp
;	    ldx #/bitmap_off_start
;	    ldy #?bitmap_off_start
;	}
;	sta	interrupt_delay
;	stx	interrupt_delay+1
;	sty	interrupt_delay+2

	moveb	#1, 		IRQ_flag
	lda	interrupt_control	; resume interrupts

	cli

	inc	clock
	dec16	vblank_timer
	lda	latch
	if (zero) {
		inc	latch				; 6.2 Super Hack
		jsr	maintain_rs232
		jsr	maintain_sounds
		jsr	vblank_keys
		jsr	vblank_get_key
		jsr	read_joystick
		jsr	cursor
		dec	sample_counter
		if (zero) {
		    jsr	sample_counter_expired
		}
		dec	latch
	}

	jmp	standard_interrupt_exit


turn_screen_off:
	moveb	#0b00001011, VIC_control
	movew	#blank_IRQ, IRQ_routine
	moveb	#251,	IRQ_scanline
	moveb	#1,	IRQ_flag
	lda	interrupt_control
	jmp	standard_interrupt_exit

blank_IRQ::
	pha
	txa
	pha
	tya
	pha

	save_and_bank_IO_in

	lda	screen_is_off
	if (zero) {					; screen is back!
	    jsr	set_bitmap_on_vector
	} 		
	moveb	#1, 		IRQ_flag
	lda	interrupt_control	; resume interrupts
	cli

	lda	latch
	if (zero) {
		inc	latch
		jsr	maintain_sounds
		jsr	maintain_rs232
		dec	latch
	}

	jmp	standard_interrupt_exit

set_bitmap_on_vector:
	movew	#bitmap_on_IRQ,	IRQ_routine
	moveb	#(quip_y),	IRQ_scanline
	rts

normal_BRK:
	rti

normal_NMI::
	pha
	txa
	pha
	tya
	pha

	save_and_bank_IO_in

	moveb	#0b01111111,NMI_interrupt	; force hibit low
	moveb	NMI_interrupt,hold_interrupt
mif (debug_mode) {
	lda	fastlink_on			; software switch
	if (!zero) {
		restore_io
		pla
		tay
		pla
		tax
		pla				; faslink does it own thing
		jmp	c_NMI			; go to fastlink
	}
}
	jmp	acia_NMI			; drain ACIA data, RTI


