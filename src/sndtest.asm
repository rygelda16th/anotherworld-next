;-----------------------------------------------------------------------------
; E3: the sound player - the ring, the DMA that empties it, and the mixer that
; fills it ahead of the DMA's read pointer.
;
; The architecture is wolf3d-next's, which is proven and measured there: zxnDMA in
; burst mode streams a 2K ring to the DAC on port $DF with WR5 auto-restart, round
; and round, while a tick asks the DMA where it is and mixes into the bytes ahead
; of that. What this port adds, and what is therefore under test here, is
; everything Another World's mixer does that Wolf3D's does not:
;
;   * per-voice resampling. Wolf3D's samples all play at one rate; these span
;     3,327 to 25,031 Hz and each channel has its own 16.8 increment.
;   * 64 volume levels through a table, against nine fixed attenuations.
;   * LOOPS. A looping voice never ends on its own, which is why something is
;     playing 98.3% of the intro.
;
; And the block splitting, which is the design decision that keeps the inner loop
; free of tests: a voice's page boundary, its sample end and its loop point are all
; resolved BEFORE the loop runs, by cutting the block short, rather than by testing
; per sample. That is O(1) a block instead of 18 T a voice a sample.
;
; `make check-mix` priced the inner loop at 295 T an output sample for four voices,
; 23.2% of the machine at 22,050 Hz. This is the same loop in its real setting.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

NR_TURBO        EQU $07
NR_MMU0         EQU $50
NR_MMU1         EQU $51

RING_PAGE       EQU 60                  ; clear of everything else here
RING_WIN        EQU $0000               ; MMU0: the ring, where the DMA reads it
SAMP_PAGE       EQU 62                  ; the sample, two pages at MMU1... see below
SAMP_WIN        EQU $2000               ; MMU1: where a sample page appears
NR_SAMP_MMU     EQU $51

; 875 kHz / prescalar is the byte rate, so 22,050 Hz wants 39.7 and 40 gives
; 21,875 - a tenth of a semitone flat, and the closest the divider allows.



        ORG $8000
        jp      start

isr:
        push    af
        push    hl
        ld      hl, (ticks)
        inc     hl
        ld      (ticks), hl
        pop     hl
        pop     af
        ei
        reti

VEC_FILL        EQU $BD
VEC_TABLE       EQU $BC00
VEC_TRAMP       EQU (VEC_FILL << 8) | VEC_FILL

start:
        di
        ld      sp, $BB00
        nextreg NR_TURBO, 3

        ; the volume table, as check-mix verified it: clamp(int8 * VOLUME / 64)
        nextreg NR_MMU1, SAMP_PAGE
        ld      hl, voltab
        ld      b, 0
.vt:
        ld      a, b
        push    bc
        push    hl
        call    scale_byte
        pop     hl
        pop     bc
        ld      (hl), a
        inc     hl
        inc     b
        jr      nz, .vt

        ; a ramp for a sample, so a wrong pointer shows as a wrong value
        nextreg NR_MMU1, SAMP_PAGE
        ld      hl, sampbuf
        ld      de, 1024
.sb:
        ld      a, l
        ld      (hl), a
        inc     hl
        dec     de
        ld      a, d
        or      e
        jr      nz, .sb

        ; the ring: silence, which for a DAC centred at 128 is 128
        nextreg NR_MMU0, RING_PAGE
        ld      hl, RING_WIN
        ld      de, RING_WIN + 1
        ld      bc, RING_LEN - 1
        ld      (hl), 128
        ldir

        ; IM 2, 257 bytes of table, and its trampoline clear of the code
        ld      a, VEC_TABLE >> 8
        ld      i, a
        ld      hl, VEC_TABLE
        ld      de, VEC_TABLE + 1
        ld      bc, 256
        ld      (hl), VEC_FILL
        ldir
        ld      hl, VEC_TRAMP
        ld      (hl), $C3
        inc     hl
        ld      (hl), isr & $FF
        inc     hl
        ld      (hl), isr >> 8
        im      2
        ei

        ld      a, $5A
        ld      (ready), a

main:
        ld      a, (go)
        or      a
        jr      z, main
        xor     a
        ld      (go), a

        ld      a, (what)
        cp      1
        jp      z, do_mix
        cp      2
        jp      z, do_dma
.done:
        ld      a, $5A
        ld      (done), a
        jr      main

;-----------------------------------------------------------------------------
; do_mix - the DMA stays stopped. Set the four voices up from what the checker
; poked, mix exactly (mix_len) samples into the ring from its start, and stop.
; Deterministic, so the host can compute the same bytes.
;-----------------------------------------------------------------------------
do_mix:
        call    setup_voices
        ld      a, (mix_len)
        ld      (blocklen), a
        ld      hl, RING_WIN
        ld      (mix_dst), hl

        ; the first ACTIVE voice stores; the rest accumulate
        ld      ix, voice0
        ld      b, 4
        ld      c, 0                    ; C = have we stored yet
