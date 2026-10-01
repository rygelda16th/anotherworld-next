; The 320x256 build's own versions of three things that change shape with the screen
; (docs/plan-wide320.md W3). Included in the resident block, where the wide build has room: its
; span fills are 32 columns of unrolled code where 256x192's are 256.
;
;   the dirty-band rule   ten 8K strips, not six bands, so a page's dirty set is a WORD
;   the glyph             the engine's own 8x8 font, eight pixels a cell, forty cells (video.cpp:299)
;
; The 256x192 versions, in src/aw.asm, are not assembled in this build.

;-----------------------------------------------------------------------------
; DIRTY STRIPS. The rule is dirty_band's in src/aw.asm, word for byte: dt_origin[p] is the page p
; was last copied from while it still mirrors it, dt_dirty[p] the strips drawn into since.
;-----------------------------------------------------------------------------

; dirty_band - A = a strip about to be drawn into, on the page pg_ptr1 names. Keeps AF, BC, DE.
;
; ON THE ROW WALK'S PATH in this build: a span that crosses strips calls band_set at every crossing,
; and the next row maps its first strip again. So the work is cut to what changes anything:
; dt_unmirror only when some page mirrors this one (dt_isrc), and the strip's bit from a table.
dirty_band:
        push    af
        push    bc
        ld      b, a
        ld      a, (pg_ptr1)
        ld      c, a
        ld      hl, dt_isrc
        add     a, l
        ld      l, a                    ; dt_isrc does not straddle a 256-byte boundary: ASSERTed
        ld      a, (hl)
        or      a
        call    nz, dt_unmirror         ; this page is changing: nothing mirrors it any more
        ld      a, b
        add     a, a
        ld      hl, dt_bits
        add     a, l
        ld      l, a                    ; nor does dt_bits
        ld      a, (hl)
        inc     hl
        ld      h, (hl)
        ld      l, a                    ; HL = 1 << strip
        ld      a, c
        add     a, a
        add     a, low dt_dirty
        ld      c, a
        ld      b, high dt_dirty        ; BC = &dt_dirty[page]; the table does not straddle either
        ld      a, (bc)
        or      l
        ld      (bc), a
        inc     c
        ld      a, (bc)
        or      h
        ld      (bc), a
        pop     bc
        pop     af
        ret

; dirty_box - poly_draw's box, x1..x2 in (p_x1) and (p_x2), is about to be drawn into page pg_ptr1.
; Marks every strip it covers, once a polygon, so band_set - called at every strip a span crosses
; and again at the next row's first - does no dirty work at all. The box is the polygon's x extent
; give or take the odd pixel (see x2 below). Keeps nothing.
dirty_box:
        ld      hl, (p_x1)              ; x1, clipped to 0
        bit     7, h
        jr      z, .x1
        ld      hl, 0
.x1:    call    .strip
        ld      b, a                    ; B = the first strip
        ; x2 + 1, clipped to 319: a point's offset can reach bbw where the box's right edge is
        ; ptx + bbw / 2, a pixel short when bbw is odd. Marking only to x2 left that pixel's strip
        ; clean - check-intro320's blit 180 found it, one pixel at x 160, the next copy skipping it.
        ld      hl, (p_x2)
        inc     hl
        ld      de, SCR_W - 1
        or      a
        sbc     hl, de
        add     hl, de
        jr      c, .x2
        ex      de, hl
.x2:    call    .strip                  ; A = the last strip
        ; mask = (2 << last) - (1 << first)
        add     a, a
        ld      hl, dt_bits
        add     a, l
        ld      l, a
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ex      de, hl
        add     hl, hl                  ; 2 << last
        ld      a, b
        add     a, a
        ld      de, dt_bits
        add     a, e
        ld      e, a
        ld      a, (de)
        ld      c, a
        inc     de
        ld      a, (de)
        ld      b, a                    ; BC = 1 << first
        or      a
        sbc     hl, bc
        ex      de, hl                  ; DE = the mask
        ld      a, (pg_ptr1)
        ld      c, a
        ld      hl, dt_isrc
        add     a, l
        ld      l, a
        ld      a, (hl)
        or      a
        call    nz, dt_unmirror         ; the page is changing: nothing mirrors it any more
        ld      a, c
        add     a, a
        add     a, low dt_dirty
        ld      l, a
        ld      h, high dt_dirty
        ld      a, (hl)
        or      e
        ld      (hl), a
        inc     l
        ld      a, (hl)
        or      d
        ld      (hl), a
        ret
; HL = x, 0..319: A = x >> 5
.strip: ld      a, l
        rlca
        rlca
        rlca
        and     7
        bit     0, h
        ret     z
        or      8
        ret

; dt_forget - A = a page overwritten outright. Keeps AF and BC.
dt_forget:
        push    af
        push    bc
        ld      c, a
        call    dt_unmirror
        ld      hl, dt_origin
        ld      b, 0
        add     hl, bc
        ld      (hl), $FF
        pop     bc
        pop     af
        ret

; dt_unmirror - C = a page that is changing. Every page recorded as a copy of it stops being one.
; Keeps BC and DE.
dt_unmirror:
        push    bc
        ld      hl, dt_origin
        ld      a, c
        ld      b, 4
.one:   cp      (hl)
        jr      nz, .next
        ld      (hl), $FF
.next:  inc     hl
        djnz    .one
        pop     bc
        ld      hl, dt_isrc             ; nothing mirrors it now
        ld      a, c
        add     a, l
        ld      l, a
        ld      (hl), 0
        ret

