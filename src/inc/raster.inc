; The rasteriser and the polygon reader, shared by the harness and the game.
;
; Every line below is gated. make check-poly draws 39 coverage polygons and compares
; 49,152 of 49,152 pixels against the Python reference, with calc_step exact on 576
; cases as words. make check-readmachine drives the reader over 17 real draws from the
; engine's own trace - 59 polygons it finds for itself, at 55 distinct zooms - and
; compares the page again.
;
; THE INCLUDER MUST DEFINE the two Layer 2 windows, and that is the whole reason this
; is parameterised:
;
;   SEG_WIN      where the polygon segment's sliding window appears, with
;                NR_SEG_MMU_LO and NR_SEG_MMU_HI as its two slots
;   DWIN         where the destination band is mapped, and NR_DWIN_MMU its slot
;   SWIN         where the source band is mapped for a page copy, and NR_SWIN_MMU
;
; polytest.asm has $4000-$7FFF spare and uses MMU2 at $4000 and MMU3 at $6000. THE
; GAME CANNOT: $4000-$7FFF is its polygon/cinematic window, and the reader is reading
; that window at the very moment the rasteriser is writing a band. So the game maps
; the destination band at MMU7 ($E000) and borrows MMU2 for the source band only
; during a copy, when the polygon window is not in use. That was the second conflict
; integration turned up, after the sound ring.
;
; EVERY SLOT THIS FILE TOUCHES MUST COME FROM THE INCLUDER, and the one place that forgot cost
; I10 a day: the hierarchy's recursion restored NR_MMU0/NR_MMU1 rather than the segment window's
; own NR_SEG_MMU_LO/HI. In polytest those are the same pair, so no gate here could ever see it.
; A shared file that reaches past its own contract for a slot number is only correct in the
; configuration it was written in - the same shape as RD_LOG_RECS two paragraphs up.
;
; It must also define SCR_W and SCR_H (256 and 192), a small
; rd_log for the reader's leaf log - whose LENGTH the includer sets in RD_LOG_RECS, because
; this wrapped at a hard-coded thirty-two records while aw.asm reserved eight. The reader
; therefore ran the log 192 bytes past its reservation in the game, and because the wrap
; compares only the high byte it landed five bytes into the C's image at $9C00. polytest, where
; this code was written, reserves the thirty-two the wrap assumed, so nothing there ever showed
; it - and nothing in the game reads the log, so nothing there showed it either.
; - and DST_P0 / SRC_P0 - the first 8K page of the
; destination and source Layer 2 pages. In the game those two are not constants for
; long: the engine selects among four pages, so I2's page model replaces them.
;
; It must also INCLUDE build/interp.inc somewhere - 1,024 reciprocals, 2,048 bytes,
; indexed by an edge's dy - and provide seg_base pointing at the polygon segment's
; first 8K page.

;-----------------------------------------------------------------------------
; fill_page - A = first 8K page of a Layer 2 page, C = the byte. All six bands.
;-----------------------------------------------------------------------------
    IFNDEF RASTER_NO_FILL_PAGE
; The harness's own page fill. The game fills through aw_fill_page and leaves this out.
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
    ENDIF

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
        ; THE ACCUMULATORS IN REGISTERS for the walk. Loading and storing both 32-bit edge positions
        ; through memory on every row, with the steps re-read each time, cost about 260 T a row, and a
        ; profile of the intro's heaviest stretch put this routine at 31% of the time outside the
        ; interrupt. So for the length of a trapezoid: the low words in the shadow BC' and DE', the
        ; high words - the integer x - in IX and IY, and the four step words patched into the
        ; immediates below. About 148 T a row. Nothing the walk calls touches the shadow set or IX and
        ; IY (the span routines, band_set, dirty_band), the interrupt saves IX and the shadow set and
        ; never touches IY, and the caller's IX and IY are put back on every way out.
        push    ix
        push    iy
        ld      hl, (step1)
        ld      (.s1lo + 1), hl
        ld      hl, (step1 + 2)
        ld      (.s1hi + 1), hl
        ld      hl, (step2)
        ld      (.s2lo + 1), hl
        ld      hl, (step2 + 2)
        ld      (.s2hi + 1), hl
        exx
        ld      bc, (cpt1)
        ld      de, (cpt2)
        exx
        ld      ix, (cpt1 + 2)
        ld      iy, (cpt2 + 2)

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

        ; sx1 = the integer half of cpt1 (IX), clipped to 0
        ld      a, ixh
        or      a
        ld      a, ixl                  ; LD leaves the flags alone
        jr      z, .x1_in
        ld      a, ixh
        bit     7, a
        jp      z, .step                ; positive and > 255: nothing visible
        xor     a                       ; negative: clamp left