.each:
        ld      a, (ix + V_ACTIVE)
        or      a
        jr      z, .next
        ld      a, c
        or      a
        jr      nz, .accum
        push    bc
        call    mix_voice_first
        pop     bc
        ld      c, 1
        jr      .next
.accum:
        push    bc
        call    mix_voice_add
        pop     bc
.next:
        ld      de, V_SIZE
        add     ix, de
        dec     b
        jp      nz, .each

        ; nothing active at all: the ring is silence, and 128 is what that means
        ld      a, c
        or      a
        jp      nz, main.done
        nextreg NR_MMU0, RING_PAGE
        ld      hl, RING_WIN
        ld      a, (mix_len)
        ld      b, a
.sil:   ld      (hl), 128
        inc     hl
        djnz    .sil
        jp      main.done

;-----------------------------------------------------------------------------
; do_dma - programme the DMA to stream the ring to the DAC round and round, then
; sample its port A address every 20 ms so the checker can fit the rate.
;-----------------------------------------------------------------------------
do_dma:
        nextreg NR_MMU0, RING_PAGE
        ld      hl, dma_prog
        ld      b, dma_prog_end - dma_prog
        ld      c, DMA_PORT
        otir

        ld      hl, dma_log
        ld      a, (dma_samples)
        ld      b, a
.sample:
        push    bc
        push    hl
        call    wait_tick
        pop     hl
        ld      bc, DMA_PORT
        ld      a, $A7                  ; WR6: read the counter and addresses
        out     (c), a
        in      a, (c)                  ; port A address, low
        ld      (hl), a
        inc     hl
        in      a, (c)                  ; high
        ld      (hl), a
        inc     hl
        pop     bc
        djnz    .sample

        ld      bc, DMA_PORT
        ld      a, $83                  ; DISABLE, which the patched emulator
        out     (c), a                  ; honours; then RESET, which it also does
        ld      a, $C3
        out     (c), a
        jp      main.done

wait_tick:
        ld      hl, (ticks)
.w:     ld      de, (ticks)
        ld      a, d
        cp      h
        jr      nz, .done
        ld      a, e
        cp      l
        jr      z, .w
.done:  ret

        ; the DMA programme and the mixer now live in src/inc/sound.inc,
        ; so this harness and the game run the same instructions.
RING_ADDR       EQU RING_WIN

        MACRO SND_MAP_PAGES
        nextreg NR_MMU0, RING_PAGE
        nextreg NR_MMU1, SAMP_PAGE
        ENDM

        INCLUDE "src/inc/sound.inc"


;-----------------------------------------------------------------------------
; setup_voices - four records from what the checker poked. Each voice's block is
; SPLIT before it runs, so the inner loop has no tests in it: the length is cut to
; whichever comes first of the requested block, the sample's end, and the page
; boundary. Cutting at the loop point is the same arithmetic.
;-----------------------------------------------------------------------------
setup_voices:
        ld      ix, voice0
        ld      iy, poke_voices
        ld      b, 4
.one:
        ld      a, (iy + 0)             ; active
        ld      (ix + V_ACTIVE), a
        ld      a, (iy + 1)             ; frac
        ld      (ix + V_FRAC), a
        ld      a, (iy + 2)             ; start offset, low
        ld      e, a
        ld      a, (iy + 3)
        ld      d, a
        ld      hl, sampbuf
        add     hl, de
        ld      (ix + V_POS), l
        ld      (ix + V_POS + 1), h
        ld      a, (iy + 4)             ; inc frac
        ld      (ix + V_INCF), a
        ld      a, (iy + 5)             ; inc int, low
        ld      (ix + V_INCI), a
        ld      a, (iy + 6)
        ld      (ix + V_INCI + 1), a
        ld      a, voltab >> 8
        ld      (ix + V_VOL), a
        ld      de, V_SIZE
        add     ix, de
        ld      de, 8
        add     iy, de
        dec     b
        jp      nz, .one
        ret

;-----------------------------------------------------------------------------
        EXPORT ready
ready:      db 0
        EXPORT go
go:         db 0
        EXPORT done
done:       db 0
        EXPORT what
what:       db 0            ; 1 = mix a block, 2 = run the DMA and watch it
        EXPORT ticks
ticks:      dw 0
        EXPORT mix_len
mix_len:    db 0
blocklen:   db 0
mix_dst:    dw 0
        EXPORT dma_samples
dma_samples: db 0
        EXPORT dma_log
dma_log:    ds 2 * 64
        EXPORT poke_voices
poke_voices: ds 8 * 4       ; active, frac, start lo/hi, incf, inci lo/hi, spare
        EXPORT prescalar_used
prescalar_used: db PRESCALAR

        ALIGN 16
voice0:     ds V_SIZE * 4

        ASSERT $ < VEC_TABLE
        ORG     $2000               ; MMU1: the volume table and the sample
        ALIGN 256
voltab:     ds 256
sampbuf:    ds 1024

        SAVENEX OPEN "build/sndtest.nex", $8000, $BB00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
