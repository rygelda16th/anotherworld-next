;-----------------------------------------------------------------------------
; What does a span cost in Layer 2's 320x256 mode, against today's 256x192?
;
; tools/wide320.py counts, from the reference engine's traces, every span and page byte both
; layouts would draw; this times one span of each kind on the machine so the counts can be priced.
; The checker is tools/wide320.py's `machine` command, the method check-span uses: a counter after
; each pass of SPANS spans, the emulator's T-state counter, the NULL mode subtracted.
;
; Only what DIFFERS between the layouts is in here - the edge stepping and the clip are the same per
; row in both and are left out. Each mode runs the span's ENTRY (band or strip, address, length) and
; its FILL, as the game's row walk does after .ordered (src/inc/raster.inc):
;
;   256x192   address = band page (y >> 5) at $E000 + ((y & 31) << 8) + x; a span is `inc l`
;   320x256   address = strip page (x >> 5) at $E000 + ((x & 31) << 8) + y; a span is `inc h`,
;             and every 32 columns the strip's 8K page changes: one NextReg and a new entry
;   320x256/64  the same with TWO pages mapped ($C000-$FFFF), so a strip is 64 columns
;
; Modes:  0 NULL   1 256 opaque (CPU)   2 256 blend   3 256 opaque by the DMA (span_dma)
;         4 320 opaque   5 320 blend   6 320/64 opaque
;-----------------------------------------------------------------------------
        DEVICE ZXSPECTRUMNEXT

SPANS       EQU 192             ; one pass: y = 0..191
L2P0        EQU 24              ; 8K page 24 = bank 12, Layer 2's first page
NR_TURBO    EQU $07
NR_MMU6     EQU $56
NR_MMU7     EQU $57
WIN         EQU $E000
WINH        EQU WIN >> 8
WIN64       EQU $C000
WIN64H      EQU WIN64 >> 8
DMA_PORT    EQU $6B

        ORG $8000
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3             ; 28 MHz
        nextreg NR_MMU6, L2P0
        nextreg NR_MMU7, L2P0
        ld      a, $5A
        ld      (ready), a

main:
        ld      a, (hold)
        or      a
        jr      z, .go
        ld      a, (hold_page)          ; a checker reads one page through MMU7, unmoving
        nextreg NR_MMU7, a
.held:  ld      a, (hold)
        or      a
        jr      nz, .held
        ld      a, 255
        ld      (n_bcmp + 1), a
        ld      (w_scmp + 1), a
        ld      (w64_scmp + 1), a
.go:
        call    one_pass
        ld      hl, (passes)
        inc     hl
        ld      (passes), hl
        jr      main

one_pass:
        ld      a, (mode)
        add     a, a
        ld      e, a
        ld      d, 0
        ld      hl, targets
        add     hl, de
        ld      a, (hl)
        inc     hl
        ld      h, (hl)
        ld      l, a
        ld      (.call + 1), hl
        ld      a, (mode)
        add     a, $20
        ld      (colour), a
        ld      a, 255                  ; every pass starts with nothing mapped
        ld      (n_bcmp + 1), a
        ld      (w_scmp + 1), a
        ld      (w64_scmp + 1), a
        xor     a
        ld      (cur_y), a
.span:
        ld      ix, (bench_x)
        ld      hl, (bench_x)
        ld      de, (bench_len)
        add     hl, de
        dec     hl
        push    hl
        pop     iy                      ; IY = x2
        ld      a, (cur_y)
        ld      e, a
        ld      a, (colour)
.call:  call    0
        ld      a, (cur_y)
        inc     a
        ld      (cur_y), a
        cp      SPANS
        jr      nz, .span
        ret

targets:
        dw      null_span, n_entry, n_entry_bl, n_entry_dma, w_entry, w_entry_bl, w64_entry
null_span:
        ret

;-----------------------------------------------------------------------------
; 256x192, as raster.inc does it from .ordered: E = y, IXL = x1, IYL = x2, A = colour.
;-----------------------------------------------------------------------------
n_entry:
        ld      hl, n_opaque
        jr      n_common
