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
        ; the case is EIGHT bytes now: p1.x, p1.y, p2.x, p2.y as signed words,
        ; the same layout poly_data uses, so this exercises point_x and point_y
        ; as well as the arithmetic.
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
        ld      bc, 8                   ; two points of two words
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
        ; Advance HL over this record. FOUR bytes a point and TWO each for bbw
        ; and bbh, since the widening: a stale copy of this arithmetic was what
        ; broke Gate C on the first widened build, and the bisect named polygon 1
        ; - a plain rectangle - which is the shape of a layout fault rather than
        ; an arithmetic one.
        ld      de, 9                   ; colour, ptx, pty, bbw, bbh
        add     hl, de
        ld      a, (hl)                 ; npoints
        inc     hl                      ; -> points
        ld      e, a
        ld      d, 0
        ex      de, hl
        add     hl, hl
        add     hl, hl                  ; npoints * 4
        ex      de, hl
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
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      (p_bbw), de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      (p_bbh), de
        ld      a, (hl)
        ld      (p_npts), a
        inc     hl
        ld      (p_pts), hl

        ; ---- the degenerate case: bbw == 0 && bbh == 1 && npoints == 4 ----
        ld      hl, (p_bbw)
        ld      a, h
        or      l
        jr      nz, .box
        ld      hl, (p_bbh)
        dec     hl
        ld      a, h
        or      l
        jr      nz, .box
        ld      a, (p_npts)
        cp      4
        jr      nz, .box
        jp      draw_point

.box:
        ; x1 = ptx - bbw/2 ; x2 = ptx + bbw/2.
        ; SIXTEEN-BIT halving: the box reaches 423 x 483 in this game, so `srl a`
        ; on a byte was wrong for every box over 255 - and Gate C's vector topped
        ; out at 204, which is why it went unnoticed. SRL H / RR L also leaves the
        ; shifted-out bit in carry, so the SBC still needs it cleared.
        ld      hl, (p_bbw)
        srl     h
        rr      l
        ld      d, h
        ld      e, l                    ; DE = bbw / 2
        ld      hl, (p_ptx)
        push    hl
        or      a                       ; clear carry before the SBC
        sbc     hl, de
        ld      (p_x1), hl
        pop     hl
        add     hl, de
        ld      (p_x2), hl

        ; y1 = pty - bbh/2 ; y2 = pty + bbh/2
        ld      hl, (p_bbh)
        srl     h
        rr      l
        ld      d, h
        ld      e, l
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
        call    point_x                 ; HL = points[A].x, signed word
        ld      de, (p_x1)
        add     hl, de
        ld      (cpt2 + 2), hl          ; the high word IS the integer part
        ld      a, (p_j)
        call    point_x
        ld      de, (p_x1)
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
.setfn: ld      (.span_call + 1), hl    ; patch the CALL, once a polygon

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

;-----------------------------------------------------------------------------
; One scanline, FUSED. This was three routines and four calls to cmp_signed,
; which make.check-polycost measured at 1,570 T-states of span entry against the
; 433 T step 0 measured for its own span row. The difference was all avoidable:
; two call/ret pairs, a general signed comparator invoked four times a row for
; values that are known to be 16-bit and small, and sx1/sx2 written to memory and
; read back three times each.
;
; Every comparison here is inline and specialised instead. At this point hliney is
; either negative or 0..191 - the loop below exits as soon as it passes 191 - so
; a non-zero high byte means negative and nothing else, which is one test rather
; than a subroutine.
;-----------------------------------------------------------------------------
.row:
        ld      hl, (hliney)
        ld      a, h
        or      a
        jp      nz, .step               ; above the top edge: step, do not draw
        ld      e, l                    ; E = y, 0..191, for band and address

        ; sx1 = the integer half of cpt1, clipped to 0
        ld      hl, (cpt1 + 2)
        ld      a, h
        or      a
        jr      z, .x1_in
        bit     7, h
        jp      z, .step                ; positive and > 255: nothing visible
        ld      l, 0                    ; negative: clamp left
.x1_in:
        ld      c, l                    ; C = sx1

        ; sx2 = the integer half of cpt2, clipped to 255
        ld      hl, (cpt2 + 2)
        ld      a, h
        or      a
        jr      z, .x2_in
        bit     7, h
        jp      nz, .step               ; negative: nothing visible
        ld      l, SCR_W - 1            ; positive and > 255: clamp right
