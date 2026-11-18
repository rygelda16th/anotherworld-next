;-----------------------------------------------------------------------------
; COPPER SOUND ON THE KS3 - why does src/coptest.asm beep once and stop?
;
; With COP_LOOP %10 the copper played its list once and stopped, on the KS3 and in CSpect 4.5.1.0.
; With %11 (restart at raster 0,0) CSpect 4.5.1.0 plays on, but the KS3 still beeps once and stops.
; This asks the machine, one key at a time, with what it knows on the ULA screen:
;
;   key 1  as coptest: the interrupt feeds each half by the DMA, index by NextReg $61 then $62
;   key 2  the same feed by the CPU (OUT to $253B), not the DMA
;   key 3  the DMA again, index by $62 first, then $61
;   key 4  no feed at all: the list is filled with the triangle once, and the copper just runs it
;
; Each key stops the copper, rebuilds and uploads the whole list by the CPU, and starts it with %11.
; A steady tone in 4 and none in 1 says the feed breaks the copper; nothing in 4 says the copper
; itself does not run on. The screen, one number a line:
;
;   1  the mode            2  interrupts so far       3  feeds so far
;   4  the line the last interrupt read (low byte)     5  the highest raster line seen (311 at 50 Hz,
;                                                         261 at 60 Hz)
;-----------------------------------------------------------------------------
        DEVICE ZXSPECTRUMNEXT

NR_TURBO        EQU $07
NR_PERIPH3      EQU $08
NR_LINE_HI      EQU $1E
NR_LINE_LO      EQU $1F
NR_LINEINT_CTL  EQU $22
NR_LINEINT_LSB  EQU $23
NR_COP_DATA     EQU $60
NR_COP_LO       EQU $61
NR_COP_HI       EQU $62
NR_DAC_AD       EQU $2D
DMA_PORT        EQU $6B
COP_RUN         EQU %11000000

LINES           EQU 312
HALF            EQU 156
LINE_A          EQU 248
LINE_B          EQU 92

VEC_TABLE       EQU $BC00
VEC_FILL        EQU $BD
VEC_TRAMP       EQU (VEC_FILL << 8) | VEC_FILL

        ORG $8000
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3
        ld      bc, $243B
        ld      a, NR_PERIPH3
        out     (c), a
        ld      b, $25
        in      a, (c)
        or      %00001000
        nextreg NR_PERIPH3, a

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

        call    cls
        ld      a, 1
        call    set_mode
        ld      a, $5A
        ld      (ready), a
        ei

main:
        di
        call    line_now                ; HL = the raster line
        ei
        ld      de, (maxline)
        or      a
        push    hl
        sbc     hl, de
        pop     hl
        jr      c, .keys
        jr      z, .keys
        ld      (maxline), hl
.keys:
        ld      bc, $F7FE               ; 1 2 3 4 5
        in      a, (c)
        cpl
        and     $0F
        jr      z, .show
        ld      b, 0
.bit:   inc     b
        rrca
        jr      nc, .bit
        ld      a, (mode)
        cp      b
        jr      z, .show
        ld      a, b
        di
        call    set_mode
        ei
.show:
        xor     a
        ld      (s_row), a
        ld      hl, mode
        call    row
        ld      hl, ticks
        call    row
        ld      hl, n_feed
        call    row
        ld      hl, last_line
        call    row
        ld      hl, maxline
        call    row
        jr      main

row:    xor     a
        ld      (s_col), a
        call    put5
        ld      hl, s_row
        inc     (hl)
        ret

; HL = the raster line now. Interrupts off: the ISR moves $243B.
line_now:
        ld      bc, $243B
        ld      a, NR_LINE_HI
        out     (c), a
        inc     b
        in      h, (c)
        dec     b
        ld      a, NR_LINE_LO
        out     (c), a
        inc     b
        in      l, (c)
        ld      a, h
        and     1
        ld      h, a
        ret

