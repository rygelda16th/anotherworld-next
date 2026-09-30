;-----------------------------------------------------------------------------
; COPIED from nextpi-gus src/next/gus.inc by tools/mkgusdata.py (`make gus-assets`): the
; build container cannot see that repo. Do not edit here; change it there.
;-----------------------------------------------------------------------------
; gus.inc - the Next's side of GUS1 (docs/protocol.md), game-independent.
;
; The card, nextpi-gus on the Pi, gets '#' text lines through a ring the host pumps into
; the Pi UART. tools/fakenext.py is the model this follows, and tools/gus_proto.py the
; reference for every byte.
;
; PROVENANCE: nextpi-opl src/next/nopl.inc at tag n5 (the CRC table, the alphabet, the
; ring and its pump, the '%' line collector, the SUP> window, the watchdog, the trip, the
; handoff and the stop): copied and cut down to GUS1's needs (no effects bank, no fast item
; path, no throttle). New here: GUS1's lines and events, the parsing of the card's '%'
; lines with their CRC, the upload with its questions and second passes, the memory CRC,
; the ping and the speed switch.
;
; The calls (AF, BC, DE and HL may change; IX, IY and the alternate registers are kept):
;
;   gus_init        once: the variables, the CRC table, the video timing (NextReg $11)
;   gus_start       the handoff, blocking: ^C, SUP>, "$ND/nextpi-gus", GUS1 within 3 s,
;                   NextReg $A2 = $D2, then gus_begin. A = the state: 2 running, 4
;                   failed (gus_err 1 no SUP>, 2 no GUS1). ND is the folder the host's
;                   probe line (or GUSINST.TXT's check) left in SUP's shell
;   gus_begin       H: the session's start without the handoff (gus_start's end, tests)
;   gus_tick        the host's frame interrupt: the clock (gus_now) on by a frame's 20
;                   ticks. AF and HL only; safe in an interrupt
;   gus_f           an F line opened at the clock's time (the line open before is closed)
;   gus_a           an A line opened at gus_stamp (3 bytes, the host's)
;   gus_note        a note on the open line, from gus_ev_voice, _pan, _sample, _vol, _rate
;   gus_stop        A = voice: stop it           gus_vol   A = voice, C = volume
;   gus_rate        A = voice, gus_ev_rate       gus_pan   A = voice, C = pan (0-16)
;   gus_wait        DE = ticks (1-16,383)        gus_alloff  every voice off
;   gus_cut         DE = the ticks back it reaches (F lines only)
;   gus_line_end    the open line closed (its CRC and LF)
;   gus_w           a W line: HL = the bytes, B = how many (1-174), gus_arg = the address
;   gus_pump        the ring into the UART's Tx FIFO, never waiting; safe in an interrupt
;   gus_poll        what the card says ('%' lines), SUP>, and the watchdog; never waits.
;                   A = the state: 4 when the card has gone (gus_err 3 no '%' line for 1.5 s,
;                   or 3 s until the second; 4 SUP> while running)
;   gus_upload      HL = the first block, DE = how many: the host's file (GUS_OPEN,
;                   GUS_READ, GUS_CLOSE) sent whole, then Q in 64s, then second passes of the
;                   named blocks' lines (3 at most). Blocking. CF clear: every block good.
;                   CF set, A: 1 the file failed, 2 no %Q answer, 3 blocks still named after
;                   three passes (gus_named_n), 4 the card went
;   gus_memcrc      gus_arg = the address (4 bytes), gus_arg + 4 = the length (4): M, and
;                   the answer into gus_m (4 bytes, CRC-32). CF set: no answer in 1 s
;   gus_ping        DE = a token: Y, and its %Y. CF set: no answer in 1 s
;   gus_speed       A = the code (1 115,200, 2 1 Mbit, 3 1.5 Mbit, 4 2 Mbit), C = flags (bit
;                   0 RTS/CTS): the switch (docs/protocol.md). CF set: not switched (A = 9
;                   on an emulator, whose UART must not be reprogrammed; else back at 115,200)
;   gus_end         E, %E within 3 s, SUP>; NextReg $A2 = 0. A = 0
;   gus_install     at SUP> (not running): the host's file (GUS_OPEN, GUS_READ, GUS_CLOSE, with
;                   the host's GUSINST.TXT) typed at SUP as it is, then GN42 awaited (30 s).
;                   CF clear: installed (ND is its folder). CF set: A = 1 the file failed, 2
;                   no GN42 (GE42, or nothing)
;
; The state (gus_state): 0 idle, 1 handshake, 2 running, 3 stopping, 4 dead or failed.
; gus_ui_hook (a word, 0 = none) is jumped to at every change of state.
;
; One producer: everything that writes the ring (the lines, events, gus_w, gus_upload's
; questions, gus_memcrc, gus_ping, gus_speed, gus_end) belongs to one context at a time.
; The blocking calls must run with the interrupt's own gus work gated off by the host, and
; with interrupts on (their time limits count GUS_FRAME_CTR). gus_pump may run in the
; interrupt handler and the main loop both (gus_busy keeps one out of the other).
;
; What the host sets (EQUs before the INCLUDE):
;   GUS_RING, GUS_RING_SIZE   the ring (a power of two, 256 to 32 KB)
;   GUS_CRCTAB                256 bytes, 256-aligned
;   GUS_FRAME_CTR             a word its frame interrupt adds 1 to
;   GUS_HZ60                  a byte: 0 at 50 Hz
;   GUS_D_MS, GUS_MEM_KB, GUS_GAIN   what H says (20, 1024, 128)
;   GUS_RDBUF, GUS_RDBUF_SIZE        gus_upload's buffer
; and the routines GUS_OPEN (the file from its start; CF on error), GUS_READ (DE = buffer,
; BC = most: BC = bytes read, 0 at the end; CF on error) and GUS_CLOSE, and piuart.inc's.
;-----------------------------------------------------------------------------

        ASSERT (GUS_CRCTAB & $FF) == 0
        ASSERT GUS_RING_SIZE >= 256
        ASSERT GUS_RING_SIZE <= $8000
        ASSERT (GUS_RING_SIZE & (GUS_RING_SIZE - 1)) == 0