.x2_in:
        ld      b, l                    ; B = sx2

        ; The two edges can CROSS, and then sx1 > sx2. The original's drawLine
        ; routines take MIN and MAX of their arguments; without that the length
        ; underflows and paints the whole 256-byte row. It shows up only on the
        ; last rows of a sliver, where the accumulators finally overtake.
        ld      a, b
        cp      c
        jr      nc, .ordered
        ld      a, c
        ld      c, b
        ld      b, a
.ordered:
        ; the band, and the MMU write only when it changes. y >> 5 is THREE RLCA,
        ; not RRCA: three RRCA leaves bits 3-5 low, which is (y >> 3) & 7 and
        ; moves the window every 8 rows instead of every 32.
        ld      a, e
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
        ; HL = DWIN + ((y & 31) << 8) + sx1 ; DE = length as a WORD.
        ; A word, not a byte: a full-width span is 256 pixels, which is 0 in a
        ; byte, and every fill below needs the true length to compute its entry.
        ld      a, e
        and     31
        add     a, DWIN >> 8
        ld      h, a
        ld      l, c
        ld      a, b
        sub     c
        ld      e, a
        ld      d, 0
        inc     de                      ; DE = 1..256
        ld      a, (p_colour)
        ; A LOCAL label. As a global one it reparented every local label after it
        ; to itself, so .row and .step became span_call.row and span_call.step and
        ; poly_draw's own jumps stopped resolving - the same trap span_tail hit in
        ; src/span.asm.
.span_call:
        call    0000                    ; patched per polygon by .setfn

.step:
        ; Both accumulators, inline. The call/ret this replaces was 34 T of the
        ; 1,570.
        ld      hl, (cpt1)
        ld      de, (step1)
        add     hl, de
        ld      (cpt1), hl
        ld      hl, (cpt1 + 2)
        ld      de, (step1 + 2)
        adc     hl, de                  ; carry survives the two LDs
        ld      (cpt1 + 2), hl
        ld      hl, (cpt2)
        ld      de, (step2)
        add     hl, de
        ld      (cpt2), hl
        ld      hl, (cpt2 + 2)
        ld      de, (step2 + 2)
        adc     hl, de
        ld      (cpt2 + 2), hl

        ; ++hliney, and stop once it passes the bottom edge
        ld      hl, (hliney)
        inc     hl
        ld      (hliney), hl
        ld      a, h
        or      a
        jr      z, .y_low
        bit     7, h
        jp      z, .ret                 ; positive and > 255: off the bottom
        jr      .y_ok                   ; still negative: keep walking
.y_low:
        ld      a, l
        cp      SCR_H
        jp      nc, .ret                ; y > 191
.y_ok:
        ld      hl, (row_count)
        dec     hl
        ld      (row_count), hl
        ld      a, h
        or      l
        jp      nz, .row
        jp      .trapezoid
.ret:
        ret

;-----------------------------------------------------------------------------
; The three fills. HL = the first pixel, DE = length 1..256, A = colour.
;
; All three are UNROLLED with a computed entry, which is the second half of what
; check-polycost said was needed: the loops they replace charged 21.3 T an opaque
; byte and 32.0 T a blend byte, measured, against step 0's 10.7 and 19 for exactly
; this technique. A DJNZ is 13 T of the 24 an opaque byte used to cost.
;
; No end masking at all: at one byte a pixel every span is whole bytes, which is
; the masking the 4bpp original needs at both ends of all three of these.
;-----------------------------------------------------------------------------
span_opaque:
        and     $0F                     ; index in the low nibble, top clear
        ex      de, hl                  ; HL = length, DE = dest
        add     hl, hl                  ; 2 bytes a pixel in the block below
        ex      de, hl                  ; DE = length*2, HL = dest
        push    hl
        ld      hl, opaque_end
        sbc     hl, de                  ; carry is clear after ADD HL,HL
        ld      (opaque_jp + 1), hl
        pop     hl
opaque_jp:
        jp      0000
        DUP 256
        ld      (hl), a
        inc     l
        EDUP
opaque_end:
        ret

