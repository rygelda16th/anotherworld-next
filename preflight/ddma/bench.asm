;-----------------------------------------------------------------------------
; plan-ddma.md D2: what does a 320x256 row cost by the zxnDDMA's 2D fill, against the CPU?
;
; In 320x256 a row of a polygon is one byte every 256 (Layer 2's column-major layout), so the game's
; CPU span is `ld (hl), a / inc h`, 11 T-states a pixel, and a new 8K strip every 64 columns. The
; zxnDDMA (core 3.03.00) can fill it in one transfer: physical addresses, 2D, row length 1, one "row"
; a pixel, port B stride 256, fill (the core distribution's docs/zxnDDMA/zxnddma.gde 2.5). What a row
; of one byte costs the DMA is not in the guide, and 3.03's source is not public, so this times it.
;
; Each test starts on raster line 0 and reads the line it ends on (NextRegs $1E and $1F), the
; guide's own method (zxnddma_compare.asm): a line is 64 us, 1,792 T-states at 28 MHz. Every test
; is about 4,096 pixels, inside one frame. The results are words at `results`, line counts, and
; `checks` holds what the CPU found in memory after the 2D tests (see count). awprobe's AWPROBE_PEEK reads both.
;
;   0  nothing                                        the method's own cost
;   1  CPU, `ld (hl), a / inc h`, 64 spans of 64      the game's span, unrolled, as raster.inc's
;   2  plain zxnDMA fill, 8,192 bytes                 fixed source, cycle lengths 2 and 2: today's
;   3  zxnDDMA fill, 8,192 bytes                      the same block, $DF bit 3 (D1)
;   4  zxnDDMA 2D fill, 64 spans of 64                row length 1, stride 256, physical
;   5  zxnDDMA 2D fill, 13 spans of 320               the whole width
;   6  zxnDDMA 2D fill, 256 spans of 16               short ones
;   7  as 4, the whole programme (RESET first) for every span, no short reload
;   8  as 6, the same
;   9  as 4, with about 3,300 T-states of CPU wait after every span (is the CPU held?)
;
; Each 2D span is a short reload (guide 2.9, note 1): $E7 the number of rows, $DB and WR4 the
; physical address, LOAD, ENABLE - nine bytes by OTIR - after one full programme per test.
;-----------------------------------------------------------------------------
        DEVICE ZXSPECTRUMNEXT

NR_TURBO    EQU $07
NR_MMU6     EQU $56
NR_MMU7     EQU $57
DMA_PORT    EQU $6B
L2P0        EQU 24                  ; 8K page 24, bank 12: where the game's Layer 2 starts
L2PHYS      EQU $40000 + L2P0 * $2000   ; $070000
COLOUR      EQU $11

        ORG $8000
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3             ; 28 MHz
        nextreg NR_MMU6, L2P0
        nextreg NR_MMU7, L2P0 + 1       ; $C000-$FFFF: Layer 2's first 64 columns
        ld      ix, results
        call    sync
        call    line_now                ; 0: nothing
        call    store
        call    sync
        call    t_cpu
        call    line_now
        call    store
        call    sync
        call    t_dma
        call    line_now
        call    store
        call    sync
        call    t_ddma
        call    line_now
        call    store
        ld      de, 64                  ; 4: 64 spans of 64
        ld      b, 64
        call    t_2d_run
        call    hist                    ; and where its bytes went
        ld      de, 320                 ; 5: 13 of 320
        ld      b, 13
        call    t_2d_run
        ld      de, 16                  ; 6: 256 of 16
        ld      b, 0
        call    t_2d_run
        ld      a, 1                    ; 7 and 8: the whole programme for every span
        ld      (full), a
        ld      de, 64
        ld      b, 64
        call    t_2d_run
        ld      de, 16
        ld      b, 0
        call    t_2d_run
        ld      a, 2                    ; 9: as 4, the short reload, and a wait after every span
        ld      (full), a
        ld      de, 64
        ld      b, 64
        call    t_2d_run
        ld      a, $5A
        ld      (ready), a
        jr      $

; one 2D test: DE pixels a span, B spans (0 = 256), the colour checked after
t_2d_run:
        push    bc
        push    de
        call    clear
        pop     de
        pop     bc
        push    bc
        push    de
        call    sync
        call    t_2d
        call    line_now
        call    store
        pop     de
        pop     bc
        jp      count                   ; checks[]: how many of the bytes it should have set are set

store:
        ld      (ix + 0), l
        ld      (ix + 1), h
        inc     ix
        inc     ix
        ret

; wait for the start of line 0
sync:
.out:   call    line_now
        ld      a, h
        or      l
        jr      z, .out                 ; already on 0: wait for it to pass
.in:    call    line_now
        ld      a, h
        or      l
        jr      nz, .in
        ret

; HL = the raster line now
line_now:
        ld      bc, $243B
        ld      a, $1E
        out     (c), a
        inc     b
        in      h, (c)
        dec     b
        ld      a, $1F
        out     (c), a
        inc     b
        in      l, (c)
        ld      a, h
        and     1
        ld      h, a
        ret

t_cpu:
        ld      b, 64
        ld      l, 0
.span:  ld      h, $C0
        ld      a, COLOUR
        call    span64
        inc     l
        djnz    .span
        ret
span64:
        DUP 64
        ld      (hl), a
        inc     h
        EDUP
        ret

t_dma:
        ld      hl, dma_prog
        ld      bc, ((dma_end - dma_prog) << 8) | DMA_PORT
        otir
        ret
dma_prog:
        db      $83, $C3
        db      $7D
        dw      colour_byte, $2000
        db      $64, $02                ; WR1: port A memory, fixed, cycle length 2
        db      $50, $22, 0             ; WR2: port B memory, incrementing, cycle length 2
        db      $AD
        dw      $C000
        db      $82, $CF, $87
dma_end:
colour_byte:    db COLOUR

t_ddma:
        ld      hl, ddma_prog
        ld      bc, ((ddma_end - ddma_prog) << 8) | DMA_PORT
        otir
        ret
ddma_prog:
        db      $83, $C3
        db      $DF, %00001000          ; fill
        db      $F7, COLOUR
        db      $7D
        dw      0, $2000
        db      $54, $02
        db      $50, $22, 0
        db      $AD
        dw      $C000
        db      $82, $CF, $87
        db      $83, $C3
ddma_end:

; B spans of DE pixels, span s at x = 0, y = s: physical L2PHYS + s
t_2d:
        ld      (p_rows), de
        ld      (r_rows), de
        ld      hl, p2_prog
        ld      c, DMA_PORT
        ld      a, b
        ld      b, p2_end - p2_prog
        otir                            ; the full programme: span 0
        ld      b, a
        dec     b
        jr      z, .done
        ld      de, (L2PHYS & $FFFF) + 1
.span:  ld      (r_lo), de
        ld      (p_lo), de
        ld      hl, r_prog
        ld      a, (full)
        or      a
        ld      a, b
        ld      b, r_end - r_prog
        jr      z, .short
        ld      hl, p2_prog
        ld      b, p2_end - p2_prog
.short: otir
        ld      b, a
        ld      a, (full)
        cp      2
        jr      nz, .nowait
        push    bc                      ; full = 2: about 3,300 T-states before the next span
        ld      b, 0
.wait:  djnz    .wait
        pop     bc
.nowait:
        inc     de
        djnz    .span
.done:  ld      de, L2PHYS & $FFFF
        ld      (p_lo), de
        ld      hl, flags_down
        ld      b, 2
        otir
        ret
p2_prog:
        db      $83, $C3
        db      $D7, 0
        db      $DB, L2PHYS >> 16
        db      $DF, %00001011          ; physical, 2D, fill
        db      $E3
        dw      1                       ; a row is one byte
        db      $E7
p_rows: dw      0                       ; and a "row" a pixel: the span's length
        db      $EB
        dw      0
        db      $EF
        dw      256                     ; the next pixel to the right
        db      $F7, COLOUR
        db      $7D
        dw      0, 1
        db      $54, $02
        db      $50, $22, 0
        db      $AD
p_lo:   dw      L2PHYS & $FFFF
        db      $82, $CF, $87
p2_end:
r_prog:
        db      $E7
r_rows: dw      0
        db      $DB, L2PHYS >> 16
        db      $AD
r_lo:   dw      0
        db      $CF, $87
r_end:
flags_down:
        db      $83, $C3

; zero the pages the 2D tests write: 320 columns, pages 24-33
clear:
        ld      a, L2P0
.page:  nextreg NR_MMU7, a
        ld      hl, $E000
        ld      de, $E001
        ld      bc, $1FFF
        ld      (hl), 0
        ldir
        inc     a
        cp      L2P0 + 10
        jr      nz, .page
        nextreg NR_MMU7, L2P0 + 1
        ret

; checks: two words a 2D test - the bytes holding COLOUR inside its spans (B spans of DE, B 0 = 256,
; at x 0.. and y 0..), then every byte that is not zero anywhere in the 320 columns. The two match,
; and equal B x DE, when the fill wrote exactly its spans and nothing else.
count:
        ld      (c_len), de
        ld      a, b
        ld      (c_spans), a
        ld      hl, 0
        ld      (c_good), hl
        ld      (c_tot), hl
        ld      bc, 0                   ; BC = x
.col:   ld      a, b                    ; the page: L2P0 + x >> 5
        rlca
        rlca
        rlca
        ld      d, a
        ld      a, c
        rlca
        rlca
        rlca
        and     7
        or      d
        add     a, L2P0
        nextreg NR_MMU7, a
        ld      hl, (c_len)             ; is x inside the spans?
        or      a
        sbc     hl, bc
        ld      a, 0
        jr      c, .xo
        jr      z, .xo
        inc     a
.xo:    ld      (c_xin), a
        ld      a, c
        and     31
        add     a, $E0
        ld      h, a
        ld      l, 0                    ; HL = the column's first byte, L = y
.row:   ld      a, (hl)
        or      a
        jr      z, .next
        push    hl
        ld      hl, (c_tot)
        inc     hl
        ld      (c_tot), hl
        pop     hl
        cp      COLOUR
        jr      nz, .next
        ld      a, (c_xin)
        or      a
        jr      z, .next
        ld      a, (c_spans)
        or      a
        jr      z, .yin                 ; 256 spans: every y
        ld      d, a
        ld      a, l
        cp      d
        jr      nc, .next
.yin:   push    hl
        ld      hl, (c_good)
        inc     hl
        ld      (c_good), hl
        pop     hl
.next:  inc     l
        jr      nz, .row
        inc     bc
        ld      a, b
        or      a
        jr      z, .col
        ld      a, c
        cp      320 - 256
        jr      nz, .col
        ld      hl, (c_ptr)
        ld      de, (c_good)
        ld      (hl), e
        inc     hl
        ld      (hl), d
        inc     hl
        ld      de, (c_tot)
        ld      (hl), e
        inc     hl
        ld      (hl), d
        inc     hl
        ld      (c_ptr), hl
        nextreg NR_MMU7, L2P0 + 1
        ret

        EXPORT ready
        EXPORT results
        EXPORT checks
; rowhist[y], y 0-63: the bytes holding COLOUR in row y, all 320 columns; colhist[x], x 0-79: in
; column x, all 256 rows. What test 4 left, to show which pixels a wrong 2D fill wrote.
hist:
        ld      bc, 0
.col:   ld      a, b
        rlca
        rlca
        rlca
        ld      d, a
        ld      a, c
        rlca
        rlca
        rlca
        and     7
        or      d
        add     a, L2P0
        nextreg NR_MMU7, a
        ld      a, c
        and     31
        add     a, $E0
        ld      h, a
        ld      l, 0
.row:   ld      a, (hl)
        cp      COLOUR
        jr      nz, .next
        ld      a, l
        cp      64
        jr      nc, .nr
        push    hl
        ld      h, 0
        ld      de, rowhist
        add     hl, de
        inc     (hl)
        pop     hl
.nr:    ld      a, b
        or      a
        jr      nz, .next
        ld      a, c
        cp      80
        jr      nc, .next
        push    hl
        ld      hl, colhist
        ld      e, c
        ld      d, 0
        add     hl, de
        inc     (hl)
        pop     hl
.next:  inc     l
        jr      nz, .row
        inc     bc
        ld      a, b
        or      a
        jr      z, .col
        ld      a, c
        cp      320 - 256
        jr      nz, .col
        nextreg NR_MMU7, L2P0 + 1
        ret

        EXPORT rowhist
rowhist:    ds 64
        EXPORT colhist
colhist:    ds 80
ready:      db 0
full:       db 0
c_len:      dw 0
c_spans:    db 0
c_xin:      db 0
c_good:     dw 0
c_tot:      dw 0
c_ptr:      dw checks
results:    ds 20
checks:     ds 24

        SAVENEX OPEN "build/ddmabench.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
