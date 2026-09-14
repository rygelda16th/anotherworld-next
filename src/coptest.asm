;-----------------------------------------------------------------------------
; COPPER SOUND - can the copper drive the DAC once a scanline, fed twice a frame?
;
; The game streams its mix to the DAC through the zxnDMA, at 21,875 Hz. Driving the DAC from the
; copper instead - one MOVE to NextReg $2D (DACs A and D) on every raster line, 312 a frame, so
; 15,600 Hz - would mix 29% fewer samples and leave the DMA free for page copies. David chose to
; try it on 2026-09-14. This harness proves the mechanism before the game goes near it.
;
; THE LIST is 312 WAIT/MOVE pairs - line L, then MOVE $2D - and 400 NOOPs to fill the copper's
; 1,024 instructions, run in LOOP mode (%10): after line 311 the NOOPs take a fraction of a line and
; the list wraps to WAIT 0. Nothing depends on where the vertical blank falls. ZEsarUX runs the copper
; at 28 MHz, about 1,800 steps a scanline (tbblue.c, tbblue_copper_handle_next_opcode).
;
; THE FEED is two line interrupts a frame, at 248 and at 92, with the ULA interrupt off. Each mixes
; 156 samples and uploads them over the half of the list the beam has just played:
;
;   at line 248, lines   0..155     at line 92, lines 156..311
;
; so everything written is at least 64 lines ahead of the beam when it is written, and nothing is
; overwritten before it has been played. The 64 lines are the latency, about 4 ms.
;
; THE SIGNAL is a triangle, period 64 samples: every step is +8 or -8. A dropped, repeated or late
; sample breaks that, so the checker (tools/checkcop.py) can count glitches in the emulator's own
; audio output rather than trusting anyone's ears.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

NR_TURBO        EQU $07
NR_PERIPH3      EQU $08                 ; bit 3: enable the 8-bit DACs
NR_LINE_HI      EQU $1E                 ; the active video line, read
NR_LINE_LO      EQU $1F
NR_LINEINT_CTL  EQU $22                 ; bit 2 ULA interrupt off, bit 1 line interrupt on, bit 0 MSB
NR_LINEINT_LSB  EQU $23
NR_COP_DATA     EQU $60
NR_COP_LO       EQU $61                 ; write index, low byte
NR_COP_HI       EQU $62                 ; %cc000iii: control bits and the index's high bits
NR_DAC_AD       EQU $2D
DMA_PORT        EQU $6B
COP_LOOP        EQU %10000000           ; start, and loop the list from its start

LINES           EQU 312
HALF            EQU 156
LINE_A          EQU 248                 ; feeds lines 0..155
LINE_B          EQU 92                  ; feeds lines 156..311

VEC_TABLE       EQU $BC00
VEC_FILL        EQU $BD
VEC_TRAMP       EQU (VEC_FILL << 8) | VEC_FILL

        ORG $8000
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3

        ; the DACs on, whatever else $08 holds
        ld      bc, $243B
        ld      a, NR_PERIPH3
        out     (c), a
        ld      b, $25
        in      a, (c)
        or      %00001000
        nextreg NR_PERIPH3, a

        ; the list: WAIT L,0 / MOVE $2D,128 for every line
        ld      hl, cop_buf
        ld      de, 0                   ; DE = the line
.build:
        ld      a, d
        or      $80                     ; %1hhhhhhv with h = 0: the line's MSB in bit 0
        ld      (hl), a
        inc     hl
        ld      (hl), e
        inc     hl
        ld      (hl), NR_DAC_AD
        inc     hl
        ld      (hl), 128
        inc     hl
        inc     de
        ld      a, e
        cp      LINES & $FF
        jr      nz, .build
        ld      a, d
        cp      LINES >> 8
        jr      nz, .build

        ; stop the copper, index 0, and upload the whole list and its NOOP padding
        nextreg NR_COP_HI, 0
        nextreg NR_COP_LO, 0
        ld      bc, $243B
        ld      a, NR_COP_DATA
        out     (c), a
        ld      b, $25
        ld      hl, cop_buf
        ld      de, LINES * 4
.up:    ld      a, (hl)
        out     (c), a
        inc     hl
        dec     de
        ld      a, d
        or      e
        jr      nz, .up
        ld      de, 2048 - LINES * 4
