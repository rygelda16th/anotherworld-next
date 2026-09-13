;-----------------------------------------------------------------------------
; AW step 0: what does ONE polygon span cost, end to end?
;
; The host measurement over 12,000 frames of real bytecode says the worst frame
; draws 4,004 spans of ~22 bytes mean, and that per-span OVERHEAD rivals the
; stores at that length. So this times the whole per-scanline operation - step
; both 16.16 edge accumulators, derive x1/x2, clip, work out the band and the
; address, dispatch on fill mode, fill - and not just the fill.
;
; One pass = SPANS spans. The checker divides emulated T-states by SPANS.
; (mode) selects what runs, so overhead and each fill mode can be separated
; inside one build - the same trick src/dmatest.asm uses for DMA vs LDIR.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

SPANS       EQU 1000
SPANLEN     EQU 22              ; measured mean, bytes at 256 wide
L2_BANK     EQU 12              ; first 16K bank of Layer 2 page 0
L2_PAGE0    EQU L2_BANK * 2     ; = 8K page 24, the first 32 scanlines
NR_TURBO    EQU $07
NR_MMU3     EQU $53
NR_L2_BANK  EQU $12
NR_L2_CFG   EQU $70
WIN         EQU $6000           ; MMU3: 32 scanlines of Layer 2

MODE_FULL_STORE EQU 0           ; whole span loop, unrolled stores
MODE_OVERHEAD   EQU 1           ; whole span loop, no fill at all
MODE_FILL_STORE EQU 2           ; fill only, unrolled stores
MODE_FILL_PUSH  EQU 3           ; fill only, PUSH
MODE_FILL_BLEND EQU 4           ; fill only, OR 8 (AW colour 0x10)
MODE_FILL_COPY  EQU 5           ; fill only, copy from page 0 (AW colour 0x11)
MODE_NULL       EQU 6           ; nothing: the harness's own per-span cost
MODE_WRAP       EQU 7           ; the fill wrapper with no fill
DEST            EQU WIN + (3 * 256) + 40

        ORG $8000
start:
        di
        ld      sp, $BF00

        nextreg NR_TURBO, 3             ; 28 MHz
        nextreg NR_L2_CFG, 0            ; 256x192, 8bpp
        nextreg NR_L2_BANK, L2_BANK
        nextreg NR_MMU3, L2_PAGE0       ; scanlines 0-31 at $6000

        ; A source row for the copy-from-background mode. Page 0's own first
        ; 8K would do on hardware; here a RAM row keeps the two independent.
        ld      hl, srcrow
        ld      de, srcrow + 1
        ld      bc, 255
        ld      (hl), $3C
        ldir

        ; ---- correctness first: one span, known place, known colour -------
        ; A benchmark of wrong code measures nothing, so the checker verifies
        ; these bytes before it believes any timing.
        ld      hl, WIN + (7 * 256) + 100       ; y=7, x=100 - clear of the loop
        ld      a, $2A
        ld      b, SPANLEN
.probe: ld      (hl), a
        inc     l
        djnz    .probe
        ld      a, $5A
        ld      (ready), a

;-----------------------------------------------------------------------------
; The timed loop.
;-----------------------------------------------------------------------------
main:
        ; A hold, for the same reason snd_hold exists in wolf3d-next: the loop
        ; walks MMU3 across all six bands, so a checker reading $6000 gets
        ; whichever page the loop happens to be on. Held, slot 3 is put back to
        ; page 0 and stays there for the length of a read.
        ld      a, (hold)
        or      a
        jr      z, .go
        nextreg NR_MMU3, L2_PAGE0
.held:  ld      a, (hold)
        or      a
        jr      nz, .held
        ld      a, 255                  ; force the next span to rewrite MMU3
        ld      (cur_band), a
.go:
        call    one_pass
        ld      hl, (passes)
        inc     hl
        ld      (passes), hl
        jr      main

