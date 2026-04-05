rs232_timeout_counter:		byte	0
rs232_save_rcv_buffer_end:	byte	0

; ---- SwiftLink/ACIA driver (userport bit-bang removed) ----

rs232_NMI::
	jmp	acia_NMI

rs232_put::
	jmp	acia_put

acia_save_status::	byte	0
acia_transmitting::	byte	0
acia_nmi_pending::	byte	0	; set by NMI handler, cleared by vblank

acia_NMI::
	; NMI-driven ACIA receive.  Drain all pending bytes into the
	; ring buffer, then RTI.
	;
	; The drain loop reads ACIA_status on each iteration, which
	; clears the VICE NMI assertion (acia_set_int(..., 0) in
	; aciacore.c STATUS read handler).  Reading ACIA_data clears
	; RDRF.  After draining, both the NMI assertion and RDRF are
	; clear, so RTI does not re-enter — the 6502 NMI latch needs
	; a fresh HIGH→LOW edge to fire again.
	;
	; Previous versions disabled NMI here (CMD=$0B) and re-armed
	; at 60Hz in acia_poll_rx.  This caused OVERRUN: VICE's ACIA
	; alarm reads bytes from the pipe at baud rate regardless of
	; CMD.  With NMI disabled, bytes pile up in rxdata — only
	; the first survives, the rest are consumed from the pipe and
	; LOST (rs232drv_getc reads before checking RDRF).  Result:
	; ~33% byte loss on burst data, corrupting all packets.
acia_NMI_from_status::
	lda	ACIA_status
	and	#ACIA_ST_RDRF
	if (!zero) {
		ldy	rs232_rcv_buffer_end
		iny
		cpy	rs232_rcv_buffer_start
		if (!equal) {
			sty	rs232_rcv_buffer_end
			dey
			lda	ACIA_data
			sta	y[@rs232_input_buffer]
		} else {
			lda	ACIA_data
			lda	#0x04
			ora	rs232_status
			sta	rs232_status
		}
		jmp	acia_NMI_from_status	; drain all pending
	}
	; RDRF clear.  Toggle NMI off/on to force a clean edge
	; on the NMI line.  If a byte arrived between our last
	; RDRF=0 read and now, this creates a HIGH→LOW edge
	; that the 6502 can detect.  The ~6-cycle disable window
	; cannot cause byte loss at 1200 baud (8333 cycles/byte).
	lda	#ACIA_CMD_NO_IRQ
	sta	ACIA_command		; NMI disabled → line HIGH
	lda	#ACIA_CMD_RX_IRQ
	sta	ACIA_command		; NMI enabled → if RDRF, line LOW
	jmp	standard_interrupt_exit

acia_open::
	ldy	#0
	sty	rs232_enable		; no CIA2 NMI activity in ACIA mode
	sty	rs232_status

	moveb	rs232_rcv_buffer_end, rs232_rcv_buffer_start
	moveb	rs232_send_buffer_end, rs232_send_buffer_start

	movew	#rs232_input, rs232_input_buffer
	movew	#rs232_output, rs232_output_buffer

	clearb	acia_transmitting

	; Route NMIs through game handler even when KERNAL ROM is
	; mapped (e.g. during disk I/O).  The KERNAL's default NMI
	; handler at $FE47 doesn't know about the ACIA and would
	; leave received data unread, jamming the NMI line low.
	movew	#normal_NMI, 0x0318

	; Reconfigure ACIA registers.  The launcher's cc65 serial
	; driver already opened the connection and sent the login
	; JSON.  It left the ACIA with interrupts disabled ($DE02=$03)
	; but DTR active so the modem connection stays alive.
	; Do NOT write ACIA_status — that triggers a programmatic
	; reset which drops DTR and (in VICE) closes/reopens the
	; RS232 device, killing the server connection.
	lda	use_acia
	if (not_zero) {
	    lda	#ACIA_CTL_9600		; ACIA mode: 9600 baud (U64 modem is TCP)
	} else {
	    lda	#ACIA_CTL_1200		; Userport: keep 1200 baud
	}
	sta	ACIA_control		; 8N1, internal clock
	; Clear stale RDRF before enabling NMI.  If RDRF is already
	; set (from launcher phase), the NMI line is stuck LOW.
	; 6502 NMI is edge-triggered — needs HIGH→LOW transition.
	; Reading ACIA_data clears RDRF, deasserting the NMI line.
	lda	ACIA_status		; acknowledge IRQ flags
	lda	ACIA_data		; clear RDRF → NMI line goes HIGH
	lda	#ACIA_CMD_RX_IRQ	; DTR on, RX NMI enabled
	sta	ACIA_command		; NMI handler disables after draining;
					; acia_poll_rx re-arms at 60Hz.
	rts

