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
NR_MMU0         EQU $50
NR_MMU1         EQU $51
SEG_WIN         EQU $0000       ; MMU0 + MMU1: 16K of the polygon segment
NR_SEG_MMU_LO   EQU $50         ; the segment window's two slots
NR_SEG_MMU_HI   EQU $51
NR_DWIN_MMU     EQU $53                 ; which slot each of those is
NR_SWIN_MMU     EQU $52

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

        ; C4's driver. In read mode the checker has poked a polygon segment into
        ; banked pages and a list of top-level draws, each one exactly what a
        ; bit-7 or bit-6 opcode computes, and the reader is what turns them into
        ; polygons. The vector path below is untouched, so Gate C still runs.
        ld      a, (read_mode)
        or      a
        jp      z, .draw_all
        ld      hl, (rd_count)
        ld      a, h
        or      l
        jp      z, .drawn
        ld      (rd_left), hl
        ld      hl, rd_list
        ld      (rd_next), hl
.read_each:
        ld      hl, (rd_next)
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      (rd_off), de
        ld      a, (hl)
        inc     hl
        ld      (rd_col), a
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      (rd_zoom), de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      (rd_ptx), de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        inc     hl
        ld      (rd_pty), de
        ld      (rd_next), hl
        xor     a
        ld      (rd_depth), a
        call    poly_read
        ld      a, (rd_stop)
        or      a
        jp      nz, .drawn
        ld      hl, (rd_left)
        dec     hl
        ld      (rd_left), hl
        ld      a, h
        or      l
        jp      nz, .read_each
        jp      .drawn

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

        INCLUDE "src/inc/raster.inc"

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
        ORG     $C000
cs_results:     ds CS_COUNT * 6         ; step (4 bytes) then dy (2) per case
        ; The draw list the checker pokes: off, colour, zoom, x, y per entry,
        ; nine bytes, which is exactly what the two opcode forms compute.
        EXPORT rd_list
rd_list:        ds 9 * 256
        EXPORT rd_log
rd_log:         ds 8 * 32       ; off, colour, ptx, pty per leaf, as read
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
