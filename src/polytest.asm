;-----------------------------------------------------------------------------
; Gate C: the polygon rasteriser, on the machine, pixel-exact.
;
; Draws the 57 polygons in build/polytest.inc - real shapes taken from a trace
; of the game, chosen for coverage - into Layer 2 page 1, and stops. The checker
; then reads the page back and compares it byte for byte against what
; tools/refvideo.py produced from exactly the same polygons.
;
; This is a transcription of fillPolygon and the three drawLine variants from
; the GPL lineage (awbi/src/video.cpp:119-475), at 256x192 and one byte a pixel.
; The reference has already been proved identical to the real engine over 64,897
; polygons at the original 320x200 and 4bpp, so what is under test here is this
; assembly, not the algorithm.
;
; CORRECTNESS FIRST. The edge accumulators live in memory, which step 0 measured
; at 433 T-states of per-span overhead and identified as the thing to fix. They
; are deliberately left there until this file is exact: the test vector is what
; makes moving them into registers a safe change rather than a hopeful one.
;
; Vertices arrive already scaled into 256x192 space. The scale is a vertex
; transform that belongs in the polygon reader, where it folds into the multiply
; the engine already does for zoom, and it is checked separately - so keeping it
; out of here leaves one thing under test at a time.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

SCR_W           EQU 256
SCR_H           EQU 192
L2_BASE_BANK    EQU 12                  ; page 0 = banks 12,13,14
BANDS           EQU 6                   ; 8K pages of 32 scanlines each
DST_PAGE        EQU 1                   ; draw into Layer 2 page 1
SRC_PAGE        EQU 0                   ; fill mode 0x11 copies from page 0
DST_P0          EQU (L2_BASE_BANK + DST_PAGE * 3) * 2
SRC_P0          EQU (L2_BASE_BANK + SRC_PAGE * 3) * 2
DWIN            EQU $6000               ; MMU3: the destination band
SWIN            EQU $4000               ; MMU2: the source band, copy mode only

NR_TURBO        EQU $07
NR_MMU2         EQU $52
NR_MMU3         EQU $53
NR_L2_BANK      EQU $12
NR_L2_CFG       EQU $70
L2_PORT         EQU $123B
L2_VISIBLE      EQU %00000010

        ORG $8000
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3
        nextreg NR_L2_CFG, 0            ; 256x192, 8bpp
        nextreg NR_L2_BANK, L2_BASE_BANK + DST_PAGE * 3
        ld      bc, L2_PORT
        ld      a, L2_VISIBLE
        out     (c), a

        ; Unit-test calc_step before drawing anything. The walk's arithmetic is
        ; a signed 8x16 multiply, a shift and a 24-bit negate, and a fault in it
        ; looks exactly like a geometry fault from the outside - so it is checked
        ; on its own against the same values Python computes.
        ; A WORD counter in memory, not DJNZ: `ld b, CS_COUNT` truncated 648 to
        ; 136 and the remaining cases read back as zeros, which looks exactly
        ; like an arithmetic fault. sjasmplus warned about the truncation and the
        ; warning is the only reason it took a minute rather than an hour.
        ld      hl, cs_cases
        ld      de, cs_results
        ld      bc, CS_COUNT
        ld      (cs_left), bc
.cs_each:
        push    hl
        push    de
        ; the case is four bytes: p1.x, p1.y, p2.x, p2.y
        ld      (p_pts), hl             ; treat the case AS the point array
        ld      b, 0                    ; index 0 = p1
        ld      c, 1                    ; index 1 = p2
        call    calc_step
        pop     de
        ld      hl, (step_lo)
        ld      a, l
        ld      (de), a
        inc     de
        ld      a, h
        ld      (de), a
        inc     de
        ld      hl, (step_hi)
        ld      a, l
        ld      (de), a
        inc     de
        ld      a, h
        ld      (de), a
        inc     de
        ld      hl, (step_dy)
        ld      a, l
        ld      (de), a
        inc     de
        ld      a, h
        ld      (de), a
        inc     de
        pop     hl
        ld      bc, 4
        add     hl, bc
        ld      bc, (cs_left)
        dec     bc
        ld      (cs_left), bc
        ld      a, b
        or      c
        jp      nz, .cs_each
        ld      a, $C5
        ld      (cs_done), a

        ; Wait for the checker to set the polygon limit and release us. Without
        ; this the program would have drawn everything before a poke could land.
.wait_go:
        ld      a, (go)
        or      a
        jr      z, .wait_go

        ; Page 0 gets the seed the reference used, so the copy mode has
        ; something recognisable to copy; page 1 starts clear.
        ld      c, PAGE0_SEED
        ld      a, SRC_P0
        call    fill_page
        ld      c, 0
        ld      a, DST_P0
        call    fill_page

        ; Draw them all.
        ;
        ; Step 2 needs a WINDOW, not just a prefix. Taking prefixes alone leaves
        ; the polygon count and the span count almost perfectly correlated, and a
        ; two-variable fit cannot then tell the two costs apart - whichever varies
        ; more absorbs the other. Drawing [poly_first, poly_first + poly_limit)
        ; lets the checker pick three point polygons against three large ones and
        ; decorrelate them on purpose.
.draw_all:
        ld      a, (poly_limit)
        or      a
        jr      z, .drawn               ; a limit of zero draws nothing
        ld      b, a
        ; Start at record (poly_first) through the generated offset table, NOT by
        ; walking records. Walking put a cost proportional to the start index
        ; into every measurement, and since the checker's windows start
        ; everywhere and all hold four polygons, that confound landed entirely
        ; in the per-polygon term and inflated it by an order of magnitude.
        ld      a, (poly_first)
        add     a, a
        ld      e, a
        ld      d, 0
        ld      hl, poly_index
        add     hl, de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ld      hl, poly_data
        add     hl, de
.each:
        push    bc
        push    hl
        call    poly_draw
        pop     hl
        ld      de, 0                   ; advance HL over this record
        ld      a, (hl)                 ; colour
        inc     hl                      ; -> ptx
        inc     hl
        inc     hl                      ; -> pty
        inc     hl
        inc     hl                      ; -> bbw
        inc     hl                      ; -> bbh
        inc     hl                      ; -> npoints
        ld      a, (hl)
        inc     hl                      ; -> points
        add     a, a                    ; npoints * 2 bytes
        ld      e, a
        ld      d, 0
        jr      nc, .nohi
        inc     d
.nohi:
        add     hl, de
        pop     bc
        djnz    .each
.drawn:
        ; Step 2 of the plan wants the cost of drawing N polygons, and the fills
        ; above cost two whole pages, so bench mode loops the DRAW only. Page 0
        ; keeps the seed the copy mode reads; page 1 accumulates, which changes
        ; the picture and not the work, since every fill mode writes the same
        ; number of bytes whatever is already there.
        ld      a, (bench)
        or      a
        jr      z, .finish
        ld      hl, (passes)
        inc     hl
        ld      (passes), hl
        jp      .draw_all
.finish:
        ld      a, $5A
        ld      (done), a
.hold:  jr      .hold                   ; the checker reads Layer 2 from here

;-----------------------------------------------------------------------------
; fill_page - A = first 8K page of a Layer 2 page, C = the byte. All six bands.
;-----------------------------------------------------------------------------
fill_page:
        ld      b, BANDS
.band:
        nextreg NR_MMU3, a
        push    af
        push    bc
        ld      hl, DWIN
        ld      a, c
        ld      d, 32                   ; 32 scanlines in an 8K band
.row:
        ld      b, 0                    ; 256 bytes
.byte:
        ld      (hl), a
        inc     l
        djnz    .byte
        inc     h
        dec     d
        jr      nz, .row
        pop     bc
        pop     af
        inc     a
        djnz    .band
        ret

;-----------------------------------------------------------------------------
; poly_draw - HL = a polygon record. Mirrors Video::fillPolygon.
;-----------------------------------------------------------------------------
poly_draw:
        ; ---- parse the record ----
        ld      a, (hl)
        ld      (p_colour), a
        inc     hl
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      (p_ptx), de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      (p_pty), de
        ld      a, (hl)
        ld      (p_bbw), a
        inc     hl
        ld      a, (hl)
        ld      (p_bbh), a
        inc     hl
        ld      a, (hl)
        ld      (p_npts), a
        inc     hl
        ld      (p_pts), hl

        ; ---- the degenerate case: bbw == 0 && bbh == 1 && npoints == 4 ----
        ld      a, (p_bbw)
        or      a
        jr      nz, .box
        ld      a, (p_bbh)
        dec     a
        jr      nz, .box
        ld      a, (p_npts)
        cp      4
        jr      nz, .box
        jp      draw_point

.box:
        ; x1 = ptx - bbw/2 ; x2 = ptx + bbw/2   (bbw/2 is an unsigned halving)
        ld      a, (p_bbw)
        srl     a                       ; NOTE: this leaves the shifted-out bit
        ld      c, a                    ; in carry, so an odd bbw would make the
        ld      hl, (p_ptx)             ; SBC below subtract one too many.
        ld      d, 0
        ld      e, c
        push    hl
        or      a                       ; clear carry before the SBC
        sbc     hl, de
        ld      (p_x1), hl
        pop     hl
        add     hl, de
        ld      (p_x2), hl

        ; y1 = pty - bbh/2 ; y2 = pty + bbh/2
        ld      a, (p_bbh)
        srl     a
        ld      e, a
        ld      d, 0
        ld      hl, (p_pty)
        push    hl
        or      a                       ; clear carry for the SBC
        sbc     hl, de
        ld      (p_y1), hl
        pop     hl
        add     hl, de
        ld      (p_y2), hl

        ; if x1 > 255 or x2 < 0 or y1 > 191 or y2 < 0: nothing is visible
        ld      hl, (p_x1)
        ld      de, SCR_W - 1
        call    cmp_signed              ; HL - DE
        jp      z, .x1ok                ; x1 == 255 is on screen: carry on
        jp      p, .ret                 ; x1 > 255: nothing is visible
.x1ok:
        ld      hl, (p_x2)
        bit     7, h
        jp      nz, .ret                ; x2 < 0
        ld      hl, (p_y1)
        ld      de, SCR_H - 1
        call    cmp_signed
        jp      z, .y1ok
        jp      p, .ret
.y1ok:
        ld      hl, (p_y2)
        bit     7, h
        jp      nz, .ret

        ; hliney = y1
        ld      hl, (p_y1)
        ld      (hliney), hl

        ; i = 0 ; j = npoints - 1
        xor     a
        ld      (p_i), a
        ld      a, (p_npts)
        dec     a
        ld      (p_j), a

        ; x2 = points[i].x + x1 ; x1 = points[j].x + x1
        ld      a, (p_i)
        call    point_x                 ; A = points[A].x
        ld      e, a
        ld      d, 0
        ld      hl, (p_x1)
        add     hl, de
        ld      (cpt2 + 2), hl          ; the high word IS the integer part
        ld      a, (p_j)
        call    point_x
        ld      e, a
        ld      d, 0
        ld      hl, (p_x1)
        add     hl, de
        ld      (cpt1 + 2), hl
        ld      hl, 0
        ld      (cpt1), hl
        ld      (cpt2), hl

        ; ++i ; --j
        ld      hl, p_i
        inc     (hl)
        ld      hl, p_j
        dec     (hl)

        ; pick the fill: < 0x10 opaque, == 0x10 blend, > 0x10 copy from page 0
        ld      a, (p_colour)
        cp      $10
        jr      c, .opaque
        jr      z, .blend
        ld      hl, span_copy
        jr      .setfn
.blend: ld      hl, span_blend
        jr      .setfn
.opaque:
        ld      hl, span_opaque
.setfn: ld      (span_fn), hl

;-----------------------------------------------------------------------------
; The trapezoid walk.
;-----------------------------------------------------------------------------
.trapezoid:
        ld      a, (p_npts)
        sub     2
        ld      (p_npts), a
        or      a
        jp      z, .ret                 ; numPoints == 0: done

        ; step1 = calcStep(points[j+1], points[j])   - its dy is DISCARDED
        ld      a, (p_j)
        inc     a
        ld      b, a                    ; p1 index
        ld      a, (p_j)
        ld      c, a                    ; p2 index
        call    calc_step
        ld      hl, (step_lo)
        ld      (step1), hl
        ld      hl, (step_hi)
        ld      (step1 + 2), hl

        ; step2 = calcStep(points[i-1], points[i])   - THIS one's dy is h.
        ; The original passes dy by reference and calls calcStep twice, so the
        ; second call overwrites it. For a well-formed trapezoid both are equal;
        ; this follows the original rather than the assumption.
        ld      a, (p_i)
        dec     a
        ld      b, a
        ld      a, (p_i)
        ld      c, a
        call    calc_step
        ld      hl, (step_lo)
        ld      (step2), hl
        ld      hl, (step_hi)
        ld      (step2 + 2), hl

        ld      hl, p_i
        inc     (hl)
        ld      hl, p_j
        dec     (hl)

        ; cpt1 = (cpt1 & 0xFFFF0000) | 0x7FFF ; cpt2 likewise | 0x8000.
        ; These two constants bias the left edge down and the right edge up so a
        ; span rounds outward, which is what makes adjacent polygons meet
        ; without a seam. They are not interchangeable.
        ld      hl, $7FFF
        ld      (cpt1), hl
        ld      hl, $8000
        ld      (cpt2), hl

        ld      hl, (step_dy)
        ld      a, h
        or      l
        jr      nz, .rows
        ; h == 0: step both accumulators once and take the next trapezoid
        call    step_both
        jp      .trapezoid

.rows:
        ld      (row_count), hl
.row:
        ; if hliney >= 0 and the span is on screen, draw it
        ld      hl, (hliney)
        bit     7, h
        jr      nz, .next               ; above the top edge
        call    emit_span
.next:
        call    step_both
        ld      hl, (hliney)
        inc     hl
        ld      (hliney), hl
        ld      de, SCR_H - 1
        call    cmp_signed
        jr      z, .more
        jp      p, .ret                 ; hliney > 191: off the bottom
.more:
        ld      hl, (row_count)
        dec     hl
        ld      (row_count), hl
        ld      a, h
        or      l
        jr      nz, .row
        jp      .trapezoid
.ret:
        ret

;-----------------------------------------------------------------------------
; emit_span - clip the current scanline's two edges and paint it.
;-----------------------------------------------------------------------------
emit_span:
        ld      hl, (cpt1 + 2)          ; sx1, signed
        ld      (sx1), hl
        ld      hl, (cpt2 + 2)          ; sx2, signed
        ld      (sx2), hl

        ; if sx1 > 255 or sx2 < 0: nothing
        ld      hl, (sx1)
        ld      de, SCR_W - 1
        call    cmp_signed
        jr      z, .l_ok
        ret     p                       ; sx1 > 255
.l_ok:
        ld      hl, (sx2)
        bit     7, h
        ret     nz                      ; sx2 < 0

        ; clamp sx1 to >= 0
        ld      hl, (sx1)
        bit     7, h
        jr      z, .l_pos
        ld      hl, 0
        ld      (sx1), hl
.l_pos:
        ; clamp sx2 to <= 255
        ld      hl, (sx2)
        ld      de, SCR_W - 1
        call    cmp_signed
        jr      z, .r_ok
        jp      m, .r_ok
        ld      hl, SCR_W - 1
        ld      (sx2), hl
.r_ok:
        ; the band, and the MMU write only when it changes
        ld      a, (hliney)             ; 0..191 here, so the low byte is enough
        ld      e, a
        ; y >> 5, the 8K band. THREE RLCA, not RRCA: rotating a byte right
        ; three times leaves bits 3-5 in the low bits, which is (y >> 3) & 7 -
        ; a band change every 8 rows instead of every 32. Rotating LEFT three
        ; times brings bits 5-7 down, which is what y >> 5 means.
        rlca
        rlca
        rlca
        and     7
        ld      hl, cur_band
        cp      (hl)
        jr      z, .band_ok
        ld      (hl), a
        push    af
        add     a, DST_P0
        nextreg NR_MMU3, a
        pop     af
        add     a, SRC_P0
        nextreg NR_MMU2, a              ; the copy mode's source band
.band_ok:
        ; The two edges can CROSS, and then sx1 > sx2. The original's drawLine
        ; routines take MIN and MAX of their two arguments, so the span is still
        ; drawn left to right; computing sx2 - sx1 without that underflows and
        ; paints the whole 256-byte row. It shows up only on the last rows of a
        ; sliver, where the accumulators finally overtake each other.
        ld      a, (sx1)
        ld      c, a
        ld      a, (sx2)
        cp      c
        jr      nc, .ordered            ; sx2 >= sx1, nothing to do
        ld      (sx1), a                ; swap them
        ld      a, c
        ld      (sx2), a
.ordered:
        ; HL = DWIN + ((y & 31) << 8) + sx1 ; B = length
        ld      a, e
        and     31
        add     a, DWIN >> 8
        ld      h, a
        ld      a, (sx1)
        ld      l, a
        ld      a, (sx2)
        sub     l
        inc     a                       ; length 1..256, 0 meaning 256
        ld      b, a
        ld      a, (p_colour)
        ld      ix, (span_fn)
        jp      (ix)

;-----------------------------------------------------------------------------
; The three fills. HL = first pixel, B = count (0 means 256), A = colour.
; No end masking at all: at one byte a pixel every span is whole bytes, which
; is the masking the 4bpp original needs at both ends of all three of these.
;-----------------------------------------------------------------------------
span_opaque:
        and     $0F                     ; index in the low nibble, top clear
.l:     ld      (hl), a
        inc     l
        djnz    .l
        ret

span_blend:
        ; Colour 0x10: set bit 3 of the index. The game's palettes already hold
        ; the blended variants at entries 8-15, so this needs no palette work.
.l:     set     3, (hl)
        inc     l
        djnz    .l
        ret

span_copy:
        ; Colour above 0x10: take the pixels from page 0 at the same coordinate.
        ld      d, h
        ld      e, l
        ld      a, h
        sub     (DWIN - SWIN) >> 8
        ld      h, a                    ; HL = the source, DE = the destination
.l:     ld      a, (hl)
        ld      (de), a
        inc     l
        inc     e
        djnz    .l
        ret

;-----------------------------------------------------------------------------
; draw_point - the degenerate polygon. Video::drawPoint, at one byte a pixel.
;-----------------------------------------------------------------------------
draw_point:
        ld      hl, (p_ptx)
        ld      de, SCR_W - 1
        call    cmp_signed
        jr      z, .xok
        ret     p
.xok:   ld      hl, (p_ptx)
        bit     7, h
        ret     nz
        ld      hl, (p_pty)
        ld      de, SCR_H - 1
        call    cmp_signed
        jr      z, .yok
        ret     p
.yok:   ld      hl, (p_pty)
        bit     7, h
        ret     nz

        ld      a, (p_pty)
        ld      e, a
        ; y >> 5, the 8K band. THREE RLCA, not RRCA: rotating a byte right
        ; three times leaves bits 3-5 in the low bits, which is (y >> 3) & 7 -
        ; a band change every 8 rows instead of every 32. Rotating LEFT three
        ; times brings bits 5-7 down, which is what y >> 5 means.
        rlca
        rlca
        rlca
        and     7
        ld      hl, cur_band
        ld      (hl), a
        push    af
        add     a, DST_P0
        nextreg NR_MMU3, a
        pop     af
        add     a, SRC_P0
        nextreg NR_MMU2, a
        ld      a, e
        and     31
        add     a, DWIN >> 8
        ld      h, a
        ld      a, (p_ptx)
        ld      l, a

        ld      a, (p_colour)
        cp      $10
        jr      c, .flat
        jr      z, .bl
        ld      a, h                    ; copy from page 0
        sub     (DWIN - SWIN) >> 8
        ld      d, a
        ld      e, l
        ld      a, (de)
        ld      (hl), a
        ret
.bl:    set     3, (hl)
        ret
.flat:  and     $0F
        ld      (hl), a
        ret

;-----------------------------------------------------------------------------
; calc_step - B = p1 index, C = p2 index.
;   dy   = p2.y - p1.y, as 16 bits (masked to the table, see below)
;   step = (p2.x - p1.x) * interp[dy] * 4, signed 32-bit
; Results in step_lo/step_hi/step_dy.
;-----------------------------------------------------------------------------
calc_step:
        push    bc
        ld      a, b
        call    point_y
        ld      (t_p1), a               ; p1.y - NOT in D: point_y builds its
        pop     bc                      ; index in DE and clobbers it, which is
        push    bc                      ; what made every negative run come out
        ld      a, c                    ; as zero.
        call    point_y
        ld      hl, t_p1
        sub     (hl)                    ; p2.y - p1.y
        ld      e, a
        ld      d, 0
        jr      nc, .dypos
        dec     d                       ; sign-extend a negative difference
.dypos:
        ld      (step_dy), de
        ; The table has 0x400 entries and the walk only ever produces a dy
        ; inside it for a well-formed polygon; masking keeps a malformed one
        ; from reading past the end rather than pretending it cannot happen.
        ld      a, d
        and     3
        ld      d, a
        ld      hl, interp_table
        sla     e
        rl      d
        add     hl, de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ld      (interp), de

        pop     bc
        push    bc
        ld      a, b
        call    point_x
        ld      (t_p1), a               ; p1.x, in memory for the same reason
        pop     bc
        ld      a, c
        call    point_x
        ld      hl, t_p1
        sub     (hl)                    ; dx = p2.x - p1.x, signed in A
        ld      c, 0                    ; C = sign flag
        jr      nc, .dxpos
        neg
        ld      c, 1
.dxpos:
        ; 24-bit product of A (0..255) and the 16-bit interp value
        ld      hl, (interp)
        ld      d, a
        ld      e, l
        mul     d, e                    ; low byte product -> DE
        push    de
        ld      d, a
        ld      e, h
        mul     d, e                    ; high byte product -> DE
        pop     hl                      ; HL = low product
        ; result = HL + (DE << 8), 24 bits in B:HL
        ld      b, 0
        ld      a, h
        add     a, e
        ld      h, a
        ld      a, b
        adc     a, d
        ld      b, a                    ; B holds bits 16-23

        ; times four
        sla     l
        rl      h
        rl      b
        sla     l
        rl      h
        rl      b

        ; and the sign
        ld      a, c
        or      a
        jr      z, .store
        ; negate the 24-bit value
        ld      a, l
        cpl
        ld      l, a
        ld      a, h
        cpl
        ld      h, a
        ld      a, b
        cpl
        ld      b, a
        inc     hl
        ld      a, h
        or      l
        jr      nz, .store
        inc     b
.store:
        ld      (step_lo), hl
        ld      a, b
        ld      (step_hi), a
        ; bits 24-31: the sign extension of a 26-bit signed value
        ld      a, c
        or      a
        ld      a, 0
        jr      z, .pos
        ld      a, $FF
.pos:   ld      (step_hi + 1), a
        ret

;-----------------------------------------------------------------------------
; step_both - cpt1 += step1 ; cpt2 += step2, 32-bit.
;-----------------------------------------------------------------------------
step_both:
        ld      hl, (cpt1)
        ld      de, (step1)
        add     hl, de
        ld      (cpt1), hl
        ld      hl, (cpt1 + 2)
        ld      de, (step1 + 2)
        adc     hl, de
        ld      (cpt1 + 2), hl

        ld      hl, (cpt2)
        ld      de, (step2)
        add     hl, de
        ld      (cpt2), hl
        ld      hl, (cpt2 + 2)
        ld      de, (step2 + 2)
        adc     hl, de
        ld      (cpt2 + 2), hl
        ret

;-----------------------------------------------------------------------------
; point_x / point_y - A = index, returns points[A].x or .y in A.
;-----------------------------------------------------------------------------
point_x:
        add     a, a
        ld      e, a
        ld      d, 0
        jr      nc, .n
        inc     d
.n:     ld      hl, (p_pts)
        add     hl, de
        ld      a, (hl)
        ret

point_y:
        add     a, a
        ld      e, a
        ld      d, 0
        jr      nc, .n
        inc     d
.n:     ld      hl, (p_pts)
        add     hl, de
        inc     hl
        ld      a, (hl)
        ret

;-----------------------------------------------------------------------------
; cmp_signed - signed HL - DE. Returns with the sign flag set as a signed
; comparison wants it, and Z if equal. HL and DE are preserved.
;-----------------------------------------------------------------------------
cmp_signed:
        push    hl
        push    de
        ld      a, h
        xor     d
        jp      m, .differ              ; different signs
        or      a
        sbc     hl, de
        ld      a, h
        or      l
        jr      z, .eq
        bit     7, h
        jr      nz, .neg
        pop     de
        pop     hl
        xor     a
        inc     a                       ; NZ, P: HL > DE
        ret
.neg:   pop     de
        pop     hl
        ld      a, $80
        or      a                       ; NZ, M: HL < DE
        ret
.eq:    pop     de
        pop     hl
        xor     a                       ; Z
        ret
.differ:
        ; HL and DE have different signs, so whichever is negative is smaller
        bit     7, h
        pop     de
        pop     hl
        jr      nz, .hl_neg
        ld      a, 1
        or      a
        ret                             ; HL positive, DE negative: HL > DE
.hl_neg:
        ld      a, $80
        or      a
        ret

;-----------------------------------------------------------------------------
        EXPORT done
done:           db 0
        ; How many polygons to draw. The checker pokes this and reboots to
        ; bisect: comparing only the finished page says something is wrong,
        ; never which shape made it wrong.
        EXPORT poly_limit
poly_limit:     db POLY_COUNT
        EXPORT bench
bench:          db 0            ; 1 = redraw forever and count passes
        EXPORT poly_first
poly_first:     db 0            ; the first record to draw, via poly_index
        EXPORT passes
passes:         dw 0
        EXPORT go
go:             db 0
        EXPORT cs_done
cs_done:        db 0
        EXPORT cs_results
cs_results:     ds CS_COUNT * 6         ; step (4 bytes) then dy (2) per case
        EXPORT p_colour
p_colour:       db 0
p_ptx:          dw 0
p_pty:          dw 0
p_bbw:          db 0
p_bbh:          db 0
p_npts:         db 0
p_pts:          dw 0
p_i:            db 0
p_j:            db 0
p_x1:           dw 0
p_x2:           dw 0
p_y1:           dw 0
p_y2:           dw 0
        EXPORT hliney
hliney:         dw 0
row_count:      dw 0
sx1:            dw 0
sx2:            dw 0
span_fn:        dw 0
cur_band:       db 255
cs_left:        dw 0
t_p1:           db 0
interp:         dw 0
step_dy:        dw 0
step_lo:        dw 0
step_hi:        dw 0, 0
cpt1:           dw 0, 0
cpt2:           dw 0, 0
step1:          dw 0, 0
step2:          dw 0, 0

        ALIGN 2
        INCLUDE "build/csteps.inc"
        INCLUDE "build/interp.inc"
        INCLUDE "build/polytest.inc"

        ASSERT $ < $BF00
        SAVENEX OPEN "build/polytest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