.x1_in:
        ld      c, a                    ; C = sx1

        ; sx2 = the integer half of cpt2 (IY), clipped to 255
        ld      a, iyh
        or      a
        ld      a, iyl
        jr      z, .x2_in
        ld      a, iyh
        bit     7, a
        jp      nz, .step               ; negative: nothing visible
        ld      a, SCR_W - 1            ; positive and > 255: clamp right
.x2_in:
        ld      b, a                    ; B = sx2

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
        call    nz, band_set
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
        ; Both accumulators, in their registers. There is no ADC for IX or IY, so each low word's
        ; carry goes into its high step with an INC before the ADD - the same sixteen bits, since only
        ; sixteen are kept. LD and EXX leave the carry alone between the two.
        exx
.s1lo:  ld      hl, 0                   ; step1, low word (patched)
        add     hl, bc                  ; cpt1 low, in BC'
        ld      b, h
        ld      c, l
.s2lo:  ld      hl, 0                   ; step2, low word (patched), for below
        exx
.s1hi:  ld      de, 0                   ; step1, high word (patched)
        jr      nc, .c1
        inc     de
.c1:    add     ix, de                  ; cpt1 high
        exx
        add     hl, de                  ; cpt2 low, in DE'
        ld      d, h
        ld      e, l
        exx
.s2hi:  ld      de, 0                   ; step2, high word (patched)
        jr      nc, .c2
        inc     de
.c2:    add     iy, de                  ; cpt2 high

        ; ++hliney, and stop once it passes the bottom edge
        ld      hl, (hliney)
        inc     hl
        ld      (hliney), hl
        ld      a, h
        or      a
        jr      z, .y_low
        bit     7, h
        jp      z, .rows_off            ; positive and > 255: off the bottom
        jr      .y_ok                   ; still negative: keep walking
.y_low:
        ld      a, l
        cp      SCR_H
        jp      nc, .rows_off           ; y > 191
.y_ok:
        ld      hl, (row_count)
        dec     hl
        ld      (row_count), hl
        ld      a, h
        or      l
        jp      nz, .row
        ; this trapezoid's rows are done: the accumulators back where the next one reads them
        exx
        ld      (cpt1), bc
        ld      (cpt2), de
        exx
        ld      (cpt1 + 2), ix
        ld      (cpt2 + 2), iy
        pop     iy
        pop     ix
        jp      .trapezoid
.rows_off:
        pop     iy
        pop     ix
.ret:
        ret