GUS_MAX_ITEMS   EQU 81                  ; a line's items (250 characters)
GUS_MASK_H      EQU high (GUS_RING_SIZE - 1)
GUS_NAMED_MAX   EQU 512                 ; blocks one gus_upload call can ask about

;-----------------------------------------------------------------------------
gus_init:
        ld hl,gus_vars
        ld de,gus_vars + 1
        ld bc,gus_vars_end - gus_vars - 1
        ld (hl),0
        ldir
        ld a,8
        ld (gus_ev_pan),a
        ld hl,GUS_CRCTAB                ; CRC-8/SMBUS: poly $07, MSB first
        ld c,0
.n:     ld a,c
        ld b,8
.bit:   add a,a
        jr nc,.nx
        xor $07
.nx:    djnz .bit
        ld (hl),a
        inc l
        inc c
        jr nz,.n
        ld a,i                          ; P/V = IFF2
        push af
        di
        ld bc,$243B
        ld a,PI_NR_TIMING
        out (c),a
        inc b
        in a,(c)
        and 7
        ld (gus_vtiming),a
        pop af
        ret po
        ei
        ret

;-----------------------------------------------------------------------------
gus_start:
        ld a,1
        call gus_set_state
        call gus_ring_reset
        call pi_uart
        ld de,PI_PER_S * 2
        call pi_ready
        ld a,1
        jr c,.fail
        ld hl,gus_s_cmd
        call pi_puts
        ld hl,gus_s_gus1
        ld de,PI_PER_S * 3
        call pi_expect
        ld a,2
        jr c,.fail
        nextreg PI_NR_I2S,PI_I2S_ON     ; the Pi's sound into the Next
        call gus_begin
        ld a,2
        jr gus_set_state
.fail:  ld (gus_err),a
        ld a,4
        ; fall through
gus_set_state:
        ld (gus_state),a
        ld hl,(gus_ui_hook)
        ld a,h
        or l
        call nz,gus_jp_hl               ; the host's hook (it may change A):
        ld a,(gus_state)                ; A = the state again, as the calls promise
        ret

gus_jp_hl:
        jp (hl)

gus_hz:                                 ; A = 50 or 60 (keeps BC, DE, HL)
        ld a,(GUS_HZ60)
        or a
        ld a,50
        ret z
        ld a,60
        ret

gus_ring_reset:
        ld hl,gus_busy
        ld (hl),1
        ld hl,0
        ld (gus_head),hl
        ld (gus_tail),hl
        xor a
        ld (gus_inline),a
        ld (gus_busy),a
        ret

; gus_begin - the session's counters, then H: version 1, the tick rate (20 a frame, for
; the video timing), D, the memory, the gain, flags 0
gus_begin:
        call gus_ring_reset
        xor a
        ld (gus_err),a
        ld (gus_rx_len),a
        ld (gus_sess_status),a
        ld (gus_q_got),a
        ld (gus_m_got),a
        ld (gus_b_got),a
        ld (gus_y_got),a
        ld (gus_e_got),a
        ld (gus_seq),a                  ; H is line 0
        ld hl,(GUS_FRAME_CTR)
        ld (gus_last_status),hl
        ld a,2
        ld (gus_state),a
        ld a,'H'
        call gus_open
        ld de,1
        call gus_item0
        ld a,(gus_vtiming)
        add a,a
        ld hl,gus_h_tick50
        ld e,a
        ld a,(GUS_HZ60)
        or a
        ld a,e
        jr z,.t
        ld hl,gus_h_tick60
.t:     add hl,a
        ld e,(hl)
        inc hl
        ld d,(hl)
        call gus_item0
        ld de,GUS_D_MS
        call gus_item0
        ld de,GUS_MEM_KB
        call gus_item0
        ld de,GUS_GAIN
        call gus_item0
        ld de,0
        call gus_item0
        jp gus_line_end

; the tick rate H declares: 20 a frame, the frame's rate scaled by NextReg $11's clock over
; VGA0's 28 MHz (VGA1-6 run the machine, and its frames, 2-18% fast; HDMI is exact)
gus_h_tick50:   DW 1000, 1020, 1052, 1071, 1107, 1143, 1179, 1000
gus_h_tick60:   DW 1200, 1224, 1263, 1286, 1329, 1371, 1414, 1200

