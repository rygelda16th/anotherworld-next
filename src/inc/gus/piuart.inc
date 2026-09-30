;-----------------------------------------------------------------------------
; COPIED from nextpi-gus src/next/piuart.inc by tools/mkgusdata.py (`make gus-assets`): the
; build container cannot see that repo. Do not edit here; change it there.
;-----------------------------------------------------------------------------
; PROVENANCE: nextpi-opl src/next/piuart.inc at tag n5, copied unchanged (this line and
; the one above are new). gus.inc uses it as nopl.inc does.
; piuart.inc - the Next's side of the Pi UART: set it up, send, drain, wait for a token,
; get SUP's prompt.
;
; PROVENANCE: copied (2026-09-28) from keen4-next src/next/sound.asm (David's Commander
; Keen port, step X7), where these routines talk to NextPi's supervisor for the Pi music:
; pi_uart, pi_put, pi_puts, pi_drain, pi_expect, pi_ready. Only the constants and
; variables they need are gathered here; the Keen-specific ones (the installer's pages,
; the error codes) are left out. Changed here since (n3.1): pi_uart reads its NextRegs
; with interrupts held off (a handler that selects another NextReg could otherwise come
; between the select and the read: a wrong prescaler), and pi_put's timeout comment.

PI_TX           EQU $133B       ; write: a byte; read: the status
PI_TX_FULL      EQU 1           ;   bit 1: the Tx FIFO is full
PI_RX_READY     EQU 0           ;   bit 0: the Rx FIFO has bytes
PI_RX           EQU $143B       ; read: a byte; write: the prescaler's low 7 bits
PI_SELECT       EQU $153B       ; bit 6: the Pi's UART; bit 4 + 2:0: the prescaler's top
PI_NR_MACHINE   EQU $00         ; 8: an emulator (whose UART must not be reprogrammed)
PI_NR_TIMING    EQU $11         ; the video timing: the system clock, so the prescaler
PI_NR_PERIPH    EQU $A0         ; bit 5: the UART on GPIO 14/15, bit 4: the Pi's
PI_NR_I2S       EQU $A2         ; the Pi's I2S audio: off at every reset
PI_I2S_ON       EQU %11010010   ; stereo, from the Pi, slave (bit 1 must be 1 since core
                                ; 3.1.5), not to EAR: NextZXOS's own value (pi.bas, 210)

; the prescaler for 115,200 baud by NextReg $11's video timing (nextpidocs/
; WIFIand_UARTReadME1st.txt): wolf3d-next's fixed 234 is right for timing 7 only
pi_prescaler:   DW 243, 248, 256, 260, 269, 278, 286, 234

; pi_uart - the Pi's UART at 115,200 baud; on an emulator only the select bit
; (writing CSpect's prescaler silences its -com link: wolf3d-next's trap). Interrupts
; are held off while it runs (NextReg $00 and $11 read in one piece), then put back
pi_uart:
        ld a,i                          ; P/V = IFF2: were interrupts on?
        push af
        di
        call .set
        pop af
        ret po                          ; they were off: left off
        ei
        ret
.set:   ld bc,$243B
        ld a,PI_NR_MACHINE
        out (c),a
        inc b
        in a,(c)
        cp 8
        ret z
        nextreg PI_NR_PERIPH,%00110000
        ld bc,$243B
        ld a,PI_NR_TIMING
        out (c),a
        inc b
        in a,(c)
        and 7
        add a,a
        ld hl,pi_prescaler
        add hl,a
        ld e,(hl)
        inc hl
        ld d,(hl)                       ; DE = the prescaler
        ld bc,PI_SELECT
        ld a,%01010000                  ; the Pi's UART; prescaler bits 16:14 = 0
        out (c),a
        ld bc,PI_RX
        ld a,e                          ; bits 13:7 (bit 7 set: "the upper seven")
        rla
        ld a,d
        rla
        and $7F
        or $80
        out (c),a
        ld a,e                          ; bits 6:0
        and $7F
        out (c),a
        ret

; pi_put - A = a byte down the UART; waits while the Tx FIFO is full, at most 256
; polls (53 T each: about 0.5 ms at 28 MHz, the time the UART takes to send 5 bytes;
; with no flow control it drains whether a Pi is there or not). CF set: gave up.
pi_put:
        push bc
        push de
        ld e,a
        ld d,0
.w:     ld bc,PI_TX
        in a,(c)
        bit PI_TX_FULL,a
        jr z,.go
        dec d
        jr nz,.w
        pop de
        pop bc
        scf
        ret
.go:    ld a,e
        out (c),a
        pop de
        pop bc
        or a
        ret

; pi_puts - HL = a string, zero-terminated
pi_puts:
        ld a,(hl)
        or a
        ret z
        call pi_put
        ret c
        inc hl
        jr pi_puts

; pi_drain - throw away what the Pi has sent
pi_drain:
        ld d,0                          ; at most 256 bytes (an emulator may say
.b:     ld bc,PI_TX                     ; "ready" for ever)
        in a,(c)
        bit PI_RX_READY,a
        ret z
        ld b,high PI_RX
        in a,(c)
        dec d
        jr nz,.b
        ret

; pi_expect - HL = a four-letter token: read the Pi until those four letters come
; in a row, at most DE units of 256 status polls (PI_PER_S units a second at 28
; MHz). CF set: not seen.
PI_PER_S        EQU 1520
pi_expect:
        ld (pi_tok),hl
        ld (pi_budget),de
        ld hl,0
        ld (pi_win),hl
        ld (pi_win+2),hl
.poll:  ld b,0
.inner: push bc
        ld bc,PI_TX
        in a,(c)
        rrca                            ; bit 0: Rx has bytes
        jr nc,.none
        ld b,high PI_RX
        in a,(c)
        ld e,a
        ld hl,(pi_win+1)                ; the window slides left, the byte on the end
        ld (pi_win),hl
        ld a,(pi_win+3)
        ld (pi_win+2),a
        ld a,e
        ld (pi_win+3),a
        ld hl,(pi_tok)
        ld de,pi_win
        ld b,4
.cmp:   ld a,(de)
        cp (hl)
        jr nz,.none
        inc de
        inc hl
        djnz .cmp
        pop bc
        or a
        ret
.none:  pop bc
        djnz .inner
        ld hl,(pi_budget)
        dec hl
        ld (pi_budget),hl
        ld a,h
        or l
        jr nz,.poll
        scf
        ret

; pi_ready - ^C, a line end, and the prompt; DE = the wait. CF set: no prompt.
pi_ready:
        push de
        call pi_drain
        ld a,3
        call pi_put
        ld a,10
        call nc,pi_put
        pop de
        ret c
        ld hl,pi_t_prompt
        jp pi_expect

pi_t_prompt:    DB "SUP>"
pi_tok:         DW 0
pi_budget:      DW 0
pi_win:         DS 4