;-----------------------------------------------------------------------------
; C4 / C6: the polygon reader, and the sliding window it reads through.
;
; Video::readAndDrawPolygon (video.cpp:83-115) and readAndDrawPolygonHierarchy
; (video.cpp:206-243). The reference half is proved against the engine call for
; call by `make check-reader` - 10,700 draws, 64,897 fills, every field - so what
; is under test here is this assembly.
;
; THE WINDOW. A segment is addressed by a flat 16-bit byte offset and the largest
; cinematic segment in the game is 65,230 bytes, 306 short of everything 16 bits
; can address, so it cannot be mapped linearly into a 64K space that also holds
; code. Two 8K pages are mapped at MMU0 and MMU1 - $0000-$3FFF, the only 16K this
; program does not otherwise use - so any record starting in the low half can be
; read to its end without a remap. The longest leaf measured is 83 bytes and the
; widest hierarchy record 717.
;
; WHERE THE SCALE GOES, which is the one thing here that is easy to get wrong.
; The reference does all of the hierarchy's arithmetic in the original's 320x200
; space and scales only when it fills, so the centre is scaled ONCE, at the leaf.
; Scaling at each step instead would compute scale(a) - scale(b) where the
; reference computes scale(a - b), and two truncations do not distribute over a
; subtraction. The box and the vertex offsets ARE scaled individually, because
; that is what the reference does with them.
;
; RECURSION, not an explicit stack. The measured depth is 4 and the reference is
; recursive; the CPU stack has room, and a saved-offset array is the same thing
; with more ways to be wrong. rd_depth refuses past 8 and counts it.
;-----------------------------------------------------------------------------

X_MUL           EQU 205
Y_MUL           EQU 246

; seg_map - HL = a byte offset into the segment. Maps the two 8K pages covering
; it and returns HL as an address inside SEG_WIN.
seg_map:
        ld      a, h
        rlca
        rlca
        rlca
        and     7                       ; H >> 5 = off >> 13, the 8K page
        ld      e, a
        ld      a, (seg_base)
        add     a, e
        ld      (rd_page), a            ; remembered, so a parent can restore it
        ; THE SLOT PAIR IS THE INCLUDER'S. polytest maps the polygon segment over
        ; $0000 through MMU0 and MMU1, which it has spare. The game cannot: that is
        ; its BYTECODE window, and the VM is mid-opcode when the reader runs. The game
        ; maps the segment at $4000 through MMU2 and MMU3 instead - the region this
        ; project had written off - which is the third slot conflict integration found.
        nextreg NR_SEG_MMU_LO, a
        inc     a
        nextreg NR_SEG_MMU_HI, a        ; the next page too
        ld      a, h
        and     $1F
        add     a, SEG_WIN >> 8
        ld      h, a
        ret

; zoom_byte - A = a raw byte from the segment; returns HL = A * zoom / 64.
; Twenty-four bits on the way: a zoom of 339, which the trace contains, times 255
; is 86,445, and that does not fit a word.
zoom_byte:
        ld      hl, (rd_zoom)
        ld      d, a
        ld      e, l
        mul     d, e
        push    de
        ld      d, a
        ld      e, h
        mul     d, e
        pop     hl
        ld      b, 0
        ld      a, h
        add     a, e
        ld      h, a
        ld      a, b
        adc     a, d
        ld      b, a                    ; B:HL = byte * zoom
        ; >> 6 IS << 2 THEN >> 8. The six-pass shift loop cost 240 T of the reader's every
        ; coordinate. Bits 22 and 23 fall off the top on the way, and the result only ever used
        ; bits 6 to 21 of the product, so it is the same sixteen bits.
        add     hl, hl
        rl      b
        add     hl, hl
        rl      b
        ld      l, h
        ld      h, b
        ret

; mul_hl_a - HL unsigned times A, >> 8. The >> 8 is a byte shuffle, not a shift.
mul_hl_a:
        ld      (sc_mul), a
        ld      d, a
        ld      e, l
        mul     d, e
        push    de
        ld      a, (sc_mul)
        ld      d, a
        ld      e, h
        mul     d, e
        pop     hl
        ld      b, 0
        ld      a, h
        add     a, e
        ld      h, a
        ld      a, b
        adc     a, d
        ld      b, a
        ld      l, h
        ld      h, b
        ret

scale_ux:
        ld      a, X_MUL
        jp      mul_hl_a
scale_uy:
        ld      a, Y_MUL
        jp      mul_hl_a

; scale_sx / scale_sy - HL signed. Magnitude then sign: the reference negates,
; scales and negates back, which rounds differently from an arithmetic shift on
; every negative odd value.
scale_sx:
        ld      a, X_MUL
        jr      scale_s
scale_sy:
        ld      a, Y_MUL