.pad:   xor     a
        out     (c), a
        dec     de
        ld      a, d
        or      e
        jr      nz, .pad
        ; and run it, looping
        nextreg NR_COP_LO, 0
        nextreg NR_COP_HI, COP_LOOP

        ; IM 2
        ld      hl, VEC_TABLE
        ld      (hl), VEC_FILL
        ld      de, VEC_TABLE + 1
        ld      bc, 256
        ldir
        ld      hl, VEC_TRAMP
        ld      (hl), $C3
        inc     hl
        ld      (hl), isr & $FF
        inc     hl
        ld      (hl), isr >> 8
        ld      a, VEC_TABLE >> 8
        ld      i, a
        im      2

        ; the first line interrupt, and the ULA's off
        xor     a
        ld      (half), a
        nextreg NR_LINEINT_LSB, LINE_A & $FF
        nextreg NR_LINEINT_CTL, %00000110 | (LINE_A >> 8)
        ei

        ld      a, $5A
        ld      (ready), a
.idle:  jr      .idle

;-----------------------------------------------------------------------------
isr:
        push    af
        push    bc
        push    de
        push    hl

        ; where the beam really is, for the checker
        ld      bc, $243B
        ld      a, NR_LINE_LO
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      (last_line), a

        ld      a, (half)
        or      a
        jr      nz, .second
        ; at LINE_A: lines 0..155, then arm LINE_B
        ld      hl, 0
        ld      (reg_start), hl
        nextreg NR_LINEINT_LSB, LINE_B & $FF
        nextreg NR_LINEINT_CTL, %00000110 | (LINE_B >> 8)
        ld      a, 1
        ld      (half), a
        ld      hl, (ticks)             ; one tick a frame, at the first half
        inc     hl
        ld      (ticks), hl
        jr      .feed
.second:
        ld      hl, HALF
        ld      (reg_start), hl
        nextreg NR_LINEINT_LSB, LINE_A & $FF
        nextreg NR_LINEINT_CTL, %00000110 | (LINE_A >> 8)
        xor     a
        ld      (half), a
.feed:
        ; the next 156 samples of the triangle, into the value bytes of those lines
        ld      hl, (reg_start)
        add     hl, hl
        add     hl, hl
        ld      de, cop_buf + 3
        add     hl, de                  ; HL = the first line's value byte
        ld      b, HALF
        ld      a, (tri)
        ld      c, a
        ld      a, (tri_dir)
        ld      e, a                    ; E = +8 or -8
.sample:
        ld      (hl), c
        inc     hl
        inc     hl
        inc     hl
        inc     hl
        ld      a, c
        add     a, e
        ld      c, a
        cp      248
        jr      nz, .not_top
        ld      e, -8
.not_top:
        or      a
        jr      nz, .next
        ld      e, 8
.next:
        djnz    .sample
        ld      a, c
        ld      (tri), a
        ld      a, e
        ld      (tri_dir), a

        ; upload those 624 bytes over the lines the beam has played - BY THE DMA. A CPU loop costs
        ; about 51 T a byte, 64K T a frame, which would eat most of what mixing fewer samples saves.
        ; In continuous mode the DMA finishes the block before the CPU runs its next instruction.
        ld      hl, (reg_start)
        add     hl, hl
        add     hl, hl                  ; the byte index
        ld      a, l
        nextreg NR_COP_LO, a
        ld      a, h
        or      COP_LOOP                ; the same control bits: only the index moves
        nextreg NR_COP_HI, a
        ld      de, cop_buf
        add     hl, de
        ld      (cop_dma_addr), hl
        ld      bc, $243B
        ld      a, NR_COP_DATA          ; the DMA writes $253B, so $243B must name the copper data
        out     (c), a
        ld      hl, cop_dma
        ld      bc, ((cop_dma_end - cop_dma) << 8) | DMA_PORT
        otir
        ld      hl, (n_feed)
        inc     hl
        ld      (n_feed), hl

        pop     hl
        pop     de
        pop     bc
        pop     af
        ei
        reti

        EXPORT ready
ready:      db 0
        EXPORT ticks
ticks:      dw 0
        EXPORT n_feed
n_feed:     dw 0
        EXPORT last_line
last_line:  db 0
half:       db 0
reg_start:  dw 0
tri:        db 0
tri_dir:    db 8
cop_buf:    ds LINES * 4

; memory -> I/O $253B, continuous, no prescalar, stop at the end of the block
cop_dma:
        db      $83                     ; DISABLE
        db      $7D                     ; WR0: A -> B, address and length follow
cop_dma_addr:
        dw      0                       ; patched: the region's first byte
        dw      HALF * 4
        db      $54, $02                ; WR1: port A memory, incrementing, cycle length 2
        db      $68, $22, 0             ; WR2: port B I/O, fixed, cycle length 2, prescalar 0
        db      $AD                     ; WR4: continuous, port B address follows
        dw      $253B
        db      $82                     ; WR5: stop at end of block
        db      $CF                     ; LOAD
        db      $87                     ; ENABLE
cop_dma_end:

        DISPLAY "> coptest ends at ", /H, $
        ASSERT $ < VEC_TABLE

        SAVENEX OPEN "build/coptest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