one_pass:
        ; reset the edge state so every pass does identical work
        ld      hl, $7FFF
        ld      (cpt1), hl
        ld      hl, 40
        ld      (cpt1+2), hl            ; x1 = 40
        ld      hl, $8000
        ld      (cpt2), hl
        ld      hl, 40 + SPANLEN - 1
        ld      (cpt2+2), hl            ; x2 = 61
        xor     a
        ld      (cur_y), a
        ld      a, 255
        ld      (cur_band), a

        ; Pick the routine ONCE. The inner loop is then byte-identical for every
        ; mode, so (mode X) - (mode NULL) is the routine's own cost and nothing
        ; else. Reading (mode) per span, as this did first, made every figure
        ; carry the loop and the dispatch and the decomposition came out
        ; negative.
        ld      a, (mode)
        add     a, a
        ld      e, a
        ld      d, 0
        ld      hl, mode_table
        add     hl, de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ld      (call_op + 1), de       ; the routine
        ld      a, (mode)
        cp      MODE_OVERHEAD
        ld      hl, fill_store
        jr      nz, .tail_set
        ld      hl, ret_only            ; overhead mode: stop before the fill
.tail_set:
        ld      (span_row.tail + 1), hl

        ld      bc, SPANS
pass_loop:
        push    bc
call_op:
        call    0000
        pop     bc
        dec     bc
        ld      a, b
        or      c
        jr      nz, pass_loop
        ret

mode_table:
        dw      span_row        ; 0 whole loop + fill
        dw      span_row        ; 1 whole loop, tail patched to ret
        dw      w_store         ; 2
        dw      w_push          ; 3
        dw      w_blend         ; 4
        dw      w_copy          ; 5
        dw      ret_only        ; 6 NULL - the harness's own cost
        dw      w_null          ; 7 wrapper only, no fill

ret_only:
        ret

; The fill wrappers are byte-identical apart from the final JP, so
; (mode 2..5) - (mode 7) is the fill and nothing else.
w_store:
        ld      hl, DEST
        ld      a, (bench_len)
        ld      c, $2A
        jp      fill_store
w_push:
        ld      hl, DEST
        ld      a, (bench_len)
        ld      c, $2A
        jp      fill_push
w_blend:
        ld      hl, DEST
        ld      a, (bench_len)
        ld      c, $2A
        jp      fill_blend
w_copy:
        ld      hl, DEST
        ld      a, (bench_len)
        ld      c, $2A
        jp      fill_copy
w_null:
        ld      hl, DEST
        ld      a, (bench_len)
        ld      c, $2A
        ret

;-----------------------------------------------------------------------------
; span_row - ONE scanline of a polygon, the whole operation.
;-----------------------------------------------------------------------------
span_row:
        ; --- step the left edge, 16.16 ---
        ld      hl, (cpt1)
        ld      de, (stp1)
        add     hl, de
        ld      (cpt1), hl
        ld      hl, (cpt1+2)
        ld      de, (stp1+2)
        adc     hl, de                  ; carry survives the two LDs
        ld      (cpt1+2), hl
        ld      a, h
        or      a
        jr      z, .x1ok
        bit     7, h
        jr      z, .offright            ; positive and > 255: nothing visible
        ld      l, 0                    ; negative: clip to 0
.x1ok:
        ld      c, l                    ; C = x1

        ; --- step the right edge ---
        ld      hl, (cpt2)
        ld      de, (stp2)
        add     hl, de
        ld      (cpt2), hl
        ld      hl, (cpt2+2)
        ld      de, (stp2+2)
        adc     hl, de
        ld      (cpt2+2), hl
        ld      a, h
        or      a
        jr      z, .x2ok
        bit     7, h
        jr      nz, .offleft            ; negative: nothing visible
        ld      l, 255                  ; > 255: clip right
.x2ok:
        ld      b, l                    ; B = x2

        ld      a, b
        sub     c
        ret     c                       ; x2 < x1: empty
        inc     a                        ; A = length 1..256 (0 means 256)
        ld      (span_len), a

        ; --- the band, and the MMU write only when it changes ---
        ld      a, (cur_y)
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
        add     a, L2_PAGE0
        nextreg NR_MMU3, a
.band_ok:
        ; --- the address: H = $60 + (y & 31), L = x1 ---
        ld      a, e
        and     31
        add     a, WIN >> 8
        ld      h, a
        ld      l, c

        ld      a, e                    ; advance the scanline
        inc     a
        ld      (cur_y), a

        ld      a, (span_len)
        ld      c, $2A                  ; the colour
.tail:
        jp      fill_store              ; patched to ret_only for overhead mode

.offright:
.offleft:
        ld      a, (cur_y)
        inc     a
        ld      (cur_y), a
        ret