; set_mode: A = 1-4, interrupts off. Stop the copper, rebuild the list, upload it all by the CPU,
; start it with %11, and arm the first line interrupt.
set_mode:
        ld      (mode), a
        nextreg NR_COP_HI, 0
        nextreg NR_COP_LO, 0
        ld      hl, cop_buf
        ld      de, 0                   ; DE = the line
        xor     a
        ld      (tri), a
        ld      a, 8
        ld      (tri_dir), a
.build:
        ld      a, d
        or      $80
        ld      (hl), a
        inc     hl
        ld      (hl), e
        inc     hl
        ld      (hl), NR_DAC_AD
        inc     hl
        ld      a, (mode)
        cp      4
        ld      a, 128
        jr      nz, .val
        push    de
        call    tri_next
        pop     de
.val:   ld      (hl), a
        inc     hl
        inc     de
        ld      a, e
        cp      LINES & $FF
        jr      nz, .build
        ld      a, d
        cp      LINES >> 8
        jr      nz, .build

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
        nextreg NR_COP_LO, 0
        nextreg NR_COP_HI, COP_RUN

        xor     a
        ld      (half), a
        nextreg NR_LINEINT_LSB, LINE_A & $FF
        nextreg NR_LINEINT_CTL, %00000110 | (LINE_A >> 8)
        ret

; A = the triangle's next value (+8 to 248, -8 to 0)
tri_next:
        ld      a, (tri)
        ld      d, a
        ld      a, (tri_dir)
        ld      e, a
        ld      a, d
        add     a, e
        cp      248
        jr      nz, .nt
        ld      e, -8
.nt:    or      a
        jr      nz, .nb
        ld      e, 8
.nb:    ld      (tri), a
        ld      d, a
        ld      a, e
        ld      (tri_dir), a
        ld      a, d
        ret

;-----------------------------------------------------------------------------
isr:
        push    af
        push    bc
        push    de
        push    hl
        ld      bc, $243B
        ld      a, NR_LINE_LO
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      (last_line), a
        ld      hl, (ticks)
        inc     hl
        ld      (ticks), hl

        ld      a, (half)
        or      a
        jr      nz, .second
        ld      hl, 0
        ld      (reg_start), hl
        nextreg NR_LINEINT_LSB, LINE_B & $FF
        nextreg NR_LINEINT_CTL, %00000110 | (LINE_B >> 8)
        ld      a, 1
        ld      (half), a
        jr      .feed
.second:
        ld      hl, HALF
        ld      (reg_start), hl
        nextreg NR_LINEINT_LSB, LINE_A & $FF
        nextreg NR_LINEINT_CTL, %00000110 | (LINE_A >> 8)
        xor     a
        ld      (half), a
.feed:
        ld      a, (mode)
        cp      4
        jr      z, .out
        ld      hl, (reg_start)
        add     hl, hl
        add     hl, hl
        ld      de, cop_buf + 3
        add     hl, de
        ld      b, HALF
.sample:
        push    hl
        push    bc
        call    tri_next
        pop     bc
        pop     hl
        ld      (hl), a
        inc     hl
        inc     hl
        inc     hl
        inc     hl
        djnz    .sample

        ld      hl, (reg_start)
        add     hl, hl
        add     hl, hl                  ; the byte index
        ld      a, (mode)
        cp      3
        jr      z, .rev
        ld      a, l
        nextreg NR_COP_LO, a
        ld      a, h
        or      COP_RUN
        nextreg NR_COP_HI, a
        jr      .index
.rev:   ld      a, h
        or      COP_RUN
        nextreg NR_COP_HI, a
        ld      a, l
        nextreg NR_COP_LO, a