; dt_copy_mask - a plain copy of (cp_sidx) onto (cp_didx) is about to run. Leaves the strips it
; must move in cp_mask, and records the destination as a fresh copy of the source.
dt_copy_mask:
        ld      hl, 0
        ld      (cp_mask), hl
        ld      a, (cp_didx)
        ld      c, a
        ld      a, (cp_sidx)
        cp      c
        ret     z                       ; the same page both ends: the reference returns too
        call    dt_unmirror             ; the destination is changing (keeps C)
        ld      hl, dt_origin
        ld      b, 0
        add     hl, bc
        ld      a, (cp_sidx)
        cp      (hl)
        ld      (hl), a                 ; from now on it mirrors this source
        push    af                      ; (the flags: did it already?)
        ld      hl, dt_isrc
        add     a, l
        ld      l, a
        ld      (hl), 1                 ; and the source is mirrored by someone
        pop     af
        ld      a, 0
        jr      nz, .fresh
        inc     a                       ; it already mirrored this source: only its dirty strips
.fresh:
        ld      hl, dt_dirty
        add     hl, bc
        add     hl, bc
        ld      e, (hl)
        ld      (hl), b                 ; B is 0: the destination is clean from now on
        inc     hl
        ld      d, (hl)
        ld      (hl), b
        or      a
        jr      nz, .have
        ld      de, (1 << BANDS) - 1    ; every strip
.have:  ld      (cp_mask), de
        ret

; dt_reset - every page restored from somewhere else: nothing mirrors anything.
dt_reset:
        ld      a, $FF
        ld      (dt_origin), a
        ld      (dt_origin + 1), a
        ld      (dt_origin + 2), a
        ld      (dt_origin + 3), a
        ld      hl, 0
        ld      (dt_isrc), hl
        ld      (dt_isrc + 2), hl
        ret

        EXPORT dt_origin
dt_origin:      db $FF, $FF, $FF, $FF
        EXPORT dt_dirty
dt_dirty:       dw 0, 0, 0, 0
        ASSERT (dt_dirty & $FF) <= 248   ; dirty_band indexes it by adding to the low byte
dt_isrc:        db 0, 0, 0, 0   ; non-zero: some page may mirror this one (stale-set is safe: slow)
        ASSERT (dt_isrc & $FF) <= 252
dt_bits:        dw 1, 2, 4, 8, 16, 32, 64, 128, 256, 512
        ASSERT (dt_bits & $FF) <= 236
cp_sidx:        db 0
cp_didx:        db 0
cp_mask:        dw 0

;-----------------------------------------------------------------------------
; draw_char6 - the 320x256 build's glyph: drawChar, video.cpp:299-330, at one byte a pixel. A = the
; character, at (str_x) cells and (str_y) rows, in (str_col). Eight pixels a cell and no scale, so
; a glyph is eight columns inside one 32-column 8K page: one page for the whole glyph, a column a
; pixel (`inc h`), a row a line (`inc l`). The name is the 256x192 one, which the caller uses.
;-----------------------------------------------------------------------------
draw_char6:
        sub     $20
        ret     c                       ; below space: nothing to draw
        cp      96
        ret     nc
        ld      l, a
        ld      h, 0
        add     hl, hl
        add     hl, hl
        add     hl, hl                  ; * 8 rows
        ld      de, FONT6_AT - $E000 + TEXT_WIN
        add     hl, de
        ld      (gl_src), hl
        ld      a, (str_y)
        cp      193
        ret     nc                      ; y <= 192, as drawChar requires
        ld      (gl_y), a
        ld      a, (str_x)
        cp      40
        ret     nc                      ; x <= 39, as drawChar requires
        ld      b, a
        rrca
        rrca
        and     $3F                     ; the strip, x * 8 >> 5
        ; THROUGH ITS OWN WINDOW, DWIN on MMU7, mapped for every glyph: the rasteriser's strips are
        ; 64 columns in the segment's window and cur_band is theirs, and the text page is at $4000.
        call    dirty_band              ; text draws into this strip too
        ld      hl, dst_p0
        add     a, (hl)
        nextreg NR_DWIN_MMU, a
        ld      a, b
        and     3
        add     a, a
        add     a, a
        add     a, a                    ; (x * 8) & 31, the glyph's first column in the strip
        add     a, DWIN >> 8
        ld      h, a
        ld      a, (gl_y)
        ld      l, a
        ld      b, 8                    ; eight rows
.row:
        ld      de, (gl_src)
        ld      a, (de)                 ; the glyph row
        inc     de
        ld      (gl_src), de
        ld      c, a
        ld      a, (str_col)
        ld      d, a                    ; D = the colour
        push    hl
        ld      e, 8                    ; eight columns
.col:
        rl      c                       ; the top bit out into carry
        jr      nc, .skip
        ld      (hl), d
.skip:
        inc     h
        dec     e
        jr      nz, .col
        pop     hl
        inc     l
        djnz    .row
        ret

;-----------------------------------------------------------------------------
; wide_display - at boot: the picture's 200 rows in the middle of the screen's 256. Layer 2's Y offset
; (NextReg $17) shows memory row 0 on screen row 28, and the clip window (NextReg $18: x1, x2, y1,
; y2, with x counted in pairs of pixels in this mode) shows rows 28-227 only, so the 56 rows each
; column has spare, 200-255, are never seen.
;-----------------------------------------------------------------------------
WIDE_TOP        EQU 28

wide_display:
        nextreg $17, 256 - WIDE_TOP
        nextreg $1C, %00000001          ; the Layer 2 clip index back to x1
        nextreg $18, 0
        nextreg $18, 159
        nextreg $18, WIDE_TOP
        nextreg $18, WIDE_TOP + 199
        ret
