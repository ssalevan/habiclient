; Low-memory code at $4800 — safe from ROML ($8000-$9FFF) and
; bitmap rendering ($4B40+/$6B40+).  Must be below $8000 because
; these routines execute while ROML is mapped or handle NMI during
; ROML mapping.
;
; Contains: NMI trampoline, cart sector reader, OBUFFS space.

	include "diskmacros.m"
	org	0x4800

;======================================================================
; NMI trampoline — buffers ACIA byte during ROML mapping ($01=$27).
; normal_NMI in vblank.obj is inside ROML ($8000-$9FFF); if NMI
; fires during cart reads, the trampoline handles it safely.
;======================================================================
nmi_trampoline::
	pha
	lda	0x01
	cmp	#0x27
	if (equal) {
		ldy	rs232_rcv_buffer_end
		lda	ACIA_data
		sta	y[@rs232_input_buffer]
		iny
		sty	rs232_rcv_buffer_end
		pla
		rti
	}
	pla
	jmp	normal_NMI

define track = tracksector+1
define sector = tracksector

;======================================================================
; Cart-based sector reader (EasyFlash)
;======================================================================
read_TS_cart::
	stx	ts_x_save
	sty	ts_y_save

	; Convert track/sector to linear sector number
	ldy	track
	lda	sector
	clc
	adc	y[cumul_sectors_lo]
	sta	cart_linear_lo
	lda	#0
	adc	y[cumul_sectors_hi]
	sta	cart_linear_hi

	; Calculate page within bank: (linear_sector & 31) + $80
	lda	cart_linear_lo
	and	#0x1f
	clc
	adc	#0x80			; high byte of $8000 + page*256
	sta	cart_src+2		; self-modify source address

	; Calculate bank: disk_b_base_bank + (linear_sector / 32)
	lda	cart_linear_hi
	asl	a
	asl	a
	asl	a			; high byte * 8
	sta	cart_temp
	lda	cart_linear_lo
	lsr	a
	lsr	a
	lsr	a
	lsr	a
	lsr	a			; low byte / 32
	ora	cart_temp		; combine
	clc
	adc	disk_b_base_bank
	sta	cart_bank

	; Disable interrupts — raster handler calls code in $8000+ range
	sei

	; Set banking: LORAM=1, HIRAM=1, CHAREN=1 for ROML + I/O visibility
	lda	#0x27
	sta	0x01

	; Disable ACIA RX NMI (vblank.obj at $809F is inside ROML window)
	lda	#0x0b
	sta	ACIA_command

	; Map ROML first, then select bank
	lda	#EF_8K
	sta	EF_control
	lda	cart_bank
	sta	EF_bank

	; Copy 256 bytes from cart ROM to disk_buffer
	ldy	#0
cart_copy_loop:
cart_src:
	lda	y[0x8000]		; self-modified high byte
	sta	y[disk_buffer]
	iny
	bne	cart_copy_loop

	; Unmap ROML
	lda	#EF_OFF
	sta	EF_control

	; Re-enable ACIA RX NMI
	lda	#ACIA_CMD_RX_IRQ
	sta	ACIA_command

	; Restore normal banking and re-enable interrupts
	bank_IO_out
	cli

	movew	tracksector, cur_buff_tracksec
	ldx	ts_x_save
	ldy	ts_y_save
	rts

; Cumulative sector count by track (for track/sector → linear sector)
cumul_sectors_lo:
	byte	0x00		; track 0 (unused)
	byte	0x00,0x15,0x2a,0x3f,0x54,0x69,0x7e,0x93	; tracks 1-8
	byte	0xa8,0xbd,0xd2,0xe7,0xfc,0x11,0x26,0x3b,0x50	; tracks 9-17
	byte	0x65		; track 18
	byte	0x78,0x8b,0x9e,0xb1,0xc4,0xd7	; tracks 19-24
	byte	0xea,0xfc,0x0e,0x20,0x32,0x44	; tracks 25-30
	byte	0x56,0x67,0x78,0x89,0x9a	; tracks 31-35

cumul_sectors_hi:
	byte	0x00		; track 0
	byte	0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00	; tracks 1-8
	byte	0x00,0x00,0x00,0x00,0x00,0x01,0x01,0x01,0x01	; tracks 9-17
	byte	0x01		; track 18
	byte	0x01,0x01,0x01,0x01,0x01,0x01	; tracks 19-24
	byte	0x01,0x01,0x02,0x02,0x02,0x02	; tracks 25-30
	byte	0x02,0x02,0x02,0x02,0x02	; tracks 31-35

cart_linear_lo:		byte	0
cart_linear_hi:		byte	0
cart_temp:		byte	0
cart_bank:		byte	0

;======================================================================
; ACIA poll helper — called from check_for_new_response tight loop.
; Drains TX, polls RX, runs RS232I, re-checks for packet.
;======================================================================
acia_poll_helper::
	save_and_bank_IO_in
	jsr	acia_put
	jsr	acia_poll_rx
	restore_IO
	jsr	p_send_a_buffer
	jmp	RS232I			; tail call, returns to caller