n_entry_bl:
        ld      hl, n_blend
        jr      n_common
n_entry_dma:
        ld      hl, n_dma
n_common:
        ld      (n_fill + 1), hl
        ld      (n_col + 1), a
        ld      c, ixl
        ld      b, iyl
        ld      a, e
        rlca
        rlca
        rlca
        and     7
n_bcmp: cp      0
        call    nz, n_band
        ld      a, e
        and     31
        add     a, WINH
        ld      h, a
        ld      l, c
        ld      a, b
        sub     c
        ld      e, a
        ld      d, 0
        inc     de
n_col:  ld      a, 0
n_fill: jp      0

n_band:
        ld      (n_bcmp + 1), a
        push    af
        add     a, L2P0
        nextreg NR_MMU7, a
        pop     af
        ret

; span_opaque's CPU path: HL = dest, DE = length 1..256, A = colour
n_opaque:
        ex      de, hl
        add     hl, hl
        ex      de, hl
        push    hl
        ld      hl, n_op_end
        sbc     hl, de
        ld      (.jp + 1), hl
        pop     hl
.jp:    jp      0
        DUP 256
        ld      (hl), a
        inc     l
        EDUP
n_op_end:
        ret

n_blend:
        push    hl
        ex      de, hl
        ld      d, h
        ld      e, l
        add     hl, hl
        add     hl, de
        ex      de, hl
        ld      hl, n_bl_end
        or      a
        sbc     hl, de
        ld      (.jp + 1), hl
        pop     hl
.jp:    jp      0
        DUP 256
        set     3, (hl)
        inc     l
        EDUP
n_bl_end:
        ret

; span_dma, src/aw.asm's: the colour held in a byte, the DMA fills from it, continuous mode
n_dma:
        ld      (sd_col), a
        ld      b, d
        ld      c, e
        ex      de, hl                  ; DE = destination
        ld      hl, sd_col
        ld      (dm_src), hl
        ld      (dm_dst), de
        ld      (dm_len), bc
        ld      hl, dm_prog
        ld      bc, ((dm_end - dm_prog) << 8) | DMA_PORT
        otir
        ret
dm_prog:
        db      $83                     ; DISABLE
        db      $7D                     ; WR0: A -> B, address and length follow
dm_src: dw      0
dm_len: dw      0
        db      $64, $02                ; WR1: port A memory, FIXED - a fill
        db      $50, $22, 0             ; WR2: port B memory, incrementing, prescalar 0
        db      $AD                     ; WR4: continuous, port B address follows
dm_dst: dw      0
        db      $82                     ; WR5: stop at end of block
        db      $CF                     ; LOAD
        db      $87                     ; ENABLE
dm_end:
sd_col: db      0

;-----------------------------------------------------------------------------
; 320x256: E = y, IX = x1 (0..319), IY = x2, A = colour.
; The strip is x1 >> 5, the address $E000 + ((x1 & 31) << 8) + y.
;-----------------------------------------------------------------------------
w_entry:
        ld      hl, w_op_run
        jr      w_common
w_entry_bl:
        ld      hl, w_bl_run
w_common:
        ld      (w_run_jp + 1), hl
        ld      c, a                    ; C = the colour, for the whole span
        ld      a, ixh                  ; strip = (x1h << 3) | (x1l >> 5)
        add     a, a
        add     a, a
        add     a, a
        ld      b, a
        ld      a, ixl
        rlca
        rlca
        rlca
        and     7
        or      b
w_scmp: cp      0
        call    nz, w_strip
        ld      a, ixl
        and     31
        add     a, WINH
        ld      h, a
        ld      l, e
        ld      a, iyl                  ; DE = x2 - x1 + 1
        sub     ixl
        ld      e, a
        ld      a, iyh
        sbc     a, ixh
        ld      d, a
        inc     de
.seg:   xor     a                       ; room left in this strip, 1..32: the window
        sub     h                       ; ends at $10000, so it is 0 - H
        ld      b, a
        ld      a, d
        or      a
        jr      nz, .full
        ld      a, b
        cp      e
        jr      nc, .last               ; room >= length: the last piece
.full:  ld      a, e                    ; DE -= room
        sub     b
        ld      e, a
        jr      nc, .nb
        dec     d
.nb:    ld      a, b
        call    w_run
        ld      a, (w_scmp + 1)         ; the next strip
        inc     a
        call    w_strip
        ld      h, WINH
        jr      .seg
.last:  ld      a, e
        ; and on into w_run, which returns for the span

; w_run - A = pixels 1..32 across the strip from HL, colour C. Keeps DE.
w_run:
w_run_jp:
        jp      0
w_op_run:
        add     a, a                    ; two bytes a pixel
        push    de
        ld      e, a
        ld      d, 0
        push    hl
        ld      hl, w_op_end
        or      a
        sbc     hl, de
        ld      (.jp + 1), hl
        pop     hl
        pop     de
.jp:    jp      0
        DUP 32
        ld      (hl), c
        inc     h
        EDUP
w_op_end:
        ret
w_bl_run:
        ld      b, a                    ; three bytes a pixel
        add     a, a
        add     a, b
        push    de
        ld      e, a
        ld      d, 0
        push    hl
        ld      hl, w_bl_end
        or      a
        sbc     hl, de
        ld      (.jp + 1), hl
        pop     hl
        pop     de
.jp:    jp      0
        DUP 32
        set     3, (hl)
        inc     h
        EDUP
w_bl_end:
        ret

w_strip:
        ld      (w_scmp + 1), a
        add     a, L2P0
        nextreg NR_MMU7, a
        ret

;-----------------------------------------------------------------------------
; 320x256 with a 64-column window: MMU6 and MMU7 both, so a span crosses half as often.
;-----------------------------------------------------------------------------
w64_entry:
        ld      c, a
        ld      a, ixh                  ; strip = (x1h << 2) | (x1l >> 6)
        add     a, a
        add     a, a
        ld      b, a
        ld      a, ixl
        rlca
        rlca
        and     3
        or      b
w64_scmp: cp    0
        call    nz, w64_strip
        ld      a, ixl
        and     63
        add     a, WIN64H
        ld      h, a
        ld      l, e
        ld      a, iyl
        sub     ixl
        ld      e, a
        ld      a, iyh
        sbc     a, ixh
        ld      d, a
        inc     de
.seg:   xor     a                       ; 0 - H again: the window ends at $10000
        sub     h
        ld      b, a
        ld      a, d
        or      a
        jr      nz, .full
        ld      a, b
        cp      e
        jr      nc, .last
.full:  ld      a, e
        sub     b
        ld      e, a
        jr      nc, .nb
        dec     d
.nb:    ld      a, b
        call    w64_run
        ld      a, (w64_scmp + 1)
        inc     a
        call    w64_strip
        ld      h, WIN64H
        jr      .seg
.last:  ld      a, e
w64_run:
        add     a, a
        push    de
        ld      e, a
        ld      d, 0
        push    hl
        ld      hl, w64_end
        or      a
        sbc     hl, de
        ld      (.jp + 1), hl
        pop     hl
        pop     de
.jp:    jp      0
        DUP 64
        ld      (hl), c
        inc     h
        EDUP
w64_end:
        ret

w64_strip:
        ld      (w64_scmp + 1), a
        add     a, a
        add     a, L2P0
        nextreg NR_MMU6, a
        inc     a
        nextreg NR_MMU7, a
        ret

;-----------------------------------------------------------------------------
        EXPORT ready
ready:      db 0
        EXPORT mode
mode:       db 0
        EXPORT hold
hold:       db 0
        EXPORT hold_page
hold_page:  db L2P0
        EXPORT bench_len
bench_len:  dw 22
        EXPORT bench_x
bench_x:    dw 40
        EXPORT passes
passes:     dw 0
colour:     db 0
cur_y:      db 0

        ASSERT $ < $BF00
        SAVENEX OPEN "build/wide320.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