scale_s:
        ld      (sc_mul2), a
        bit     7, h
        jr      nz, scale_s_neg
        ld      a, (sc_mul2)
        jp      mul_hl_a
scale_s_neg:
        xor     a
        sub     l
        ld      l, a
        sbc     a, a
        sub     h
        ld      h, a                    ; HL = -HL
        ld      a, (sc_mul2)
        call    mul_hl_a
        xor     a
        sub     l
        ld      l, a
        sbc     a, a
        sub     h
        ld      h, a
        ret

;-----------------------------------------------------------------------------
; poly_read - one record, recursive. All of its state is in memory because of
; that; the values are pushed and popped around the recursive call.
;   (rd_off)   the record's byte offset within the segment
;   (rd_col)   the incoming colour; bit 7 set means the record may supply its own
;   (rd_zoom)  the zoom
;   (rd_ptx) (rd_pty)  the centre, in the original's 320x200 space
;-----------------------------------------------------------------------------
poly_read:
        ld      a, (rd_stop)
        or      a
        ret     nz                      ; the limit was reached: unwind
        ld      a, (rd_depth)
        inc     a
        ld      (rd_depth), a
        cp      9
        jp      nc, .too_deep

        ld      hl, (rd_off)
        call    seg_map
        ld      a, (hl)
        inc     hl
        ld      (rd_src), hl            ; just past the first byte
        cp      $C0
        jp      c, .not_leaf

        ; Log this leaf's INPUTS - offset, colour, centre - before anything is
        ; computed from them. Comparing the built record says a field is wrong;
        ; comparing the inputs says whether the reader reached the right record in
        ; the first place, which is a different fault with a different cause.
    IFNDEF RASTER_NO_LEAF_LOG
        push    af
        ld      hl, (rd_log_at)
        ld      de, (rd_off)
        ld      (hl), e
        inc     hl
        ld      (hl), d
        inc     hl
        ld      a, (rd_col)
        ld      (hl), a
        inc     hl
        ld      de, (rd_ptx)
        ld      (hl), e
        inc     hl
        ld      (hl), d
        inc     hl
        ld      de, (rd_pty)
        ld      (hl), e
        inc     hl
        ld      (hl), d
        inc     hl
        inc     hl                      ; eight bytes an entry
        ; A SIXTEEN-BIT COMPARE, not the high bytes. `ld a,h / cp d` only works when the log's
        ; start and its end sit in different 256-byte pages, which is true of polytest's
        ; thirty-two records and false of the game's eight - there the first entry already
        ; tests equal and every leaf overwrote record zero.
        ld      de, rd_log + 8 * RD_LOG_RECS
        ld      a, l
        sub     e
        ld      a, h
        sbc     a, d
        jr      c, .log_ok
        ld      hl, rd_log              ; wrap rather than run off the end
.log_ok:
        ld      (rd_log_at), hl
        pop     af
    ENDIF

        ; ---- a leaf ----------------------------------------------------------
        ld      d, a
        ld      a, (rd_col)
        bit     7, a
        jr      z, .have_colour
        ld      a, d
        and     $3F
.have_colour:
        ld      (rd_record), a

        ; the centre: scaled ONCE, here, after all the hierarchy arithmetic
        ld      hl, (rd_ptx)
        call    scale_sx
        ld      (rd_record + 1), hl
        ld      hl, (rd_pty)
        call    scale_sy
        ld      (rd_record + 3), hl

        call    .next_byte
        call    zoom_byte
        call    scale_ux
        ld      (rd_record + 5), hl     ; bbw
        call    .next_byte
        call    zoom_byte
        call    scale_uy
        ld      (rd_record + 7), hl     ; bbh

        call    .next_byte
        ld      (rd_record + 9), a      ; npoints
        or      a
        jp      z, .draw
        ld      (rd_n), a
        ld      hl, rd_record + 10
        ld      (rd_dst), hl
        ; ZOOM 0x40 IS THE IDENTITY, and 97.4% of the intro's polygons use it. zoom_byte then
        ; returns the byte it was given, and all that is left is the Next's own scale - one MUL
        ; per coordinate, whose high byte IS mul_hl_a's `>> 8` for a value under 256. The general
        ; walk below cost about 2,200 T a vertex in calls, shifts and stores; this costs about 160.
        ; A profile of the intro's late frames put 62% of the time outside the interrupt in
        ; poly_read, zoom_byte and mul_hl_a, and 1% in filling spans.
        ld      hl, (rd_zoom)
        ld      a, h
        or      a
        jr      nz, .each_pt
        ld      a, l
        cp      $40
        jr      nz, .each_pt
        ld      hl, (rd_src)
        ld      bc, rd_record + 10