;-----------------------------------------------------------------------------
; the clock
gus_tick:                               ; the frame interrupt: gus_now += 20 (24 bits;
        ld a,(gus_now)                  ; the Z80N's add hl,a sets no carry, so bytewise)
        add a,20
        ld (gus_now),a
        ret nc
        ld hl,gus_now + 1
        inc (hl)
        ret nz
        inc hl
        inc (hl)
        ret

; gus_f - an F line at the clock's time (read in one piece: the interrupt moves it)
gus_f:
        call gus_close_open
        ld a,i
        push af
        di
        ld hl,(gus_now)
        ld (gus_stamp),hl
        ld a,(gus_now + 2)
        ld (gus_stamp + 2),a
        pop af
        jp po,.f
        ei
.f:     ld a,'F'
        jr gus_open_timed

gus_a:
        call gus_close_open
        ld a,'A'
        ; fall through
gus_open_timed:                         ; A = 'F' or 'A': the line, its stamp first
        call gus_open
        ld a,(gus_stamp + 2)
        and 3
        ld b,a
        ld de,(gus_stamp)
        jp gus_item

gus_close_open:                         ; a line still open is closed first
        ld a,(gus_inline)
        or a
        ret z
        jp gus_line_end

;-----------------------------------------------------------------------------
; lines: '#', the type, the sequence character; items of 3 characters; the CRC's two
; characters and LF. Everything goes into the ring a byte at a time (gus_put)

; gus_open - A = the type
gus_open:
        ld (gus_inline),a
        ld c,a
        ld a,'#'
        call gus_put
        ld a,c
        call gus_put
        ld a,(gus_seq)
        ld hl,gus_alpha
        add hl,a
        ld b,(hl)                       ; the sequence character
        ld a,b
        call gus_put
        ld h,high GUS_CRCTAB            ; the CRC, from 0, over the type and it
        ld l,c
        ld a,(hl)
        xor b
        ld l,a
        ld a,(hl)
        ld (gus_crc),a
        xor a
        ld (gus_nitems),a
        ret

; gus_item0 - DE, an item under 65,536 (B = 0)
gus_item0:
        ld b,0
        ; fall through
; gus_item - B = bits 17-16, DE = bits 15-0: its three characters (keeps nothing)
gus_item:
        ld hl,gus_nitems
        inc (hl)
        ld a,d                          ; bits 17-12: B << 4 | D >> 4
        swapnib
        and 15
        ld c,a
        ld a,b
        swapnib
        and $30
        or c
        call gus_char
        ld a,d                          ; bits 11-6: (D & 15) << 2 | E >> 6
        and 15
        add a,a
        add a,a
        ld c,a
        ld a,e
        rlca
        rlca
        and 3
        or c
        call gus_char
        ld a,e                          ; bits 5-0
        and 63
        ; fall through
; gus_char - A = 0-63: its character into the line and its CRC (keeps BC, DE)
gus_char:
        ld hl,gus_alpha
        add hl,a
        ld a,(hl)
        push af
        ld hl,gus_crc
        xor (hl)
        ld h,high GUS_CRCTAB
        ld l,a
        ld a,(hl)
        ld (gus_crc),a
        pop af
        jp gus_put

; gus_room - A = the items an event needs: if the open line cannot take them all, it ends
; and a line of the same type goes on (a timed one with the same stamp; the hosts here send
; no waits before a line fills). An event never straddles two lines (keeps BC, DE)
gus_room:
        ld hl,gus_nitems
        add a,(hl)
        cp GUS_MAX_ITEMS + 1
        ret c
        ; fall through
gus_continue:
        push bc
        push de
        call gus_line_end
        ld a,(gus_last_type)
        cp 'F'
        jr z,.t
        cp 'A'
        jr z,.t
        call gus_open
        jr .o
.t:     call gus_open_timed
.o:     pop de
        pop bc
        ret

; gus_line_end - the CRC's two characters and LF
gus_line_end:
        ld a,(gus_inline)
        or a
        ret z
        ld (gus_last_type),a
        ld a,(gus_crc)
        rlca
        rlca
        and 3
        ld hl,gus_alpha
        add hl,a
        ld a,(hl)
        call gus_put
        ld a,(gus_crc)
        and 63
        ld hl,gus_alpha
        add hl,a
        ld a,(hl)
        call gus_put
        ld a,10
        call gus_put
        ld a,(gus_seq)
        inc a
        and 63
        ld (gus_seq),a
        xor a
        ld (gus_inline),a
        ret

; gus_put - A = a byte for the UART (keeps BC, DE). Stored before the tail moves past it;
; a full ring loses the byte (counted)
gus_put:
        push de
        push bc
        ld c,a
        ld hl,(gus_tail)
        ld d,h
        ld e,l
        inc de
        ld a,d
        and GUS_MASK_H
        ld d,a                          ; DE = the tail after it
        ld a,(gus_head)
        cp e
        jr nz,.ok
        ld a,(gus_head + 1)
        cp d
        jr nz,.ok
        ld hl,(gus_overflow)            ; full
        inc hl
        ld (gus_overflow),hl
        jr .out
.ok:    push de
        ld de,GUS_RING
        add hl,de
        ld (hl),c                       ; the byte first,
        pop de
        ld (gus_tail),de                ; then the tail
.out:   pop bc
        pop de
        ret

; gus_queued - HL = the bytes waiting in the ring
gus_queued:
        ld hl,(gus_tail)
        ld de,(gus_head)
        or a
        sbc hl,de
        ld a,h
        and GUS_MASK_H
        ld h,a
        ret

;-----------------------------------------------------------------------------
; events (docs/protocol.md, Events): an operation in bits 17-14

gus_note:                               ; op 1: voice, pan, flags 0; sample and volume; rate
        ld a,3
        call gus_room
        ld a,(gus_ev_voice)
        add a,a
        or $40
        ld d,a                          ; bits 15-8: 01 vvvvv p
        ld a,(gus_ev_pan)
        ld c,a
        and 16
        jr z,.p
        inc d                           ; the pan's bit 4 is the item's bit 8
.p:     ld a,c
        and 15
        swapnib
        ld e,a                          ; bits 7-4: the pan's low bits; flags 0
        ld b,0
        call gus_item
        ld hl,(gus_ev_sample)           ; the sample in bits 17-8, the volume in 7-0
        ld a,h
        and 3
        ld b,a
        ld d,l
        ld a,(gus_ev_vol)
        ld e,a
        call gus_item
        ld a,(gus_ev_rate + 2)
        and 3
        ld b,a
        ld de,(gus_ev_rate)
        jp gus_item

gus_stop:                               ; op 2: A = voice
        call gus_room1
        add a,a
        or $80
        ld d,a
        ld e,0
        jp gus_item0

gus_vol:                                ; op 3: A = voice, C = volume
        call gus_room1
        add a,a
        or $C0
        ld d,a
        ld e,c
        jp gus_item0

gus_rate:                               ; op 4: A = voice; the rate in gus_ev_rate
        push af
        ld a,2
        call gus_room
        pop af
        add a,a
        ld d,a
        ld e,0
        ld b,1
        call gus_item
        ld a,(gus_ev_rate + 2)
        and 3
        ld b,a
        ld de,(gus_ev_rate)
        jp gus_item

gus_pan:                                ; op 5: A = voice, C = pan
        call gus_room1
        add a,a
        or $40
        ld d,a
        ld e,c
        ld b,1
        jp gus_item

gus_cut:                                ; op 6: DE = the ticks back it reaches
        call gus_room1
        ld a,d
        and $3F
        or $80
        ld d,a
        ld b,1
        jp gus_item

gus_alloff:                             ; op 7
        call gus_room1
        ld de,$C000
        ld b,1
        jp gus_item

gus_wait:                               ; op 0: DE = ticks
        call gus_room1
        ld a,d
        and $3F
        ld d,a
        jp gus_item0

gus_room1:                              ; room for a one-item event (keeps A, BC, DE)
        push af
        ld a,1
        call gus_room
        pop af
        ret

; gus_w - a W line: HL = the bytes, B = how many (1-174), gus_arg = the address
gus_w:
        push hl
        push bc
        call gus_close_open
        ld a,'W'
        call gus_open
        ld hl,gus_arg
        call gus_num36
        pop bc
        push bc
        ld e,b
        ld d,0
        call gus_item0
        pop bc
        pop hl
.g:     ld d,(hl)                       ; three bytes a group (the last padded with zeros)
        inc hl
        dec b
        ld e,0
        ld c,0
        jr z,.go
        ld e,(hl)
        inc hl
        dec b
        jr z,.go
        ld c,(hl)
        inc hl
        dec b
.go:    push hl
        push bc
        ld a,d                          ; bits 23-18
        rrca
        rrca
        and 63
        call gus_char
        ld a,d                          ; 17-12: (D & 3) << 4 | E >> 4
        and 3
        swapnib
        ld b,a
        ld a,e
        swapnib
        and 15
        or b
        call gus_char
        pop bc
        push bc
        ld a,e                          ; 11-6: (E & 15) << 2 | C >> 6
        and 15
        add a,a
        add a,a
        ld b,a
        ld a,c
        rlca
        rlca
        and 3
        or b
        call gus_char
        pop bc
        ld a,c                          ; 5-0
        and 63
        push bc
        call gus_char
        pop bc
        pop hl
        ld a,b
        or a
        jr nz,.g
        jp gus_line_end

; gus_num36 - HL = a 32-bit number (under 2^24): two items, bits 35-18 and 17-0
gus_num36:
        push hl
        inc hl
        inc hl
        ld a,(hl)                       ; bits 23-16
        rrca
        rrca
        and $3F
        ld e,a
        ld d,0
        call gus_item0                  ; the high item: bits 23-18
        pop hl
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld a,(hl)
        and 3
        ld b,a
        jp gus_item                     ; the low item: bits 17-0

;-----------------------------------------------------------------------------
; gus_pump - the ring into the Tx FIFO, never waiting. AF, BC, DE, HL only; no calls
gus_pump:
        ld hl,gus_busy
        ld a,(hl)
        or a
        ret nz
        inc (hl)
.next:  ld hl,(gus_head)
        ld de,(gus_tail)
        ld a,l
        cp e
        jr nz,.have
        ld a,h
        cp d
        jr z,.done
.have:  ld bc,PI_TX
        in a,(c)
        bit PI_TX_FULL,a
        jr nz,.done
        push hl
        ld de,GUS_RING
        add hl,de
        ld a,(hl)
        pop hl
        out (c),a
        inc hl
        ld a,h
        and GUS_MASK_H
        ld h,a
        ld (gus_head),hl
        ld hl,gus_bytes
        inc (hl)
        jr nz,.next
        inc hl
        inc (hl)
        jr nz,.next
        inc hl
        inc (hl)
        jr .next
.done:  xor a
        ld (gus_busy),a
        ret

; gus_drain - the ring out, waiting (at most 2 s). CF set: it did not empty
gus_drain:
        ld hl,(GUS_FRAME_CTR)
        ld (gus_t0),hl
.d:     call gus_pump
        call gus_rx_all
        call gus_queued
        ld a,h
        or l
        ret z
        ld de,100
        call gus_timeout
        jr nc,.d
        ret

; gus_timeout - DE = frames: CF set when that many have passed since gus_t0
gus_timeout:
        ld hl,(GUS_FRAME_CTR)
        push de
        ld de,(gus_t0)
        or a
        sbc hl,de
        pop de
        or a
        sbc hl,de
        ccf
        ret

;-----------------------------------------------------------------------------
; what the card says

; gus_poll - the Rx FIFO (64 bytes at most a turn), then the watchdog. A = the state
gus_poll:
        ld a,(gus_state)
        cp 2
        ret nz
        call gus_rx_all
        ld a,(gus_state)
        cp 2
        ret nz
        call gus_watchdog
        ld a,(gus_state)
        ret

gus_rx_all:
        ld d,64                         ; (an emulator may say "ready" for ever)
.b:     ld bc,PI_TX
        in a,(c)
        rrca
        ret nc
        ld b,high PI_RX
        in a,(c)
        push de
        call gus_rx_byte
        pop de
        dec d
        jr nz,.b
        ret

gus_rx_byte:
        ld c,a
        ld hl,(gus_rx_win + 1)          ; the last four bytes: "SUP>"?
        ld (gus_rx_win),hl
        ld a,(gus_rx_win + 3)
        ld (gus_rx_win + 2),a
        ld a,c
        ld (gus_rx_win + 3),a
        ld hl,(gus_rx_win)
        ld de,"US"
        or a
        sbc hl,de
        jr nz,.line
        ld hl,(gus_rx_win + 2)
        ld de,">P"
        or a
        sbc hl,de
        jr nz,.line
        ld a,1
        ld (gus_sup_seen),a
        ld a,(gus_state)
        cp 2
        ret nz                          ; only while running is it the card gone
        ld a,4
        jp gus_trip
.line:  ld a,c
        cp 13
        ret z
        cp 10
        jr z,.eol
        ld a,(gus_rx_len)
        cp 63
        ret nc
        ld hl,gus_rx_buf
        add hl,a
        ld (hl),c
        inc a
        ld (gus_rx_len),a
        ret
.eol:   ld a,(gus_rx_len)
        ld b,a
        xor a
        ld (gus_rx_len),a
        ld a,b
        cp 4
        ret c
        ld a,(gus_rx_buf)
        cp '%'
        ret nz
        ; fall through
; gus_pline - the card's line in gus_rx_buf, B characters: '%', the type, items, the CRC
gus_pline:
        ld a,b
        sub 4                           ; the items' characters
        ld c,0
.div:   cp 3                            ; C = items (the characters a multiple of 3)
        jr c,.rem
        sub 3
        inc c
        jr .div
.rem:   or a
        jr nz,.bad
        ld a,c
        cp 10
        jr nc,.bad
        ld (gus_pn),a
        ld hl,gus_rx_buf + 1            ; the CRC over the type and the items
        ld a,b
        sub 3
        ld d,a                          ; characters
        xor a
.crc:   xor (hl)
        push hl
        ld h,high GUS_CRCTAB
        ld l,a
        ld a,(hl)
        pop hl
        inc hl
        dec d
        jr nz,.crc
        ld e,a                          ; E = the CRC
        ld a,(hl)                       ; its two characters
        call gus_unalpha
        jr c,.bad
        ld d,a
        inc hl
        ld a,(hl)
        call gus_unalpha
        jr c,.bad
        ld c,a
        ld a,e
        rlca
        rlca
        and 3
        cp d
        jr nz,.bad
        ld a,e
        and 63
        cp c
        jr nz,.bad
        ld hl,gus_rx_buf + 2            ; the items, decoded into gus_pit (3 bytes each)
        ld de,gus_pit
        ld a,(gus_pn)
        or a
        jr z,.go
        ld b,a
.it:    push bc
        call gus_unitem
        pop bc
        jr c,.bad
        djnz .it
.go:    ld hl,(GUS_FRAME_CTR)           ; a good line: the watchdog's clock
        ld (gus_last_status),hl
        ld hl,gus_sess_status
        inc (hl)
        jr nz,.nosat
        dec (hl)
.nosat: ld a,(gus_rx_buf + 1)
        ld c,a
        ld a,(gus_pn)
        ld b,a
        ld a,c
        cp 'T'
        jr z,.t
        cp 'Q'
        jr z,.q
        cp 'M'
        jr z,.m
        cp 'B'
        jr z,.b
        cp 'Y'
        jr z,.y
        cp 'E'
        jr z,.e
        ret
.bad:   ld hl,(gus_pbad)
        inc hl
        ld (gus_pbad),hl
        ret
.t:     ld a,b
        cp 9
        ret nz
        ld de,gus_tv                    ; nine words: each item's low 16 bits
        call gus_words
        ld hl,(gus_tn)
        inc hl
        ld (gus_tn),hl
        ret
.q:     ld a,b
        cp 6
        ret nz
        ld hl,gus_pit                   ; the items as they are (gus_qbit reads them)
        ld de,gus_q
        ld bc,18
        ldir
        ld a,1
        ld (gus_q_got),a
        ret
.m:     ld a,b
        cp 6
        ret nz
        ld hl,(gus_pit + 15)            ; the low 16 bits, then the high
        ld (gus_m),hl
        ld hl,(gus_pit + 12)
        ld (gus_m + 2),hl
        ld a,1
        ld (gus_m_got),a
        ret
.b:     ld a,1
        ld (gus_b_got),a
        ret
.y:     ld a,b
        cp 1
        ret nz
        ld hl,(gus_pit)
        ld (gus_y),hl
        ld a,1
        ld (gus_y_got),a
        ret
.e:     ld a,b
        cp 7
        ret nz
        ld de,gus_ev_end
        call gus_words
        ld a,1
        ld (gus_e_got),a
        ret

gus_words:                              ; B items from gus_pit: their low 16 bits to DE
        ld hl,gus_pit
.w:     ld a,(hl)
        ld (de),a
        inc hl
        inc de
        ld a,(hl)
        ld (de),a
        inc hl
        inc hl
        inc de
        djnz .w
        ret

; gus_unitem - HL = 3 characters: the item into DE (3 bytes: low, middle, high); HL and DE
; move on. CF set: not the alphabet
gus_unitem:
        ld a,(hl)
        call gus_unalpha
        ret c
        ld b,a                          ; v0 (bits 17-12)
        inc hl
        ld a,(hl)
        call gus_unalpha
        ret c
        ld c,a                          ; v1 (bits 11-6)
        inc hl
        ld a,(hl)
        call gus_unalpha
        ret c
        inc hl
        push hl
        ld l,a                          ; v2
        ld a,c                          ; low: (v1 & 3) << 6 | v2
        rrca
        rrca
        and $C0
        or l
        ld (de),a
        inc de
        ld a,b                          ; middle: (v0 & 15) << 4 | v1 >> 2
        swapnib
        and $F0
        ld l,a
        ld a,c
        rrca
        rrca
        and 15
        or l
        ld (de),a
        inc de
        ld a,b                          ; high: v0 >> 4
        swapnib
        and 3
        ld (de),a
        inc de
        pop hl
        or a
        ret

; gus_unalpha - A = a character: A = its value, CF set if it is not in the alphabet
gus_unalpha:
        cp 'A'
        jr c,.lo
        cp 'Z' + 1
        jr nc,.hi
        sub 'A'
        ret
.hi:    cp '_'
        jr z,.us
        cp 'a'
        jr c,.bad
        cp 'z' + 1
        jr nc,.bad
        sub 'a' - 26
        ret
.us:    ld a,63
        or a
        ret
.lo:    cp '-'
        jr z,.dash
        cp '0'
        jr c,.bad
        cp '9' + 1
        jr nc,.bad
        add a,52 - '0'
        or a
        ret
.dash:  ld a,62
        or a
        ret
.bad:   scf
        ret

; gus_qbit - A = i (0-63): NZ if the last %Q's bit i is set (the block first + i not good)
gus_qbit:
        ld hl,gus_q + 6                 ; the bitmap's four items, 18 bits each
.i:     cp 18
        jr c,.b
        sub 18
        inc hl
        inc hl
        inc hl
        jr .i
.b:     ld c,a                          ; bit c of the item at HL
        srl a
        srl a
        srl a
        add hl,a
        ld a,c
        and 7
        ld b,a
        ld a,(hl)
        inc b
.s:     dec b
        jr z,.t
        rrca
        jr .s
.t:     and 1
        ret

; gus_watchdog - no '%' line for 1.5 s (3 s until the session's second) means it has gone
gus_watchdog:
        call gus_hz
        ld e,a
        ld d,0
        ld a,(gus_sess_status)
        cp 2
        jr c,.grace
        srl e
        call gus_hz
        add a,e
        ld e,a
        jr .lim
.grace: ld l,e
        ld h,0
        add hl,hl
        add hl,de
        ex de,hl
.lim:   ld hl,(GUS_FRAME_CTR)
        push de
        ld de,(gus_last_status)
        or a
        sbc hl,de
        pop de
        or a
        sbc hl,de
        ret c
        ld a,3
        ; fall through
gus_trip:                               ; A = the error: the card has gone
        ld (gus_err),a
        ld hl,gus_trips
        inc (hl)
        nextreg PI_NR_I2S,0
        call gus_ring_reset
        ld a,4
        jp gus_set_state

;-----------------------------------------------------------------------------
; the blocking calls

; gus_wait_flag - HL = a flag byte (the call has zeroed it), DE = frames: CF set if it is
; still 0 by then, or the card went
gus_wait_flag:
        push hl
        ld hl,(GUS_FRAME_CTR)
        ld (gus_t0),hl
        pop hl
.w:     push hl
        push de
        call gus_pump
        call gus_rx_all
        pop de
        pop hl
        ld a,(gus_state)
        cp 4
        scf
        ret z
        ld a,(hl)
        or a
        ret nz                          ; (CF clear)
        push hl
        call gus_timeout
        pop hl
        jr nc,.w
        ret

; gus_upload - see the header
gus_upload:
        ld (gus_up_first),hl
        ld (gus_up_n),de
        ld hl,gus_named
        ld de,gus_named + 1
        ld bc,63
        ld (hl),$FF                     ; every block to go, the first time
        ldir
        xor a
        ld (gus_up_pass),a
        call gus_drain
.pass:  call GUS_OPEN
        ld a,1
        ret c
        call gus_stream
        push af
        call GUS_CLOSE
        pop af
        ret c                           ; (A: 1 read, 4 the card went)
        call gus_ask
        ret c
        ld hl,(gus_named_n)
        ld a,h
        or l
        ret z                           ; every block good (CF clear)
        ld a,(gus_up_pass)
        cp 3
        jr nc,.left
        inc a
        ld (gus_up_pass),a
        jr .pass
.left:  ld a,3
        scf
        ret

; gus_stream - the file's lines, those of named blocks (all of them the first time)
gus_stream:
        xor a
        ld (gus_lbuf_n),a
.chunk: ld de,GUS_RDBUF
        ld bc,GUS_RDBUF_SIZE
        call GUS_READ
        ld a,1
        ret c
        ld a,b
        or c
        ret z                           ; the end (CF clear)
        ld hl,GUS_RDBUF
.byte:  ld a,(hl)
        inc hl
        push hl
        push bc
        call gus_lbyte
        pop bc
        pop hl
        ld a,(gus_state)
        cp 4
        ld a,4
        scf
        ret z
        dec bc
        ld a,b
        or c
        jr nz,.byte
        jr .chunk

; gus_lbyte - A = the file's next byte: into the line buffer; a whole line is sent if its
; block is named
gus_lbyte:
        ld c,a
        ld a,(gus_lbuf_n)
        cp 255
        jr nc,.full
        ld hl,gus_lbuf
        add hl,a
        ld (hl),c
        inc a
        ld (gus_lbuf_n),a
.full:  ld a,c
        cp 10
        ret nz
        ld a,(gus_lbuf_n)
        ld b,a
        xor a
        ld (gus_lbuf_n),a
        ld a,b
        cp 8
        ret c
        ld hl,gus_lbuf + 3              ; the block: the first item, less the first block
        ld de,gus_it
        push bc
        call gus_unitem
        pop bc
        ret c
        ld hl,(gus_it)
        ld de,(gus_up_first)
        or a
        sbc hl,de
        ret c
        ld de,GUS_NAMED_MAX
        or a
        sbc hl,de
        ret nc
        add hl,de                       ; HL = the block's place
        ld a,l                          ; its bit in gus_named
        and 7
        ld c,a
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        ld de,gus_named
        add hl,de
        ld a,(hl)
        inc c
.s:     dec c
        jr z,.t
        rrca
        jr .s
.t:     and 1
        ret z                           ; not named: not sent
        ld a,(gus_up_pass)
        or a
        jr z,.send
        ld hl,(gus_up_lines)
        inc hl
        ld (gus_up_lines),hl
.send:  ld hl,gus_lbuf
.snd:   ld a,(hl)
        inc hl
        push hl
        push bc
        call gus_tx
        pop bc
        pop hl
        ret c
        djnz .snd
        ret

; gus_tx - A = a byte, straight to the UART (the ring is empty), taking what comes back
; meanwhile. CF set: the Tx stayed full for 2 s
gus_tx:
        push af
        ld hl,(GUS_FRAME_CTR)
        ld (gus_t0),hl
.w:     ld bc,PI_TX
        in a,(c)
        rrca
        jr nc,.nrx
        ld b,high PI_RX
        in a,(c)
        call gus_rx_byte
        jr .w
.nrx:   ld bc,PI_TX
        in a,(c)
        bit PI_TX_FULL,a
        jr z,.go
        ld de,100
        call gus_timeout
        jr nc,.w
        pop af
        ret
.go:    pop af
        out (c),a
        ld hl,gus_up_sent
        inc (hl)
        jr nz,.ok
        inc hl
        inc (hl)
        jr nz,.ok
        inc hl
        inc (hl)
.ok:    or a
        ret

; gus_ask - Q in 64s over every block of the upload: gus_named and gus_named_n
gus_ask:
        ld hl,gus_named
        ld de,gus_named + 1
        ld bc,63
        ld (hl),0
        ldir
        ld hl,0
        ld (gus_named_n),hl
        ld (gus_ask_at),hl              ; the place from the first block
.q:     ld hl,(gus_up_n)
        ld de,(gus_ask_at)
        or a
        sbc hl,de
        ret z                           ; all asked (CF clear)
        ld de,64
        or a
        sbc hl,de
        add hl,de
        jr c,.n
        ld hl,64
.n:     ld a,l
        ld (gus_ask_n),a
        xor a
        ld (gus_q_got),a
        ld a,'Q'
        call gus_open
        ld hl,(gus_up_first)
        ld de,(gus_ask_at)
        add hl,de
        ex de,hl
        call gus_item0
        ld a,(gus_ask_n)
        ld e,a
        ld d,0
        call gus_item0
        call gus_line_end
        ld hl,gus_q_got
        ld de,50
        call gus_wait_flag
        ld a,2
        ret c
        ld a,(gus_ask_n)                ; each bit set: named
        ld b,a
        ld c,0
.bit:   push bc
        ld a,c
        call gus_qbit
        pop bc
        jr z,.nb
        ld hl,(gus_named_n)
        inc hl
        ld (gus_named_n),hl
        ld hl,(gus_ask_at)              ; the place: ask_at + c
        ld a,c
        add hl,a
        ld a,l
        and 7
        ld e,a
        srl h
        rr l
        srl h
        rr l
        srl h
        rr l
        push de
        ld de,gus_named
        add hl,de
        pop de
        ld a,1
        inc e
.sh:    dec e
        jr z,.set
        rlca
        jr .sh
.set:   or (hl)
        ld (hl),a
.nb:    inc c
        djnz .bit
        ld hl,(gus_ask_at)
        ld a,(gus_ask_n)
        add hl,a
        ld (gus_ask_at),hl
        jp .q

; gus_memcrc - M for gus_arg's address and length; the answer in gus_m
gus_memcrc:
        xor a
        ld (gus_m_got),a
        call gus_close_open
        ld a,'M'
        call gus_open
        ld hl,gus_arg
        call gus_num36
        ld hl,gus_arg + 4
        call gus_num36
        call gus_line_end
        ld hl,gus_m_got
        ld de,50
        jp gus_wait_flag

; gus_ping - DE = a token: Y, and its answer
gus_ping:
        push de
        xor a
        ld (gus_y_got),a
        call gus_close_open
        ld a,'Y'
        call gus_open
        pop de
        push de
        call gus_item0
        call gus_line_end
        ld hl,gus_y_got
        ld de,50
        call gus_wait_flag
        pop de
        ret c
        ld hl,(gus_y)
        or a
        sbc hl,de
        ret z
        scf
        ret

; gus_install - see the header. The bytes go straight to the UART, as gus_upload's do; the
; answer is matched on the way (the file's own echo cannot make "GN42": $((6*7)) in it)
gus_install:
        call GUS_OPEN
        ld a,1
        ret c
        xor a
        ld (gus_gn),a
.chunk: ld de,GUS_RDBUF
        ld bc,GUS_RDBUF_SIZE
        call GUS_READ
        jr c,.rderr
        ld a,b
        or c
        jr z,.sent
        ld hl,GUS_RDBUF
.b:     ld a,(hl)
        inc hl
        push hl
        push bc
        call gus_itx
        pop bc
        pop hl
        jr c,.rderr
        dec bc
        ld a,b
        or c
        jr nz,.b
        jr .chunk
.rderr: call GUS_CLOSE
        ld a,1
        scf
        ret
.sent:  call GUS_CLOSE
        ld hl,(GUS_FRAME_CTR)           ; GN42 (or GE42) within 30 s
        ld (gus_t0),hl
.w:     ld a,(gus_gn)
        cp 4
        jr z,.done
        ld bc,PI_TX
        in a,(c)
        rrca
        jr nc,.t
        ld b,high PI_RX
        in a,(c)
        call gus_gn_byte
        jr .w
.t:     ld de,1500
        call gus_timeout
        jr nc,.w
        ld a,2
        ret
.done:  ld a,(gus_gn_ok)
        or a
        ld a,2
        scf
        ret z
        or a
        ret

gus_itx:                                ; A = a byte for SUP, the answer watched meanwhile
        push af
        ld hl,(GUS_FRAME_CTR)
        ld (gus_t0),hl
.w:     ld bc,PI_TX
        in a,(c)
        rrca
        jr nc,.nrx
        ld b,high PI_RX
        in a,(c)
        call gus_gn_byte
        jr .w
.nrx:   ld bc,PI_TX
        in a,(c)
        bit PI_TX_FULL,a
        jr z,.go
        ld de,100
        call gus_timeout
        jr nc,.w
        pop af
        ret
.go:    pop af
        out (c),a
        or a
        ret

; gus_gn_byte - A = a byte from SUP: "GN42" or "GE42" found? (gus_gn counts the matched
; characters to 4; gus_gn_ok 1 for GN42)
gus_gn_byte:
        ld c,a
        ld a,(gus_gn)
        cp 4
        ret z
        or a
        jr nz,.n1
        ld a,c
        cp 'G'
        ret nz
        ld a,1
        ld (gus_gn),a
        ret
.n1:    cp 1
        jr nz,.n2
        ld a,c
        cp 'N'
        jr z,.ok1
        cp 'E'
        jr nz,.reset
        xor a
        ld (gus_gn_ok),a
        jr .adv
.ok1:   ld a,1
        ld (gus_gn_ok),a
.adv:   ld hl,gus_gn
        inc (hl)
        ret
.n2:    cp 2
        jr nz,.n3
        ld a,c
        cp '4'
        jr z,.adv
        jr .reset
.n3:    ld a,c
        cp '2'
        jr z,.adv
.reset: xor a
        ld (gus_gn),a
        ld a,c
        cp 'G'
        ret nz
        ld a,1                          ; a new start: this G
        ld (gus_gn),a
        ret

; gus_speed - see the header
gus_speed:
        ld (gus_sp_code),a
        ld a,c
        ld (gus_sp_flags),a
        ld a,i
        push af
        di
        ld bc,$243B                     ; an emulator? (NextReg $00 = 8)
        xor a
        out (c),a
        inc b
        in a,(c)
        ld c,a
        pop af
        jp po,.di
        ei
.di:    ld a,c
        cp 8
        ld a,9
        scf
        ret z
        xor a
        ld (gus_b_got),a
        call gus_close_open
        ld a,'S'
        call gus_open
        ld a,(gus_sp_code)
        ld e,a
        ld d,0
        call gus_item0
        ld a,(gus_sp_flags)
        ld e,a
        ld d,0
        call gus_item0
        call gus_line_end
        ld hl,gus_b_got
        ld de,25
        call gus_wait_flag
        ret c
.empty: ld bc,PI_TX                     ; the Tx empties at the old speed
        in a,(c)
        bit 4,a
        jr z,.empty
        ld a,(gus_sp_code)
        ld c,a
        ld a,(gus_sp_flags)
        call gus_set_speed
        ld a,10                         ; a lone LF: the end of any half line
        call gus_tx
        ld a,(gus_sp_code)
        add a,$A0
        ld e,a
        ld d,$0F                        ; the token $0FA0 + code (4000 + code)
        call gus_ping
        ret nc                          ; switched
        ld c,1                          ; not answered: back to 115,200
        xor a
        call gus_set_speed
        ld a,10
        call gus_tx
        scf
        ret

; gus_set_speed - C = the code, A = flags: the prescaler (for the video timing) and the
; flow control, port $163B bit 5
gus_set_speed:
        and 1
        ld a,$18                        ; 8N1
        jr z,.fc
        ld a,$38                        ; 8N1, hardware flow control
.fc:    ld (gus_sp_frame),a
        ld a,c
        dec a
        jr nz,.fast
        call pi_uart                    ; 115,200: piuart.inc's own
        jr .frame
.fast:  dec a                           ; the table's row: (code - 2) x 8 + timing
        add a,a
        add a,a
        add a,a
        ld hl,gus_vtiming
        add a,(hl)
        ld hl,gus_presc
        add hl,a
        ld a,(hl)
        ld bc,PI_SELECT
        ld d,a
        ld a,%01010000                  ; the Pi's UART; the prescaler's top bits 0
        out (c),a
        ld bc,PI_RX
        ld a,d
        and $7F
        out (c),a                       ; its low 7 bits
        ld a,$80                        ; its middle 7 bits: 0
        out (c),a
.frame: ld bc,$163B
        ld a,(gus_sp_frame)
        out (c),a
        ret

; round(the system clock / the speed), for NextReg $11's timings 0-7: 1, 1.5 and 2 Mbit
gus_presc:      DB 28, 29, 29, 30, 31, 32, 33, 27
                DB 19, 19, 20, 20, 21, 21, 22, 18
                DB 14, 14, 15, 15, 16, 16, 17, 14

; gus_end - E, %E, SUP>; $A2 off. A = 0 (not running: nothing done, A = the state)
gus_end:
        ld a,(gus_state)
        cp 2
        ret nz
        call gus_close_open
        xor a
        ld (gus_e_got),a
        ld a,'E'
        call gus_open
        call gus_line_end
        xor a
        ld (gus_sup_seen),a
        ld a,3
        call gus_set_state
        ld hl,gus_e_got                 ; %E, then SUP> (it may have come with it)
        ld de,150
        call gus_wait_flag
        ld a,(gus_sup_seen)
        or a
        jr nz,.ok
        ld hl,pi_t_prompt
        ld de,PI_PER_S * 2
        call pi_expect
        jr nc,.ok
        ld de,PI_PER_S * 2
        call pi_ready
.ok:    nextreg PI_NR_I2S,0
        call gus_ring_reset
        xor a
        jp gus_set_state

;-----------------------------------------------------------------------------
gus_alpha:      DB "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
gus_s_cmd:      DB "$ND/nextpi-gus", 10, 0
gus_s_gus1:     DB "GUS1"

gus_vars:
gus_state       DB 0
gus_err         DB 0
gus_trips       DB 0
gus_vtiming     DB 0
gus_seq         DB 0
gus_crc         DB 0
gus_inline      DB 0                    ; the open line's type, or 0
gus_last_type   DB 0
gus_nitems      DB 0
gus_stamp       DS 3                    ; the timed line's stamp
gus_now         DS 3                    ; the Next's clock, ticks
gus_head        DW 0
gus_tail        DW 0
gus_busy        DB 0
gus_overflow    DW 0
gus_bytes       DS 4                    ; bytes the pump sent
gus_ui_hook     DW 0
gus_t0          DW 0
gus_rx_len      DB 0
gus_rx_win      DS 4
gus_rx_buf      DS 64
gus_pn          DB 0                    ; the card's line's items
gus_pit         DS 30                   ; and their values, 3 bytes each
gus_last_status DW 0
gus_sess_status DB 0
gus_sup_seen    DB 0
gus_pbad        DW 0                    ; the card's lines that failed their CRC
gus_tn          DW 0                    ; %T lines
gus_tv          DS 18                   ; %T: good, bad, gaps, late, steps, lead+131072, voices, blocks, refused
gus_q_got       DB 0
gus_q           DS 18                   ; %Q's items: first, count, the bitmap in four
gus_m_got       DB 0
gus_m           DS 4                    ; %M: the CRC-32
gus_b_got       DB 0
gus_y_got       DB 0
gus_y           DW 0
gus_e_got       DB 0
gus_ev_end      DS 14                   ; %E: good, bad, gaps, late, steps, blocks, CPU (tenths)
gus_it          DS 3
gus_arg         DS 8                    ; gus_memcrc's address and length; gus_w's address
gus_ev_voice    DB 0                    ; gus_note's fields
gus_ev_pan      DB 0
gus_ev_sample   DW 0
gus_ev_vol      DB 0
gus_ev_rate     DS 3
gus_up_first    DW 0
gus_up_n        DW 0
gus_up_pass     DB 0
gus_up_sent     DS 3                    ; bytes the uploads sent
gus_up_lines    DW 0                    ; lines the second passes sent
gus_named       DS 64                   ; bit i: block first + i named
gus_named_n     DW 0
gus_ask_at      DW 0
gus_ask_n       DB 0
gus_lbuf_n      DB 0
gus_lbuf        DS 256
gus_sp_code     DB 0
gus_sp_flags    DB 0
gus_sp_frame    DB 0
gus_gn          DB 0                    ; gus_install's answer: characters matched
gus_gn_ok       DB 0                    ; 1: GN42, 0: GE42
gus_vars_end:
