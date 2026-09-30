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
;     and the Z80 path exactly as it was;
;   - the interrupt's part (card_isr): the clock, a heartbeat F line every frame, the UART both
;     ways, and the watchdog: a card lost mid-game hands back to the Z80 path at once.
;
; THE ONE-PRODUCER RULE (gus.inc's header). While the card is on, only the interrupt writes the
; ring: the main code's routines here post to it through variables the interrupt reads. Before
; the card is on, only the boot writes it, and the interrupt's card work is gated off (card_on).
;-----------------------------------------------------------------------------

CARD_ORG        EQU $E000               ; CARD_PAGE (11) is aw.asm's: its MMU directive needs it first
; the fast link, tried after the handoff: gus_speed's code (1 115,200, 2 1 Mbit, 3 1.5 Mbit),
; with RTS/CTS. An emulator never switches (gus_speed says 9) and a switch that fails falls
; back to 115,200 inside a second, so trying it costs little; the KS3 decides (plan A5)
CARD_SPEED      EQU 2
CARD_PROBE_WAIT EQU PI_PER_S / 2        ; half a second for SUP>: what a Next with no Pi loses

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
GUS_RDBUF_SIZE  EQU 512
GUS_CRCTAB      EQU card_crctab
GUS_FRAME_CTR   EQU ticks                   ; the interrupt adds 1 a frame, at LINE_A
GUS_HZ60        EQU card_hz60
GUS_D_MS        EQU 20
GUS_GAIN        EQU 128

        ORG CARD_ORG
; the entry points, at fixed places: card_call is handed these
CARD_ISR:       jp card_isr             ; $E000 the interrupt, both lines
CARD_BOOT:      jp card_boot            ; $E003 cop_start's end

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
card_abi_end:

;-----------------------------------------------------------------------------
; card_isr - the interrupt, after the mixer's part: gus.inc's frame work at LINE_A (the frame's
; interrupt, cop_half 1 after it), the UART both ways at both lines. Every register may change:
; the interrupt saved them all
card_isr:
        ld a,(cop_half)                 ; 1: LINE_A's interrupt just ran (LINE_B armed)
        or a
        jr z,.pump
        ld hl,(card_isrs)
        inc hl
        ld (card_isrs),hl
        call gus_tick                   ; the Next's clock, 20 ticks a frame
        call gus_f                      ; the heartbeat: an F line every frame
        call gus_line_end
.pump:  call gus_pump
        call gus_poll                   ; A = the state: 4 when the card has gone
        cp 4
        jr z,card_lost
        ld a,(cop_half)
        or a
        ret z
        ; the numbers the probe reads, once a frame
        ld hl,(gus_bytes)
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

; card_lost - the watchdog tripped, or SUP> came back: the Z80 path takes over at once
card_lost:
        xor a
        ld (card_on),a
        ld a,(gus_err)
        ld (card_err),a
        ld a,CS_LOST
        ld (card_st),a
        ret

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
        ld a,CS_ON
        jp .out
.end:   ld (card_st),a                  ; the session ends: the Pi as it was, the Z80 path on
        ld a,(card_speed)
        cp 1
        jr nz,.e
        ld a,1                          ; back to 115,200 first: the card answers E at the
        ld c,0                          ; speed it has, and SUP> comes at 115,200
        call gus_speed
.e:     jp gus_end
.out:   ld (card_st),a
        ret
    ENDIF

; card_probe - the probe line at SUP>, and GP42 within a second. CF set: GA42, or nothing
card_probe:
        ld hl,probe_s_line
        call pi_puts
        ld hl,probe_s_gp
        ld de,PI_PER_S
        jp pi_expect

; card_go - the card is on: the interrupt's card work starts
card_go:
        ld a,1
        ld (card_on),a
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

card_hz60:      DB 0
card_installing: DB 0
card_fopen:     DB 0
card_fh:        DB 0
card_up_t0:     DW 0

        ALIGN 256
card_crctab:    DS 256
card_ring:      DS GUS_RING_SIZE
card_rdbuf:     DS GUS_RDBUF_SIZE
card_end:
        DISPLAY "> the card's page 11 at ", /H, CARD_ORG, " ending ", /H, card_end, " (", /D, $10000 - card_end, " bytes free)"
        ASSERT card_end <= $10000