.fast_pt:
        ld      d, (hl)
        inc     hl
        ld      e, X_MUL
        mul     d, e                    ; D = (x * 205) >> 8, which is what scale_ux returns
        ld      a, d
        ld      (bc), a
        inc     bc
        xor     a                       ; and the high byte, always 0 here
        ld      (bc), a
        inc     bc
        ld      d, (hl)
        inc     hl
        ld      e, Y_MUL
        mul     d, e
        ld      a, d
        ld      (bc), a
        inc     bc
        xor     a
        ld      (bc), a
        inc     bc
        ld      a, (rd_n)
        dec     a
        ld      (rd_n), a
        jr      nz, .fast_pt
        ld      (rd_src), hl
        jp      .draw
.each_pt:
        call    .next_byte
        call    zoom_byte
        call    scale_ux
        call    .store
        call    .next_byte
        call    zoom_byte
        call    scale_uy
        call    .store
        ld      a, (rd_n)
        dec     a
        ld      (rd_n), a
        jp      nz, .each_pt
.draw:
        ; A polygon limit across the whole run, so a failure can be bisected to
        ; one polygon rather than one draw: a draw makes up to 256 of them and
        ; comparing the page after a whole draw says only that one of them is
        ; wrong. Gate C bisects the same way and for the same reason.
        ld      hl, (rd_pcount)
        inc     hl
        ld      (rd_pcount), hl
        ld      de, (rd_plimit)
        ld      a, d
        and     e
        inc     a
        jr      z, .do_draw             ; $FFFF means no limit, so zero can mean
        or      a                       ; "build it but draw nothing" - which is
        sbc     hl, de                  ; what a bisect needs at its first step
        jr      c, .do_draw
        ld      a, h
        or      l
        jr      z, .do_draw             ; EQUAL still draws. rd_pcount is bumped
                                        ; before this test, so carry alone means
                                        ; "draw plimit - 1 of them" and the whole
                                        ; comparison came out one polygon adrift
        ; At the limit. STOP the whole run rather than going on building records
        ; nobody draws: there is one record buffer, so continuing left the LAST
        ; polygon of the run in it and every field comparison was against the
        ; wrong polygon - which sent a debugging session hunting rounding faults
        ; in arithmetic that was right.
        ld      a, 1
        ld      (rd_stop), a
        jp      .ret
.do_draw:
        ld      hl, rd_record
        call    poly_draw
        jp      .ret

.next_byte:
        ld      hl, (rd_src)
        ld      a, (hl)
        inc     hl
        ld      (rd_src), hl
        ret

.store:
        ld      de, (rd_dst)
        ex      de, hl                  ; HL = destination, DE = the value
        ld      (hl), e
        inc     hl
        ld      (hl), d
        inc     hl
        ld      (rd_dst), hl
        ret

        ; ---- a hierarchy record ---------------------------------------------