span_blend:
        ; Colour 0x10: set bit 3 of the index. The game's palettes already hold
        ; the blended variants at entries 8-15, so this needs no palette work.
        ;
        ; PUSH THE DESTINATION FIRST. Length*3 needs a copy of the length in a
        ; pair, and the only spare pair is DE - which is holding the destination.
        ; The first version wrote the length over it and then restored the length
        ; as the destination, which the Gate C bisect named in one run: polygon
        ; 35, bucket 'blend'.
        push    hl                      ; the destination
        ex      de, hl                  ; HL = length
        ld      d, h
        ld      e, l                    ; DE = length
        add     hl, hl                  ; 2 * length
        add     hl, de                  ; 3 * length, 3 bytes a pixel
        ex      de, hl                  ; DE = 3 * length
        ld      hl, blend_end
        or      a
        sbc     hl, de
        ld      (blend_jp + 1), hl
        pop     hl                      ; HL = the destination again
blend_jp:
        jp      0000
        DUP 256
        set     3, (hl)
        inc     l
        EDUP
blend_end:
        ret

span_copy:
        ; Colour above 0x10: take the pixels from page 0 at the same coordinate.
        ; The entry has to be computed BEFORE DE becomes the destination, because
        ; the block needs both pointers.
        ex      de, hl                  ; HL = length, DE = dest
        add     hl, hl
        add     hl, hl                  ; HL = length*4, 4 bytes a pixel
        ex      de, hl                  ; DE = length*4, HL = dest
        push    hl
        ld      hl, copy_end
        or      a
        sbc     hl, de
        ld      (copy_jp + 1), hl
        pop     hl
        ld      d, h
        ld      e, l                    ; DE = destination
        ld      a, h
        sub     (DWIN - SWIN) >> 8
        ld      h, a                    ; HL = source, same offset in page 0
copy_jp:
        jp      0000
        DUP 256
        ld      a, (hl)
        ld      (de), a
        inc     l
        inc     e
        EDUP
copy_end:
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
        ; dy = p2.y - p1.y, a SIGNED 16-BIT difference now. Both coordinates can
        ; exceed a byte: the game's post-zoom geometry reaches 483 in y after the
        ; 256x192 scale.
        push    bc
        ld      a, b
        call    point_y
        ld      (t_p1), hl              ; p1.y - NOT in a register pair that
        pop     bc                      ; point_y clobbers, which is what made
        push    bc                      ; every negative run come out as zero.
        ld      a, c
        call    point_y                 ; HL = p2.y
        ld      de, (t_p1)
        or      a                       ; clear carry for the SBC
        sbc     hl, de                  ; HL = dy, signed
        ld      (step_dy), hl

        ; The table has 0x400 entries and a well-formed polygon never produces a
        ; dy outside it; masking keeps a malformed one from reading past the end
        ; rather than pretending it cannot happen.
        ld      a, h
        and     3
        ld      h, a
        add     hl, hl                  ; word entries
        ld      de, interp_table
        add     hl, de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ld      (interp), de

        ; dx = p2.x - p1.x, signed 16-bit
        pop     bc
        push    bc
        ld      a, b
        call    point_x
        ld      (t_p1), hl
        pop     bc
        ld      a, c
        call    point_x
        ld      de, (t_p1)
        or      a
        sbc     hl, de                  ; HL = dx, signed

        ; magnitude and sign, because MUL D,E is unsigned
        ld      c, 0
        bit     7, h
        jr      z, .dxpos
        ld      c, 1
        xor     a
        sub     l
        ld      l, a
        sbc     a, a
        sub     h
        ld      h, a                    ; HL = -HL
.dxpos:
        ; ---- |dx| * interp, 16 x 16 -> 32 bits -------------------------------
        ; Four MUL D,E and three shifted accumulations. This was an 8 x 16
        ; product while a coordinate was a byte; widening it is the one part of
        ; the 16-bit change that is not mechanical, which is exactly what the
        ; 2,862-case unit test is for.
        ;
        ;   prod = al*bl + (ah*bl + al*bh) << 8 + ah*bh << 16
        ;
        ; The accumulator IS step_lo..step_hi+1, four contiguous bytes.
        ld      (m_a), hl
        ld      hl, (interp)
        ld      (m_b), hl

        ld      a, (m_a)
        ld      d, a
        ld      a, (m_b)
        ld      e, a
        mul     d, e                    ; al * bl
        ld      (step_lo), de
        xor     a
        ld      (step_hi), a
        ld      (step_hi + 1), a

        ld      a, (m_a + 1)
        ld      d, a
        ld      a, (m_b)
        ld      e, a
        mul     d, e                    ; ah * bl, at byte 1
        call    .add_at1

        ld      a, (m_a)
        ld      d, a
        ld      a, (m_b + 1)
        ld      e, a
        mul     d, e                    ; al * bh, at byte 1
        call    .add_at1

        ld      a, (m_a + 1)
        ld      d, a
        ld      a, (m_b + 1)
        ld      e, a
        mul     d, e                    ; ah * bh, at byte 2
        ld      hl, step_hi
        ld      a, (hl)
        add     a, e
        ld      (hl), a
        inc     hl
        ld      a, (hl)
        adc     a, d
        ld      (hl), a

        ; ---- times four, 32-bit ---------------------------------------------
        ld      hl, step_lo
        call    .shl32
        ld      hl, step_lo
        call    .shl32

        ; ---- and the sign ---------------------------------------------------
        ld      a, c
        or      a
        ret     z
        ; negate the 32-bit value: complement all four bytes and add one
        ld      hl, step_lo
        ld      b, 4
.cpl:
        ld      a, (hl)
        cpl
        ld      (hl), a
        inc     hl
        djnz    .cpl
        ld      hl, step_lo
        ld      b, 4
.inc32:
        inc     (hl)
        ret     nz                      ; no carry out of this byte: done
        inc     hl
        djnz    .inc32
        ret

.add_at1:
        ; the 16-bit product in DE, added in at byte 1 of the accumulator
        ld      hl, step_lo + 1
        ld      a, (hl)
        add     a, e
        ld      (hl), a
        inc     hl
        ld      a, (hl)
        adc     a, d
        ld      (hl), a
        inc     hl
        ld      a, (hl)
        adc     a, 0
        ld      (hl), a
        ret

.shl32:
        ; HL -> a four-byte little-endian value; shift it left once
        sla     (hl)
        inc     hl
        rl      (hl)
        inc     hl
        rl      (hl)
        inc     hl
        rl      (hl)
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
; point_x / point_y - A = index, returns points[A].x or .y in HL, signed.
; Four bytes a point now, two signed words, because the game's post-zoom geometry
; reaches 423 x 483 after the 256x192 scale.
;
; These still build their index in DE, so they still CLOBBER D - which is what
; made every negative run compute as zero when a caller held a value there. The
; callers keep their operands in memory for exactly that reason.
;-----------------------------------------------------------------------------
point_x:
        ld      l, a
        ld      h, 0
        add     hl, hl
        add     hl, hl                  ; index * 4
        ld      de, (p_pts)
        add     hl, de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ex      de, hl
        ret

point_y:
        ld      l, a
        ld      h, 0
        add     hl, hl
        add     hl, hl
        ld      de, (p_pts)
        add     hl, de
        inc     hl
        inc     hl
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ex      de, hl
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
        EXPORT p_colour
p_colour:       db 0
p_ptx:          dw 0
p_pty:          dw 0
p_bbw:          dw 0
p_bbh:          dw 0
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
cur_band:       db 255
cs_left:        dw 0
t_p1:           dw 0            ; p1's coordinate, in memory not in D
m_a:            dw 0            ; the multiply's operands
m_b:            dw 0
interp:         dw 0
step_dy:        dw 0
step_lo:        dw 0
step_hi:        dw 0, 0
cpt1:           dw 0, 0
cpt2:           dw 0, 0
step1:          dw 0, 0
step2:          dw 0, 0

; The generated tables and the unit test's results live ABOVE the stack. Below it
; they do not fit: the unrolled fills are 2,304 bytes of straight-line code, the
; widened cases are fourteen bytes each, and together they pushed the program past
; $BF00 and then past 64K - which sjasmplus reports as "write outside of device
; memory" and truncated address constants, not as "this does not fit".
; $C000 upwards is slot 3, which nothing here pages: the Layer 2 windows are MMU2
; and MMU3.
        ORG     $C000
cs_results:     ds CS_COUNT * 6         ; step (4 bytes) then dy (2) per case
        ALIGN 2
        INCLUDE "build/csteps.inc"
        INCLUDE "build/interp.inc"
        INCLUDE "build/polytest.inc"

        ASSERT $ < $FF00
        SAVENEX OPEN "build/polytest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