acia_resume::
	; Re-arm ACIA after disk B loading.
	;
	; Unlike userport mode (where KERNAL IEC kills CIA2 NMIs and
	; no bytes arrive during disk I/O), ACIA NMIs keep firing
	; throughout disk B loading.  The 256-byte ring buffer fills
	; in ~2 seconds; the remaining ~28 seconds of server traffic
	; is dropped.  The stale 255 bytes in the ring buffer contain
	; partial packets with old sequence numbers.  If RS232I
	; processes them, the protocol state gets corrupted — NXTSEQ
	; advances past what the server expects, and subsequent valid
	; packets are rejected as duplicates.
	;
	; Fix: flush the ring buffer so the protocol starts clean,
	; matching userport's behavior.  Also clear RDRF to deassert
	; the NMI line (KERNAL NMI handler may have left it stuck LOW)
	; and re-enable RX NMI.
	moveb	rs232_rcv_buffer_end, rs232_rcv_buffer_start
	save_and_bank_IO_in
	lda	ACIA_status		; acknowledge IRQ flags
	lda	ACIA_data		; clear RDRF → NMI line HIGH
	lda	#ACIA_CMD_RX_IRQ
	sta	ACIA_command		; re-enable RX NMI
	restore_IO
	rts

acia_put::
	; Drain TX buffer by polling TDRE (Transmit Data Register
	; Empty).  VICE clears TDRE on write and re-sets it after
	; the baud-rate character time — no WDC 65C51 TDRE bug.
	; The poll loop naturally rate-limits to wire speed.
acia_put_loop:
	ldy	rs232_send_buffer_start
	cpy	rs232_send_buffer_end
	if (equal) {rts}		; buffer empty
	lda	ACIA_status
	and	#ACIA_ST_TDRE
	if (zero) {rts}			; TX busy — byte still shifting out
	lda	y[@rs232_output_buffer]
	sta	ACIA_data
	inc	rs232_send_buffer_start
	jmp	acia_put_loop

acia_poll_rx::
	; Safety drain + ensure NMI enabled — called from maintain_rs232
	; at 60Hz.  The NMI handler now stays armed (no CMD=$0B), so
	; this is normally a no-op.  It serves as a safety net: if a
	; byte arrived between the NMI drain loop exit and RTI (rare
	; race), this catches it.  Also ensures CMD=$09 is set in case
	; anything unexpected cleared it.
acia_poll_drain::
	lda	ACIA_status
	and	#ACIA_ST_RDRF
	if (!zero) {
		ldy	rs232_rcv_buffer_end
		iny
		cpy	rs232_rcv_buffer_start
		if (!equal) {
			sty	rs232_rcv_buffer_end
			dey
			lda	ACIA_data
			sta	y[@rs232_input_buffer]
		} else {
			lda	ACIA_data	; must read to clear RDRF
			lda	#0x04
			ora	rs232_status
			sta	rs232_status
		}
		jmp	acia_poll_drain		; check for more
	}
	; RDRF clear → NMI line HIGH.  Re-enable NMI.
	lda	#ACIA_CMD_RX_IRQ
	sta	ACIA_command
	rts