.not_leaf:
        and     $3F
        cp      2
        jp      nz, .bad

        ; the centre moves, IN 320x200 SPACE
        call    .next_byte
        call    zoom_byte
        ld      de, (rd_ptx)
        ex      de, hl
        or      a
        sbc     hl, de
        ld      (rd_ptx), hl
        call    .next_byte
        call    zoom_byte
        ld      de, (rd_pty)
        ex      de, hl
        or      a
        sbc     hl, de
        ld      (rd_pty), hl

        ; A count MINUS ONE: read as an unsigned byte and looped while >= 0, so 0
        ; means one child and 255 means 256 (video.cpp:210-215). A WORD counter,
        ; therefore: a byte one cannot hold 256, and the first draft's `inc a /
        ; jr z` treated the 256-child case as none at all.
        call    .next_byte
        ld      l, a
        ld      h, 0
        inc     hl
        ld      (rd_kids), hl
.kid_loop:
        ; every child is read relative to THIS record's centre, so both are saved
        ld      hl, (rd_ptx)
        push    hl
        ld      hl, (rd_pty)
        push    hl

        ; The child's offset is BIG-endian, and .next_byte uses HL to walk the
        ; segment - so `ld h,a` followed by another call loses the high byte
        ; entirely. This is the same trap as point_x clobbering D, in a new place:
        ; a helper's working registers are not yours to hold a value in.
        call    .next_byte
        ld      d, a
        call    .next_byte
        ld      e, a
        push    de                      ; the offset; bit 15 decides the colour

        call    .next_byte
        call    zoom_byte
        ld      de, (rd_ptx)
        add     hl, de
        ld      (rd_cptx), hl
        call    .next_byte
        call    zoom_byte
        ld      de, (rd_pty)
        add     hl, de
        ld      (rd_cpty), hl

        pop     hl                      ; the offset again
        ld      a, $FF
        ld      (rd_ccol), a
        bit     7, h
        jr      z, .no_colour
        ; the colour byte is read WITHOUT advancing past it, then pc += 2
        push    hl
        ld      hl, (rd_src)
        ld      a, (hl)
        and     $7F
        ld      (rd_ccol), a
        ld      hl, (rd_src)
        inc     hl
        inc     hl
        ld      (rd_src), hl
        pop     hl
.no_colour:
        res     7, h                    ; offset &= 0x7FFF
        add     hl, hl                  ; times two, from the SEGMENT BASE

        ; Save what the recursion will overwrite - including THE WINDOW. A child
        ; can live in a different pair of pages, and seg_map will have moved the
        ; window to reach it, so the parent's saved rd_src is an address into
        ; whatever the child mapped. That is what made the machine find 31
        ; malformed records where the reference finds none.
        ld      de, (rd_src)
        push    de
        ld      de, (rd_kids)
        push    de
        ld      a, (rd_page)
        push    af

        ld      (rd_off), hl
        ld      a, (rd_ccol)
        ld      (rd_col), a
        ld      hl, (rd_cptx)
        ld      (rd_ptx), hl
        ld      hl, (rd_cpty)
        ld      (rd_pty), hl
        call    poly_read

        pop     af
        ld      (rd_page), a
        ; THE SEGMENT'S OWN SLOTS, which is the whole reason this line is spelled this way.
        ; It used to restore NR_MMU0 and NR_MMU1, and in polytest - where this reader was
        ; written - the segment window IS MMU0 and MMU1, so it was right and every reader gate
        ; passed. The GAME cannot put it there: MMU0 and MMU1 are the bytecode window and the VM
        ; is mid-opcode when the reader runs, so aw.asm maps the segment at $4000 on MMU2 and
        ; MMU3. Restoring the wrong pair wrote segment pages into the BYTECODE window and left
        ; the segment window holding whatever the child had mapped.
        nextreg NR_SEG_MMU_LO, a
        inc     a
        nextreg NR_SEG_MMU_HI, a        ; the parent's window, back again
        pop     de
        ld      (rd_kids), de
        pop     de
        ld      (rd_src), de
        pop     hl
        ld      (rd_pty), hl
        pop     hl
        ld      (rd_ptx), hl

        ld      a, (rd_stop)
        or      a
        jp      nz, .ret
        ld      hl, (rd_kids)
        dec     hl
        ld      (rd_kids), hl
        ld      a, h
        or      l
        jp      nz, .kid_loop
        jp      .ret

.bad:
        ld      hl, (rd_bad)
        inc     hl
        ld      (rd_bad), hl
.ret:
        ld      a, (rd_depth)
        dec     a
        ld      (rd_depth), a
        ret

.too_deep:
        ld      hl, (rd_deep)
        inc     hl
        ld      (rd_deep), hl
        jp      .ret

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
;-----------------------------------------------------------------------------
; band_set - A = the band (y >> 5) to draw into next, known to differ from cur_band.
; Maps the destination and the copy mode's source for it. Keeps BC and DE; A comes back.
;
; THE DESTINATION PAGE IS A VARIABLE, not a constant. The harness draws into one page for its
; whole run; the engine keeps four and selects among them with selectVideoPage, so the band's page
; number has to be read rather than assembled in. dst_p0 and src_p0 start as the harness's two
; constants, so nothing changes for it.
;-----------------------------------------------------------------------------
band_set:
        ld      (cur_band), a
    IFDEF DIRTY_BANDS
        call    dirty_band              ; the includer's: this band of this page is being drawn on
    ENDIF
        push    af
        ld      hl, dst_p0
        add     a, (hl)
        nextreg NR_DWIN_MMU, a
        pop     af
        push    af
        ld      hl, src_p0
        add     a, (hl)
        nextreg NR_SWIN_MMU, a          ; the copy mode's source band
        pop     af
        ret

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
        ; THROUGH band_set, LIKE A SPAN. This used to map NR_MMU3 and NR_MMU2 with the constants
        ; DST_P0 and SRC_P0 - polytest's slots and polytest's pages, written before the game had
        ; either. In the game those are the POLYGON SEGMENT WINDOW, so every point unmapped the
        ; reader's data, and the pixel went through DWIN into whatever band was last mapped
        ; there - while cur_band claimed a band that nothing had mapped. Part 2 draws 15,734 points
        ; in 700 blits. In polytest band_set does exactly what this did, so nothing changes there.
        ld      hl, cur_band
        cp      (hl)
        call    nz, band_set
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


        EXPORT dst_p0
dst_p0:         db DST_P0       ; the first 8K page of the page being drawn into
        EXPORT src_p0
src_p0:         db SRC_P0       ; and of the source, for a page copy
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
        EXPORT cur_band
cur_band:       db 255
cs_left:        dw 0
t_p1:           dw 0            ; p1's coordinate, in memory not in D
m_a:            dw 0            ; the multiply's operands
m_b:            dw 0
sc_mul:         db 0
sc_mul2:        db 0
        EXPORT seg_base
seg_base:       db 0            ; the first 8K page of the polygon segment
        EXPORT rd_off
rd_off:         dw 0
        EXPORT rd_col
rd_col:         db 0
        EXPORT rd_zoom
rd_zoom:        dw 64
        EXPORT rd_ptx
rd_ptx:         dw 0
        EXPORT rd_pty
rd_pty:         dw 0
        EXPORT rd_bad
rd_bad:         dw 0            ; records whose first byte was neither form
        EXPORT rd_deep
rd_deep:        dw 0            ; records refused for nesting past 8
rd_depth:       db 0
rd_src:         dw 0
rd_dst:         dw 0
rd_n:           db 0
rd_kids:        dw 0
rd_page:        db 0            ; the first of the two pages now in the window
rd_cptx:        dw 0
rd_cpty:        dw 0
rd_ccol:        db 0
        EXPORT read_mode
read_mode:      db 0            ; 1 = drive the reader from rd_list
        EXPORT rd_count
rd_count:       dw 0
        EXPORT rd_plimit
rd_plimit:      dw $FFFF        ; $FFFF = no limit; 0 = draw none
        EXPORT rd_pcount
rd_pcount:      dw 0
rd_log_at:      dw rd_log
        EXPORT rd_stop
rd_stop:        db 0
rd_left:        dw 0
rd_next:        dw 0
        EXPORT rd_record
rd_record:      ds 10 + 50 * 4  ; the record poly_draw parses, built here
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