;-----------------------------------------------------------------------------
; fill_store - A = length (0 = 256), HL = dest, C = colour.
; Computed entry into an unrolled block of `ld (hl),a / inc l` pairs: 11 T a
; byte, with the entry address patched into a JP so HL stays the destination.
;-----------------------------------------------------------------------------
fill_store:
        ld      d, 0
        ld      e, a
        ex      de, hl                  ; HL = len, DE = dest
        add     hl, hl                  ; 2 bytes per pair
        ex      de, hl                  ; DE = len*2, HL = dest
        push    hl
        ld      hl, store_end
        sbc     hl, de                  ; carry is clear after ADD HL,HL here
        ld      (store_jp + 1), hl
        pop     hl
        ld      a, c                    ; A = the byte to write
store_jp:
        jp      0000                    ; patched above
        ; 256 pairs, so any length 1..256 has an entry point
        DUP 256
        ld      (hl), a
        inc     l
        EDUP
store_end:
        ret

;-----------------------------------------------------------------------------
; fill_push - two bytes per PUSH, the cheapest fill the machine has.
; Writes DOWNWARD from the far end and needs SP inside the framebuffer, so it
; runs with interrupts already off and puts SP back.
;-----------------------------------------------------------------------------
fill_push:
        ; Work out the entry point BEFORE SP moves: once SP is inside the
        ; framebuffer every PUSH is a pixel write, so the scratch push/pop this
        ; used to do landed two bytes of Layer 2.
        ld      d, 0
        ld      e, a                    ; DE = len
        add     hl, de                  ; HL = one past the end
        push    hl                      ; (still on the real stack)
        srl     e                       ; E = pairs
        ld      d, 0                    ; DE = pairs
        ; ONE byte per PUSH HL, not two. The store block above is two bytes a
        ; pair (LD (HL),A + INC L) and copying its *2 here made every PUSH fill
        ; run twice the pushes it should - 44 bytes written for a 22-byte span,
        ; scribbling past the end, and at len 254 the entry landed 126 bytes
        ; before the block and hung the machine.
        or      a                       ; clear carry for the SBC
        ld      hl, push_end
        sbc     hl, de
        ld      (push_jp + 1), hl
        pop     hl                      ; HL = one past the end again
        ld      (push_sp + 1), sp
        ld      sp, hl
        ld      a, c
        ld      h, a
        ld      l, a                    ; HL = colour in both halves
push_jp:
        jp      0000
        DUP 128
        push    hl
        EDUP
push_end:
push_sp:
        ld      sp, 0000
        ret

;-----------------------------------------------------------------------------
; fill_blend - AW colour 0x10: set bit 3 of every pixel already there.
; Read-modify-write, so no fill trick applies: SET 3,(HL) is 15 T a byte.
;-----------------------------------------------------------------------------
fill_blend:
        ld      b, a
.next:  set     3, (hl)
        inc     l
        djnz    .next
        ret

;-----------------------------------------------------------------------------
; fill_copy - AW colour 0x11: copy the same span out of page 0.
;-----------------------------------------------------------------------------
fill_copy:
        ld      de, srcrow
        ld      b, a
.next:  ld      a, (de)
        ld      (hl), a
        inc     de
        inc     l
        djnz    .next
        ret

;-----------------------------------------------------------------------------
        EXPORT ready
ready:      db 0
        EXPORT mode
mode:       db 0
        EXPORT hold
hold:       db 0
        EXPORT bench_len
bench_len:  db SPANLEN              ; the checker sweeps this to fit T/byte
        EXPORT passes
passes:     dw 0
        EXPORT span_len
span_len:   db 0

cpt1:       ds 4
cpt2:       ds 4
cur_y:      db 0
cur_band:   db 255
; TRULY vertical edges, step zero. +0.25 px a scanline was tried first and it
; drifts x1 by 250 pixels over a 1000-span pass, so spans got clipped, changed
; length, and rows were rewritten at different offsets as y wrapped - a moving
; workload, which is not what this is trying to weigh. ADD/ADC cost the same
; whatever the operands, so a zero step measures the same arithmetic and leaves
; every span identical and checkable. The clip tests still execute; only their
; branches are never taken, which understates a clipped span slightly.
stp1:       dw 0, 0
stp2:       dw 0, 0

        ALIGN 256
srcrow:     ds 256

        ASSERT $ < $BF00
        SAVENEX OPEN "build/span.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
