;-----------------------------------------------------------------------------
; card.inc - the Pi's GUS-like card (plan-pi-gus.md; nextpi-gus, GPL-2.0-or-later), in PAGE 11,
; run at $E000 through MMU7.
;
; aw.asm includes this with sjasmplus's MMU 7 mapping page 11 into slot 7, so it assembles at
; $E000 and lands in page 11 - bank 5's upper half, which nothing else in the program uses (see
; NR_PAL_SRC_MMU: MMU3 maps other pages INTO that slot, it never writes page 11's contents). The
; resident block reaches it through card_call, which borrows MMU7 and puts back what it found,
; exactly as the interrupt borrows MMU7 for a sample page.
;
; What is here:
;   - nextpi-gus's Next side, copied into src/inc/gus/ by tools/mkgusdata.py: gus.inc (GUS1),
;     piuart.inc (the Pi UART), gusprobe.inc (its probe line);
;   - the boot (card_boot): find the Pi and the card, install it if missing, upload every
;     sound (GUSALL.GUS), check the card's CRC of its memory; any failure leaves the card off
;     and the Z80 path exactly as it was. With the card on, the interrupt's mixer is off
;     (snd_off) and the copper plays silence: the card is the sound;
;   - the interrupt's part (card_isr): the clock, an F line every frame (the heartbeat, with
;     the frame's effects and the music's cuts), the music's rows up to L ahead in A lines,
;     the UART both ways, and the watchdog: a card lost mid-game hands back to the Z80 path at
;     once;
;   - what the main code calls: card_snd (op_playSound), card_mus (op_playMusic, after the
;     Z80 path has done its part), card_stop (st_stop: op_updateMemList(0) and a part's
;     setup), card_load (sv_load's end).
;
; THE MUSIC. The Z80 player keeps running at the frame boundary exactly as it does without the
; card - music_clock, music_tick, the 0xF4 marker the scripts wait on, the positions a save
; keeps, the voices - with the mixer off, so it is heard nowhere; it is what the game's timing
; follows, and what a lost card hands back to. The card's notes come from a SENDER in the
; interrupt: it walks the same module on the same clock (a row every delay * 60 / 7050 ms from
; the Z80 clock's start), up to L ahead, as A lines stamped with each row's exact time, so a
; row is heard on time however long the frame that owns it runs. It follows the reference,
; sfxplayer.cpp, where the Z80 path does not: a row naming an instrument sets the channel's
; volume, the order list's end stops every channel, and a retime keeps the pending row's time
; (the re-armed timer's). The machine's calls tell it what the reference's player was told:
;   a module start   the old module's rows from its start time cut, the new one's instruments'
;                    first four samples zeroed (W, prepareInstruments), its rows from there;
;   a retime         the rows sent after the pending one cut and sent again on the new period;
;   a stop           the rows from its time cut; the notes sounding carry on (SfxPlayer::stop);
;   st_stop          the same, and every voice off (op_updateMemList(0): _ply->stop, stopAll).
;
; THE ONE-PRODUCER RULE (gus.inc's header). While the card is on, only the interrupt writes the
; ring: the main code's routines post to it through variables the interrupt reads, written with
; interrupts held off. Before the card is on, only the boot writes it, and the interrupt's card
; work is gated off (card_on).
;-----------------------------------------------------------------------------

CARD_ORG        EQU $E000               ; CARD_PAGE (11) is aw.asm's: its MMU directive needs it first
; the fast link, tried after the handoff: gus_speed's code (1 115,200, 2 1 Mbit, 3 1.5 Mbit),
; with RTS/CTS. An emulator never switches (gus_speed says 9) and a switch that fails falls
; back to 115,200 inside a second, so trying it costs little; the KS3 decides (plan A5)
CARD_SPEED      EQU 2
CARD_PROBE_WAIT EQU PI_PER_S / 2        ; half a second for SUP>: what a Next with no Pi loses
CARD_L          EQU 300                 ; the music is sent this many ticks (ms at 50 Hz) ahead
CARD_ROWS       EQU 4                   ; rows the sender sends at most a frame
CARD_HIST       EQU 8                   ; rows it remembers (a retime rewinds among them)
; THE BORDER SAYS WHAT THE CARD DID, for the KS3 (plan A5), where nothing reads card_abi: blue
; from SUP's answer while the card is found, installed and uploaded (so it also times the upload),
; black once it is on, MAGENTA if it failed after the Pi answered or was lost mid-game - so the
; Z80 path is playing although a Pi is there. No Pi: the border is never touched. (Red is the
; game's own fault border, show_err.)
CARD_BORDER_UP  EQU 1
CARD_BORDER_BAD EQU 3

; card_st, the boot's verdict
CS_NONE         EQU 0                   ; not tried (a build with no upload: GUS_BLOCKS 0)
CS_NOPI         EQU 1                   ; no SUP> in half a second: no Pi, or NextPi not up
CS_NOCARD       EQU 2                   ; SUP, but no card, and GUSINST.TXT did not install one
CS_NOSTART      EQU 3                   ; gus_start failed (no GUS1)
CS_UPLOAD       EQU 4                   ; gus_upload failed (card_uperr says how)
CS_NOM          EQU 5                   ; no %M answer
CS_BADM         EQU 6                   ; %M is not the build's CRC
CS_ON           EQU 7                   ; the card is on
CS_LOST         EQU 8                   ; it was on, and went (the watchdog, or SUP>)

; gus.inc's host EQUs (its header)
GUS_RING        EQU card_ring
GUS_RING_SIZE   EQU 1024
GUS_RDBUF       EQU card_rdbuf
GUS_RDBUF_SIZE  EQU 256
GUS_CRCTAB      EQU card_crctab
GUS_FRAME_CTR   EQU ticks                   ; the interrupt adds 1 a frame, at LINE_A
GUS_HZ60        EQU card_hz60
GUS_D_MS        EQU 20
GUS_GAIN        EQU 128

        ORG CARD_ORG
card_crctab:    DS 256                  ; first: gus.inc wants it 256-aligned, and $E000 is, with no padding
; the entry points: card_call is handed these
CARD_ISR:       jp card_isr             ; the interrupt, both lines
CARD_BOOT:      jp card_boot            ; cop_start's end
CARD_SND:       jp card_snd             ; aw_play_sound's first instruction
CARD_MUS:       jp card_mus             ; aw_play_music's, once the Z80 path is done
CARD_STOP:      jp card_stop            ; st_stop
CARD_LOAD:      jp card_load            ; sv_load's end

; THE CARD'S STATE, where tools/cspect/awsnd.cs reads it (AWSND_CARD: page 11's physical
; address plus the offset, so it is read whatever MMU7 holds at the time)
        EXPORT card_abi
card_abi:
card_st:        DB CS_NONE              ; +0 the boot's verdict
card_inst:      DB 0                    ; +1 1: GUSINST.TXT installed the card
card_uperr:     DB 0                    ; +2 gus_upload's error (0: every block good)
card_speed:     DB 0                    ; +3 0 not tried, 1 switched, 2 not, 9 an emulator
card_upframes:  DW 0                    ; +4 frames the upload took
card_isrs:      DW 0                    ; +6 frames the interrupt's card work ran
card_passes:    DB 0                    ; +8 the upload's second passes
card_err:       DB 0                    ; +9 gus_err when the card was lost
card_m:         DS 4                    ; +10 %M as the card said it
card_bytes:     DS 4                    ; +14 bytes the pump has sent
card_tn:        DW 0                    ; +18 %T lines seen
card_tv:        DS 18                   ; +20 the last %T: good, bad, gaps, late, steps, lead, voices, blocks, refused
card_on_ticks:  DW 0                    ; +38 ticks, and
card_on_now:    DS 3                    ; +40 the card's clock, when it came on: the two clocks' offset
card_nfx:       DW 0                    ; +43 effects sent (notes and stops)
card_nrows:     DW 0                    ; +45 music rows sent
card_ncuts:     DB 0                    ; +47 cuts sent
card_abi_end:

;-----------------------------------------------------------------------------
; card_isr - the interrupt, after the mixer's part: the frame's work at LINE_A (cop_half is 1
; after it), the UART both ways at both lines. Every register may change: the interrupt saved
; them all, the alternate set too
card_isr:
        ld a,(cop_half)                 ; 1: LINE_A's interrupt just ran (LINE_B armed)
        or a
        jr z,.pump
        ld hl,(card_isrs)
        inc hl
        ld (card_isrs),hl
        call gus_tick                   ; the Next's clock, 20 ticks a frame
        call gus_f                      ; the heartbeat: an F line every frame, with
        call card_ops                   ; the music's cut and all-off,
        call card_effects               ; and the frame's effects
        ld a,(card_pend_zero)
        or a
        call nz,card_zero               ; W: a new module's instruments' first samples
        call card_send                  ; A: the music's rows due up to L ahead
        call gus_line_end
.pump:  call gus_pump
        call gus_poll                   ; A = the state: 4 when the card has gone
        cp 4
        jr z,card_lost
        ld a,(cop_half)
        or a
        ret z
        ld hl,(gus_bytes)               ; the numbers the probe reads, once a frame
        ld (card_bytes),hl
        ld hl,(gus_bytes + 2)
        ld (card_bytes + 2),hl
        ld hl,(gus_tn)
        ld (card_tn),hl
        ld hl,gus_tv
        ld de,card_tv
        ld bc,18
        ldir
        ret

; card_lost - the watchdog tripped, or SUP> came back: the Z80 path takes over at once. The
; mixer plays the Z80 voices, which the Z80 player and op_playSound kept current all along
card_lost:
        ld a,CARD_BORDER_BAD
        out ($FE),a
        xor a
        ld (card_on),a
        ld (snd_off),a
        ld a,(gus_err)
        ld (card_err),a
        ld a,CS_LOST
        ld (card_st),a
        ret

; card_ops - the music's posted cut (the earliest time asked for, as ticks back from the F
; line's) and all-off, after a retime has had its say
card_ops:
        ld a,(card_pend_rt)
        or a
        call nz,card_retime
        ld a,(card_pend_cut)
        or a
        jr z,.ao
        xor a
        ld (card_pend_cut),a
        ld hl,(gus_now)                 ; back = now - the cut's time, 0 to 16,383
        ld de,(card_cut_t)
        or a
        sbc hl,de
        ld a,(gus_now + 2)
        ld b,a
        ld a,(card_cut_t + 2)
        ld c,a
        ld a,b
        sbc a,c
        jr c,.none                      ; (after now: cannot be; nothing is sent ahead of it)
        jr nz,.far
        ld a,h
        cp $40
        jr c,.back
.far:   ld hl,$3FFF
        jr .back
.none:  ld hl,0
.back:  ex de,hl
        call gus_cut
        ld hl,card_ncuts
        inc (hl)
.ao:    ld a,(card_pend_ao)
        or a
        ret z
        xor a
        ld (card_pend_ao),a
        jp gus_alloff

; card_effects - the mailbox: a slot a channel, filled by card_snd, emptied here
card_effects:
        ld hl,card_mb
        ld b,0                          ; B = the channel, the card's voice
.slot:  ld a,(hl)
        or a
        jr z,.next
        ld (hl),0
        push hl
        push bc
        dec a
        jr nz,.stop
        inc hl
        ld a,(hl)                       ; the sample: the sound's resource number
        ld (gus_ev_sample),a
        xor a
        ld (gus_ev_sample + 1),a
        ld (gus_ev_rate + 2),a
        inc hl
        ld a,(hl)
        ld (gus_ev_vol),a
        inc hl
        ld a,(hl)
        ld (gus_ev_rate),a
        inc hl
        ld a,(hl)
        ld (gus_ev_rate + 1),a
        ld a,b
        ld (gus_ev_voice),a
        call gus_note
        jr .sent
.stop:  ld a,b
        call gus_stop
.sent:  ld hl,(card_nfx)
        inc hl
        ld (card_nfx),hl
        pop bc
        pop hl
.next:  ld de,5
        add hl,de
        inc b
        ld a,b
        cp 4
        jr nz,.slot
        ret

; card_zero - W: four zero bytes at each instrument's first sample, as prepareInstruments does
; to every instrument it finds loaded (sfxplayer.cpp:89)
card_zero:
        xor a
        ld (card_pend_zero),a
        ld hl,card_instr
        ld b,15
.i:     ld a,(hl)                       ; the instrument's resource
        inc hl
        inc hl
        or a
        jr z,.n
        push hl
        push bc
        call card_resident              ; HL = the resource's three address bytes; Z: not loaded
        jr z,.skip
        ld e,(hl)
        inc hl
        ld d,(hl)
        inc hl
        ld a,(hl)
        ld (gus_arg),de
        ld (gus_arg + 2),a
        or d
        or e
        jr z,.skip                      ; address 0: not a sound (the table's own)
        xor a
        ld (gus_arg + 3),a
        ld hl,card_zeros
        ld b,4
        call gus_w
.skip:  pop bc
        pop hl
.n:     djnz .i
        ret

; card_resident - A = a resource: NZ if it is loaded (res_page), and HL = its entry in card_addr
card_resident:
        ld e,a
        ld d,0
        ld hl,res_page
        add hl,de
        ld a,(hl)
        ld h,d
        ld l,e
        add hl,hl
        add hl,de                       ; HL = the resource x 3
        ld de,card_addr
        add hl,de
        or a
        ret

;-----------------------------------------------------------------------------
; THE SENDER. card_sn_* is the next row: its order and position, its time; card_hist the
; rows sent, for a retime to rewind among.

card_send:
        ld a,(card_sn_on)
        or a
        ret z
        ld bc,$243B                     ; MMU2 and MMU3 are borrowed for the module's pattern
        ld a,NR_MMU2                    ; and put back as found: READ (this interrupt may have
        out (c),a                       ; landed in a draw, or in page 10's code at MMU2)
        inc b
        in a,(c)
        ld (card_mmu2),a
        dec b
        ld a,NR_MMU3
        out (c),a
        inc b
        in a,(c)
        ld (card_mmu3),a
        ld a,CARD_ROWS
        ld (card_rows_left),a
.row:   ld hl,(gus_now)                 ; due: the row's time at most now + L
        ld de,CARD_L
        add hl,de
        ld (card_tmp),hl
        ld a,(gus_now + 2)
        adc a,0
        ld (card_tmp + 2),a
        ld hl,card_tmp
        ld de,card_sn_time
        call card_lt                    ; CF: now + L is before the row: not yet
        jr c,.out
        call card_row
        ld a,(card_sn_on)
        or a
        jr z,.out
        ld hl,card_rows_left
        dec (hl)
        jr nz,.row
.out:   ld a,(card_mmu2)
        nextreg NR_MMU2,a
        ld a,(card_mmu3)
        nextreg NR_MMU3,a
        ret

; card_row - the row at card_sn_*: an A line at its time, and the sender on past it
card_row:
        call card_hist_push
        ld a,(card_sn_order)            ; the block: $C0 + order_table[order] * 1024 + pos
        ld hl,card_orders
        add hl,a
        ld a,(hl)
        add a,a
        add a,a
        ld h,a
        ld l,0
        ld de,(card_sn_pos)
        add hl,de
        ld de,$C0
        add hl,de                       ; HL = the row's offset in the module
        ld a,h                          ; its two pages at MMU2 and MMU3, as music_tick does
        rlca
        rlca
        rlca
        and 7
        ld e,a
        ld a,(card_sn_page)
        add a,e
        nextreg NR_MMU2,a
        inc a
        nextreg NR_MMU3,a
        ld a,h
        and $1F
        add a,$40
        ld h,a
        ld (card_rp),hl                 ; the row's four channels, at $4000 up
        xor a
        ld (card_aopen),a               ; its A line opens with its first event (card_ev)
        ld hl,(card_nrows)
        inc hl
        ld (card_nrows),hl
        xor a
.ch:    ld (card_ch),a
        call card_chan
        ld a,(card_ch)
        inc a
        cp 4
        jr nz,.ch
        ld hl,(card_sn_pos)             ; on: sixteen bytes a row, 1,024 a block
        ld de,16
        add hl,de
        ld (card_sn_pos),hl
        ld a,h
        cp 4
        jr c,.time
        ld hl,0
        ld (card_sn_pos),hl
        ld a,(card_sn_order)
        inc a
        ld (card_sn_order),a
        ld hl,card_sn_norder
        cp (hl)
        jr nz,.time
        call card_ev
        call gus_alloff                 ; the order list's end: stopAll, at this row's time
        xor a
        ld (card_sn_on),a
.time:  ld a,(card_aopen)
        or a
        call nz,gus_line_end            ; (a row that does nothing sends nothing: the card
                                        ; takes a timed line with no events for a bad one)
        ld hl,(card_sn_time)            ; the next row's time
        ld de,(card_sn_period)
        add hl,de
        ld (card_sn_time),hl
        ld a,(card_sn_time + 2)
        adc a,0
        ld (card_sn_time + 2),a
        ret

; card_chan - A = a channel of the row at card_rp: handlePattern, sfxplayer.cpp
card_chan:
        add a,a
        add a,a
        ld hl,(card_rp)
        add hl,a
        ld d,(hl)                       ; note_1, big-endian
        inc hl
        ld e,(hl)
        inc hl
        ld b,(hl)                       ; note_2, kept in BC throughout
        inc hl
        ld c,(hl)
        ld (card_n1),de
        xor a
        ld (card_smp),a
        ld a,d                          ; 0xFFFD: the VM's marker - the Z80 player's, not the card's
        cp $FF
        jr nz,.inst
        ld a,e
        cp $FD
        ret z
.inst:  ld a,b                          ; an instrument named: its sample and volume, if loaded
        and $F0
        jr z,.play
        rrca
        rrca
        rrca
        rrca
        dec a
        add a,a
        ld hl,card_instr
        add hl,a
        ld a,(hl)                       ; its resource
        or a
        jr z,.play                      ; an empty slot
        ld (card_smp),a
        inc hl
        ld a,(hl)
        ld (card_vol),a
        ld a,(card_smp)
        call card_resident              ; (DE, HL): only a loaded sound has ins->data
        jr nz,.fx
        xor a
        ld (card_smp),a
        jr .play
.fx:    ld a,b                          ; effects 5 and 6 move the volume, clamped to 0-63
        and $0F
        cp 5
        jr nz,.n5
        ld a,(card_vol)
        add a,c
        jr c,.max
        cp $40
        jr c,.sv
.max:   ld a,$3F
        jr .sv
.n5:    cp 6
        jr nz,.vset
        ld a,(card_vol)
        sub c
        jr nc,.sv
        xor a
.sv:    ld (card_vol),a
.vset:  call card_ev
        ld a,(card_vol)                 ; setChannelVolume, whatever the row goes on to do
        add a,a
        add a,a
        ld c,a
        ld a,(card_ch)
        call gus_vol
.play:  ld de,(card_n1)
        ld a,d
        or e
        ret z                           ; note_1 zero: nothing more
        ld a,d
        cp $FF
        jr nz,.note
        ld a,e
        cp $FE
        jr nz,.note
        call card_ev
        ld a,(card_ch)                  ; 0xFFFE stops the channel
        jp gus_stop
.note:  ld a,(card_smp)
        or a
        ret z                           ; no sample: nothing plays
        call card_rate                  ; 7159092 / (note_1 x 2) Hz
        call card_ev
        ld a,(card_ch)
        ld (gus_ev_voice),a
        ld a,(card_smp)
        ld (gus_ev_sample),a
        xor a
        ld (gus_ev_sample + 1),a
        ld a,(card_vol)
        add a,a
        add a,a
        ld (gus_ev_vol),a
        jp gus_note

; card_ev - the row's A line, opened at its time by its first event. Keeps BC and DE
card_ev:
        ld a,(card_aopen)
        or a
        ret nz
        inc a
        ld (card_aopen),a
        push bc
        push de
        ld hl,(card_sn_time)
        ld (gus_stamp),hl
        ld a,(card_sn_time + 2)
        ld (gus_stamp + 2),a
        call gus_a
        pop de
        pop bc
        ret

; card_rate - DE = the period (note_1): gus_ev_rate = 3,579,546 / DE, the reference's
; 7159092 / (note_1 * 2) (sfxplayer.cpp:198). 24 bits by 16, restoring, a bit a turn
card_rate:
        ld b,d
        ld c,e                          ; BC = the divisor
        ld hl,0                         ; the remainder
        ld de,$9E9A                     ; 3,579,546 = $369E9A: the dividend, becoming the quotient
        ld a,$36
        ld (card_div),a
        ld a,24
.bit:   ex af,af'                       ; (the interrupt saved the alternate set)
        sla e
        rl d
        ld a,(card_div)
        rla
        ld (card_div),a
        adc hl,hl                       ; under $2000: a period is under $1000
        or a
        sbc hl,bc
        jr nc,.one
        add hl,bc
        jr .next
.one:   inc e
.next:  ex af,af'
        dec a
        jr nz,.bit
        ld (gus_ev_rate),de
        ld a,(card_div)
        ld (gus_ev_rate + 2),a
        ret

; card_hist_push - the row about to be sent (card_sn_*) onto the history; the oldest goes
card_hist_push:
        ld a,(card_hn)
        cp CARD_HIST
        jr c,.room
        ld hl,card_hist + 6
        ld de,card_hist
        ld bc,(CARD_HIST - 1) * 6
        ldir
        ld a,CARD_HIST - 1
        ld (card_hn),a
.room:  ld c,a
        add a,a
        add a,c
        add a,a                         ; x 6
        ld hl,card_hist
        add hl,a
        ex de,hl
        ld hl,card_sn_time
        ld bc,3
        ldir
        ld a,(card_sn_order)
        ld (de),a
        inc de
        ld hl,card_sn_pos
        ldi
        ldi
        ld hl,card_hn
        inc (hl)
        ret

; card_retime - the period changed at card_rt_r (card_rt_p). The reference re-arms its timer:
; the pending row - the first due after the retime - keeps its time, and the rows after it
; come at the new period. The interrupt posted the retime one frame ago (card_rt_r is the
; clock then, the clock moves only here), and rows are 100 ms and more apart, so at most one
; row falls between it and now.
card_retime:
        xor a
        ld (card_pend_rt),a
        ld hl,(card_rt_p)
        ld (card_sn_period),hl
        ld a,(card_hn)                  ; the pending row: the first sent after card_rt_r
        or a
        ret z
        ld b,a
        ld c,0
        ld hl,card_hist
.find:  push hl
        push bc
        ld de,card_rt_r
        ex de,hl
        call card_lt                    ; CF: R before the row
        pop bc
        pop hl
        jr c,.found
        ld de,6
        add hl,de
        inc c
        djnz .find
        ret                             ; none sent: the pending row is the next, unchanged
.found: ld (card_rt_at),hl
        ld a,c
        ld (card_rt_i),a
        ld de,gus_now                   ; the pending row, at or after now?
        call card_lt                    ; CF: before now - it stays, sent
        jr c,.kept
        ld hl,(card_rt_at)              ; it is dropped by a cut at now, and sent again as it was
        ld a,(card_rt_i)
        jr .rewind
.kept:  ld hl,(card_rt_at)              ; its time + the new period is the next row's
        ld de,card_sn_time
        ld bc,3
        ldir
        ld hl,(card_sn_period)
        ld de,(card_sn_time)
        add hl,de
        ld (card_sn_time),hl
        ld a,(card_sn_time + 2)
        adc a,0
        ld (card_sn_time + 2),a
        ld a,(card_rt_i)                ; and if it was sent already, it goes again
        inc a
        ld hl,card_hn
        cp (hl)
        ret nc                          ; not sent: the sender's next row is it
        ld hl,(card_rt_at)
        ld de,6
        add hl,de
        push hl
        push af
        call .cut
        pop af
        pop hl
        ld (card_hn),a                  ; the history back to before it
        inc hl
        inc hl
        inc hl
        jr .pos                         ; (its time is card_sn_time's, just set)
.rewind:                                ; HL = entry A: from it, at its own time
        ld (card_hn),a
        push hl
        call .cut
        pop hl
        ld de,card_sn_time
        ld bc,3
        ldir
.pos:   ld a,(hl)
        ld (card_sn_order),a
        inc hl
        ld de,card_sn_pos
        ldi
        ldi
        ld a,1
        ld (card_sn_on),a
        ret
.cut:   ld hl,gus_now                   ; a cut at now: everything sent ahead from here
        jp card_cut_at

; card_lt - HL and DE point at 24-bit times. CF set: (HL) is before (DE) (wrap-safe: their
; difference's sign). Changes A, C, HL, DE
card_lt:
        ld a,(de)
        ld c,a
        ld a,(hl)
        sub c
        inc hl
        inc de
        ld a,(de)
        ld c,a
        ld a,(hl)
        sbc a,c
        inc hl
        inc de
        ld a,(de)
        ld c,a
        ld a,(hl)
        sbc a,c
        rla
        ret

; card_cut_at - HL = a time: the next F line cuts the music sent from it (the earliest of the
; times asked for). Interrupts off
card_cut_at:
        ld a,(card_pend_cut)
        or a
        jr z,.set
        push hl
        ld de,card_cut_t
        call card_lt                    ; CF: this one is earlier
        pop hl
        ret nc
.set:   ld de,card_cut_t
        ld bc,3
        ldir
        ld a,1
        ld (card_pend_cut),a
        ret

; card_cut_after - HL = a time: the music sent for AFTER it is cut. What is due at it plays: the
; reference's timer fired it before the op (a stop, a new module, stopAll). Interrupts off
card_cut_after:
        ld de,card_tmp2
        ld bc,3
        ldir
        ld hl,(card_tmp2)
        inc hl
        ld (card_tmp2),hl
        ld a,h
        or l
        jr nz,.c
        ld hl,card_tmp2 + 2
        inc (hl)
.c:     ld hl,card_tmp2
        jp card_cut_at

;-----------------------------------------------------------------------------
; THE MAIN CODE'S CALLS, through the resident gates. AF, BC, DE and HL change, nothing else;
; what the interrupt reads is written with interrupts held off, and they go back as found.

; card_snd - op_playSound (snd_playSound, vm.cpp:692), in the reference's order of tests: a
; sound not loaded returns before volume 0 stops the channel. The Z80 path runs on after it.
card_snd:
        ld a,(SND_BLOCK + 0)
        call card_resident
        ret z                           ; not loaded: nothing, as the reference
        ld a,(SND_BLOCK + 3)            ; the channel, masked as the Z80 path does
        and 3
        ld c,a
        add a,a
        add a,a
        add a,c
        ld hl,card_mb
        add hl,a                        ; HL = its slot
        ld a,i
        push af
        di
        ld a,(SND_BLOCK + 2)
        or a
        jr nz,.note
        ld (hl),2                       ; volume 0: stop the channel
        jr card_ei
.note:  cp $40                          ; MIN(volume, 0x3F), x 4
        jr c,.v
        ld a,$3F
.v:     add a,a
        add a,a
        ld (hl),1
        inc hl
        ld c,a
        ld a,(SND_BLOCK + 0)
        ld (hl),a                       ; the sample
        inc hl
        ld (hl),c                       ; the volume
        inc hl
        ex de,hl
        ld a,(SND_BLOCK + 1)            ; frequenceTable[freq], in Hz
        cp 40
        jr c,.f
        ld a,39
.f:     add a,a
        ld hl,card_freq
        add hl,a
        ldi
        ldi
        ; fall through
card_ei:                                ; interrupts back as they were
        pop af
        ret po
        ei
        ret

; card_mus - op_playMusic, after the Z80 path (the resident aw_play_music) has run
card_mus:
        ld a,(MUS_BLOCK + 0)
        or a
        jr z,.zero
        call card_resident
        ret z                           ; not loaded: the Z80 player kept the old module; so does the card
        xor a                           ; the sender stops first: its tables are about to change
        ld (card_sn_on),a
        ld hl,MUS_ORDER_AT              ; the module's tables, the sender's own copy: the Z80 path
        ld de,card_orders               ; rewrites them for the next module, under the sender
        ld bc,$80
        ldir
        ld hl,MUS_INSTR_AT
        ld de,card_instr
        ld bc,30
        ldir
        ld a,i
        push af
        di
        ld hl,(ticks)                   ; t0: the Z80 clock's start (mus_clock_start), in the
        ld de,(mus_last_tick)           ; card's clock: now, less 20 a tick since
        or a
        sbc hl,de
        add hl,hl
        add hl,hl
        ld d,h
        ld e,l
        add hl,hl
        add hl,hl
        add hl,de
        ex de,hl
        ld hl,(gus_now)
        or a
        sbc hl,de
        ld (card_t0),hl
        ld a,(gus_now + 2)
        sbc a,0
        ld (card_t0 + 2),a
        ld hl,card_t0                   ; the old module's rows after then go
        call card_cut_after
        ld hl,card_t0                   ; the first row: t0 + the period (the timer's first call)
        call card_start
        jp card_ei
.zero:  ld hl,(MUS_BLOCK + 1)
        ld a,h
        or l
        jr z,.stop
        call mus_set_period             ; a retime: the Z80's own arithmetic, music_clock then sees it done
        ld a,i
        push af
        di
        ld hl,gus_now
        ld de,card_rt_r
        ld bc,3
        ldir
        ld hl,(mus_period)
        ld (card_rt_p),hl
        ld a,1
        ld (card_pend_rt),a
        jp card_ei
.stop:  ld a,i                          ; a stop: the timer goes; the notes sounding carry on
        push af
        di
        xor a
        ld (card_sn_on),a
        ld (card_pend_rt),a
        ld (card_hn),a
        ld hl,gus_now
        call card_cut_after
        jp card_ei

; card_start - the sender at the Z80 player's module (mus_*), its first row at (HL) + the period.
; Interrupts off
card_start:
        ld de,card_tmp
        ld bc,3
        ldir
        ld a,(mus_page)
        ld (card_sn_page),a
        ld a,(mus_num_order)
        ld (card_sn_norder),a
        ld a,(mus_cur_order)
        ld (card_sn_order),a
        ld hl,(mus_cur_pos)
        ld (card_sn_pos),hl
        ld hl,(mus_period)
        ld (card_sn_period),hl
        ld de,(card_tmp)
        add hl,de
        ld (card_sn_time),hl
        ld a,(card_tmp + 2)
        adc a,0
        ld (card_sn_time + 2),a
        xor a
        ld (card_hn),a
        ld (card_pend_rt),a             ; a retime before it is moot
        inc a
        ld (card_pend_zero),a
        ld (card_sn_on),a
        ret

; card_stop - st_stop: op_updateMemList(0) and a part's setup stop the player and every voice
; (_ply->stop, _mix->stopAll). Effects waiting in the mailbox go too.
card_stop:
        ld a,i
        push af
        di
        xor a
        ld (card_sn_on),a
        ld (card_pend_rt),a
        ld (card_hn),a
        ld (card_mb),a
        ld (card_mb + 5),a
        ld (card_mb + 10),a
        ld (card_mb + 15),a
        inc a
        ld (card_pend_ao),a
        ld hl,gus_now
        call card_cut_after
        jp card_ei

; card_load - sv_load's end: the Z80 player is as the save left it; the sender follows it from
; its position, its first row a period from now. The voices restored are the Z80 mixer's:
; the card plays nothing that was sounding (sv_load's aw_setup_part stopped them all).
card_load:
        xor a
        ld (card_sn_on),a
        ld a,(mus_playing)
        or a
        ret z
        ld hl,MUS_ORDER_AT
        ld de,card_orders
        ld bc,$80
        ldir
        ld hl,MUS_INSTR_AT
        ld de,card_instr
        ld bc,30
        ldir
        call mus_set_period
        ld a,i
        push af
        di
        ld hl,gus_now
        call card_start
        jp card_ei

;-----------------------------------------------------------------------------
; card_boot - from cop_start's end, with interrupts on (the upload's limits count ticks) and
; the card's interrupt work off. Blocking: half a second with no Pi; with the card, the upload.
card_boot:
    IF GUS_BLOCKS == 0
        ret                             ; no upload in this build: the card is never tried
    ELSE
        call gus_init
        ld a,$05                        ; 50 or 60 Hz: NextReg $05 bit 2, for H's tick rate
        call nr_read
        and 4
        ld (card_hz60),a
        call pi_uart
        ld de,CARD_PROBE_WAIT
        call pi_ready                   ; ^C, LF, SUP>
        ld a,CS_NOPI
        jp c,.out
        ld a,CARD_BORDER_UP
        out ($FE),a
        call card_probe                 ; GP42: the card is there
        jr nc,.have
        ld a,1                          ; GA42, or nothing: install it, then look again
        ld (card_installing),a
        call gus_install
        ld a,0
        ld (card_installing),a
        ld a,CS_NOCARD
        jp c,.out
        ld a,1
        ld (card_inst),a
        ld de,PI_PER_S * 2
        call pi_ready
        ld a,CS_NOCARD
        jp c,.out
        call card_probe
        ld a,CS_NOCARD
        jp c,.out
.have:  call gus_start                  ; the handoff: GUS1, NextReg $A2, H
        cp 2
        ld a,CS_NOSTART
        jp nz,.out
    IF CARD_SPEED > 1
        ld a,CARD_SPEED
        ld c,1                          ; RTS/CTS
        call gus_speed
        ld b,1
        jr nc,.sw
        ld b,a                          ; 9: an emulator
        cp 9
        jr z,.sw
        ld b,2                          ; not switched: still 115,200
.sw:    ld a,b
        ld (card_speed),a
    ENDIF
        ld hl,(ticks)
        ld (card_up_t0),hl
        ld hl,0
        ld de,GUS_BLOCKS
        call gus_upload                 ; every sound, from GUSALL.GUS
        push af
        ld a,(gus_up_pass)
        ld (card_passes),a
        ld hl,(ticks)
        ld de,(card_up_t0)
        or a
        sbc hl,de
        ld (card_upframes),hl
        pop af
        jr nc,.m
        ld (card_uperr),a
        ld a,CS_UPLOAD
        jp .end
.m:     ld hl,0                         ; M over the memory the upload fills
        ld (gus_arg),hl
        ld (gus_arg + 2),hl
        ld hl,GUS_LEN_LO
        ld (gus_arg + 4),hl
        ld hl,GUS_LEN_HI
        ld (gus_arg + 6),hl
        call gus_memcrc
        ld a,CS_NOM
        jp c,.end
        ld hl,(gus_m)
        ld (card_m),hl
        ld de,GUS_CRC_LO
        or a
        sbc hl,de
        ld a,CS_BADM
        jp nz,.end
        ld hl,(gus_m + 2)
        ld (card_m + 2),hl
        ld de,GUS_CRC_HI
        or a
        sbc hl,de
        ld a,CS_BADM
        jp nz,.end
        call card_go
        xor a                           ; black: the card is on
        out ($FE),a
        ld a,CS_ON
        jp .out
.end:   ld (card_st),a                  ; the session ends: the Pi as it was, the Z80 path on
        ld a,(card_speed)
        cp 1
        jr nz,.e
        ld a,1                          ; back to 115,200 first: the card answers E at the
        ld c,0                          ; speed it has, and SUP> comes at 115,200
        call gus_speed
.e:     call gus_end
        jr .bad
.out:   ld (card_st),a
        cp CS_NOPI
        ret z                           ; no Pi: the border as it was
        cp CS_ON
        ret z
.bad:   ld a,CARD_BORDER_BAD
        out ($FE),a
        ret
    ENDIF

; card_probe - the probe line at SUP>, and GP42 within a second. CF set: GA42, or nothing
card_probe:
        ld hl,probe_s_line
        call pi_puts
        ld hl,probe_s_gp
        ld de,PI_PER_S
        jp pi_expect

; card_go - the card is on: the interrupt's mixer off, the copper's list silent (both halves
; uploaded: the interrupt uploads nothing from now on), the card's interrupt work on
card_go:
        di
        ld a,1
        ld (snd_off),a
        xor a
        ld (cop_pending),a              ; (nothing of the mixer's is left for dma_mem to send)
        call silence_ring
        ld hl,0
        call cop_upload
        ld hl,COP_HALF
        call cop_upload
        ld hl,(ticks)
        ld (card_on_ticks),hl
        ld hl,(gus_now)
        ld (card_on_now),hl
        ld a,(gus_now + 2)
        ld (card_on_now + 2),a
        ld a,1
        ld (card_on),a
        ei
        ret

;-----------------------------------------------------------------------------
; the host's file calls for gus.inc (gus_upload, gus_install): esxDOS, with the ROM back over
; the bottom 16K for each call (esx_rom, esx_back: vmhost.inc) and interrupts held off across
; it, as every file call here is; put back as they were. The name goes in IX and HL both, as
; load_code does. IX is kept
GUS_OPEN:
        call GUS_CLOSE
        push ix
        ld a,i
        push af
        di
        call esx_rom
        ld hl,card_fn_all
        ld a,(card_installing)
        or a
        jr z,.o
        ld hl,card_fn_inst
.o:     push hl
        pop ix
        ld a,ESX_DRIVE
        ld b,FA_READ
        rst $08
        DB F_OPEN
        jr c,.back
        ld (card_fh),a
        ld a,1
        ld (card_fopen),a               ; (LD keeps the flags)
.back:  call esx_back                   ; keeps F
        jr c,card_esx_fail
        jr card_esx_ok

GUS_READ:                               ; DE = the buffer, BC = the most: BC = bytes read
        push ix
        ld a,i
        push af
        di
        push de
        push bc
        call esx_rom
        pop bc
        pop hl
        push hl
        pop ix
        ld a,(card_fh)
        rst $08
        DB F_READ
        call esx_back                   ; keeps F and BC
        jr c,card_esx_fail
        ; fall through
card_esx_ok:                            ; interrupts as they were, IX back, CF clear
        pop af
        jp po,.di
        ei
.di:    pop ix
        or a
        ret

card_esx_fail:
        pop af
        jp po,.di
        ei
.di:    pop ix
        scf
        ret

GUS_CLOSE:
        ld a,(card_fopen)
        or a
        ret z
        xor a
        ld (card_fopen),a
        push ix
        ld a,i
        push af
        di
        call esx_rom
        ld a,(card_fh)
        rst $08
        DB F_CLOSE
        call esx_back
        jr card_esx_ok

card_fn_all:    DB "GUSALL.GUS", 0
card_fn_inst:   DB "GUSINST.TXT", 0

;-----------------------------------------------------------------------------
        INCLUDE "src/inc/gus/piuart.inc"
        INCLUDE "src/inc/gus/gus.inc"
        INCLUDE "src/inc/gus/gusprobe.inc"

; each resource's first sample in the card's memory, 3 bytes (0: not a sound): build/gusdata.inc
card_addr:
        GUS_ADDR_TABLE
; op_playSound's forty pitches in Hz
card_freq:
        GUS_FREQ_HZ
card_zeros:     DB 0, 0, 0, 0

card_hz60:      DB 0
card_installing: DB 0
card_fopen:     DB 0
card_fh:        DB 0
card_up_t0:     DW 0
; the mailbox: a slot a channel - kind (0 empty, 1 note, 2 stop), sample, volume, rate (2)
card_mb:        DS 4 * 5
; what the main code posts for the interrupt's next F line
card_pend_cut:  DB 0
card_cut_t:     DS 3
card_pend_ao:   DB 0
card_pend_rt:   DB 0
card_rt_r:      DS 3
card_rt_p:      DW 0
card_rt_at:     DW 0
card_rt_i:      DB 0
card_pend_zero: DB 0
; the sender
card_sn_on:     DB 0
card_sn_page:   DB 0
card_sn_norder: DB 0
card_sn_order:  DB 0
card_sn_pos:    DW 0
card_sn_time:   DS 3
card_sn_period: DW 0
card_hn:        DB 0
card_t0:        DS 3
card_tmp:       DS 3
card_tmp2:      DS 3
card_mmu2:      DB 0
card_mmu3:      DB 0
card_rows_left: DB 0
card_rp:        DW 0
card_ch:        DB 0
card_n1:        DW 0
card_smp:       DB 0
card_vol:       DB 0
card_div:       DB 0
card_aopen:     DB 0

card_ring:      DS GUS_RING_SIZE
; THE UPLOAD'S FILE BUFFER IS THE SENDER'S TABLES. gus_upload and gus_install read the SD card
; through it at boot, before the card is on; the sender's tables are written only once it is
; (card_mus, card_load), so the two never meet, and page 11 has no 256 bytes to spare.
card_rdbuf:
card_orders:    DS $80                  ; the module's order table and instruments, as the
card_instr:     DS 30                   ; module started (aw_play_music's layout)
card_hist:      DS CARD_HIST * 6        ; the rows sent: time (3), order, position (2)
                DS GUS_RDBUF_SIZE - ($ - card_rdbuf)
        ASSERT $ - card_rdbuf == GUS_RDBUF_SIZE
card_end:
        DISPLAY "> the card's page 11 at ", /H, CARD_ORG, " ending ", /H, card_end, " (", /D, $10000 - card_end, " bytes free)"
        ASSERT card_end <= $10000