.index: ld      de, cop_buf
        add     hl, de
        ld      (cop_dma_addr), hl
        ld      bc, $243B
        ld      a, NR_COP_DATA
        out     (c), a
        ld      a, (mode)
        cp      2
        jr      z, .cpu
        ld      hl, cop_dma
        ld      bc, ((cop_dma_end - cop_dma) << 8) | DMA_PORT
        otir
        jr      .fed
.cpu:   ld      hl, (cop_dma_addr)
        ld      bc, $253B
        ld      de, HALF * 4
.byte:  ld      a, (hl)
        out     (c), a
        inc     hl
        dec     de
        ld      a, d
        or      e
        jr      nz, .byte
.fed:   ld      hl, (n_feed)
        inc     hl
        ld      (n_feed), hl
.out:
        pop     hl
        pop     de
        pop     bc
        pop     af
        ei
        reti

cop_dma:
        db      $83
        db      $7D
cop_dma_addr:
        dw      0
        dw      HALF * 4
        db      $54, $02
        db      $68, $22, 0
        db      $AD
        dw      $253B
        db      $82
        db      $CF
        db      $87
cop_dma_end:

;-----------------------------------------------------------------------------
cls:
        xor     a
        out     ($FE), a
        ld      hl, $4000
        ld      de, $4001
        ld      bc, $17FF
        ld      (hl), a
        ldir
        ld      hl, $5800
        ld      de, $5801
        ld      bc, $02FF
        ld      (hl), $47
        ldir
        ret

; the word at (HL) as five decimal digits, after a space
put5:
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ex      de, hl
        ld      a, (s_col)
        inc     a
        ld      (s_col), a
        ld      de, 10000
        call    .digit
        ld      de, 1000
        call    .digit
        ld      de, 100
        call    .digit
        ld      de, 10
        call    .digit
        ld      a, l
        jp      putd
.digit: xor     a
.sub:   or      a
        sbc     hl, de
        jr      c, .done
        inc     a
        jr      .sub
.done:  add     hl, de
        push    hl
        call    putd
        pop     hl
        ret

; digit A at (s_row, s_col), and s_col on by one
putd:
        add     a, a
        add     a, a
        add     a, a
        ld      e, a
        ld      d, 0
        ld      hl, digits
        add     hl, de
        ld      a, (s_row)
        and     $18
        or      $40
        ld      d, a
        ld      a, (s_row)
        and     7
        rrca
        rrca
        rrca
        ld      e, a
        ld      a, (s_col)
        or      e
        ld      e, a
        ld      b, 8
.line:  ld      a, (hl)
        ld      (de), a
        inc     hl
        inc     d
        djnz    .line
        ld      hl, s_col
        inc     (hl)
        ret

digits:
        db      $3C, $66, $6E, $76, $66, $66, $3C, 0
        db      $18, $38, $18, $18, $18, $18, $7E, 0
        db      $3C, $66, $06, $0C, $30, $60, $7E, 0
        db      $3C, $66, $06, $1C, $06, $66, $3C, 0
        db      $0C, $1C, $3C, $6C, $7E, $0C, $0C, 0
        db      $7E, $60, $7C, $06, $06, $66, $3C, 0
        db      $3C, $60, $7C, $66, $66, $66, $3C, 0
        db      $7E, $06, $0C, $18, $30, $30, $30, 0
        db      $3C, $66, $66, $3C, $66, $66, $3C, 0
        db      $3C, $66, $66, $3E, $06, $0C, $38, 0

        EXPORT ready
ready:      db 0
        EXPORT mode
mode:       dw 0
        EXPORT ticks
ticks:      dw 0
        EXPORT n_feed
n_feed:     dw 0
        EXPORT last_line
last_line:  dw 0
        EXPORT maxline
maxline:    dw 0
s_row:      db 0
s_col:      db 0
half:       db 0
reg_start:  dw 0
tri:        db 0
tri_dir:    db 8
cop_buf:    ds LINES * 4

        ASSERT $ < VEC_TABLE

        SAVENEX OPEN "build/copdiag.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
