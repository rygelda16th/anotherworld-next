;-----------------------------------------------------------------------------
; AW step 1: what does ONE OUTPUT SAMPLE of the mixer cost?
;
; First step in the plan because it is the largest unpriced cost in the project.
; The host measurement says sound is live 98.3% of the intro at a mean of 2.83
; voices, so the mixer is a permanent tax on the frame budget, not an occasional
; one - and the three candidate output rates were costed by scaling
; wolf3d-next's measurement of a mixer that does none of the three things this
; one must: resample per voice, scale through 64 volume levels, and loop.
;
; One pass = (blocklen) output samples. The checker fits T against blocklen over
; several lengths, so the per-sample figure does not carry the block setup.
; MODE_NULL is the harness's own cost and is subtracted from everything else -
; the same arrangement as src/span.asm.
;
; Registers in every inner loop. The split across the two banks is what makes
; the advance branchless, so it is worth stating:
;     main    HL = sample pointer   DE = integer increment   C = fraction
;             B = samples left      A = scratch
;     shadow  HL' = mix buffer      DE' = volume table (D' page, E' index)
; The fractional add sets carry, LD does not disturb it, so ADC HL,DE applies
; the integer increment and the fraction's carry in one 15 T instruction. The
; first draft of this used JR NC / INC HL and cost 14 T a sample more.
;
; What is deliberately NOT in the inner loop, and why that is honest:
;   * the page-boundary test. A voice advances at most ceil(inc) * blocklen
;     bytes in a block, so the block is SPLIT at the boundary before the loop
;     runs - O(1) a block, not a sample.
;   * the sample-end and loop-point tests, split the same way.
; That splitting is the real design. A per-sample test would cost 18 T a voice
; and there is no reason to pay it.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

MIXLEN      EQU 128             ; output samples a block; wolf3d-next's lead
VOLUME      EQU 48              ; of 63: a loud but not maximal voice
NR_TURBO    EQU $07

MODE_NULL   EQU 0               ; nothing: the harness's own per-block cost
MODE_ADV    EQU 1               ; advance only - the floor under any mixer
MODE_V1     EQU 2               ; 1 voice, table volume, STORE (the first voice)
MODE_V1A    EQU 3               ; 1 voice, table volume, ACCUMULATE + saturate
MODE_V4     EQU 4               ; 4 voices: 1 store + 3 accumulate <- the number
MODE_V1U    EQU 5               ; 1 voice accumulate, unrolled x4
MODE_V4U    EQU 6               ; 4 voices, unrolled x4
MODE_MUL    EQU 7               ; 1 voice, Z80N MUL D,E instead of the table
MODE_BIAS   EQU 8               ; a separate signed -> DAC-unsigned pass
MODE_INTERP EQU 9               ; 1 voice with the reference's interpolation

; A voice record. `pos` is a REAL ADDRESS in the sample window, not an index, so
; the advance is a 24.8 add straight onto the pointer and the fetch is one
; LD A,(HL). Converting an index to an address per sample would cost more than
; the fetch does.
V_FRAC      EQU 0               ; 0.8 fractional position
V_POS       EQU 1               ; word: pointer into the sample window
V_INCF      EQU 3               ; 0.8 fractional increment
V_INCI      EQU 4               ; word: integer increment
V_VOL       EQU 6               ; high byte of this voice's 256-byte volume table
V_SIZE      EQU 8

        ORG $8000
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3             ; 28 MHz

        ; ---- the volume table -------------------------------------------
        ; tbl[b] = clamp((int8)b * VOLUME / 64), the reference's
        ; `(int)b * ch->volume / 0x40` (mixer.cpp:141). One level is enough to
        ; time the lookup; the shipped set is 64 of these, 16,384 bytes, which
        ; is exactly two 8K pages.
        ld      hl, voltab
        ld      b, 0                    ; 256 iterations, B wrapping to 0
vt_loop:
        ld      a, b
        push    bc
        push    hl
        call    scale_byte
        pop     hl
        pop     bc
        ld      (hl), a
        inc     hl
        inc     b
        jr      nz, vt_loop

        ; ---- the sample -------------------------------------------------
        ; A ramp, so a wrong pointer or a wrong increment shows up as a wrong
        ; value rather than as plausible noise.
        ld      hl, sampbuf
        ld      de, 512
sb_loop:
        ld      a, l
        ld      (hl), a
        inc     hl
        dec     de
        ld      a, d
        or      e
        jr      nz, sb_loop

        ; ---- correctness before timing ----------------------------------
        ; A benchmark of wrong code measures nothing. Mix one voice over a
        ; short block and let the checker verify the bytes against a host
        ; computation before it believes any figure.
        call    setup_voices
        ld      a, 8
        ld      (blocklen), a
        ld      ix, voice0
        call    mix_first
        ld      a, $5A
        ld      (ready), a
        ld      a, MIXLEN
        ld      (blocklen), a

;-----------------------------------------------------------------------------
; The timed loop.
;-----------------------------------------------------------------------------
main:
        ld      a, (hold)
        or      a
        jr      z, main_go
main_held:
        ld      a, (hold)
        or      a
        jr      nz, main_held
main_go:
        call    one_pass
        ld      hl, (passes)
        inc     hl
        ld      (passes), hl
        jr      main

one_pass:
        call    setup_voices            ; every pass does identical work

        ; Pick the routine ONCE, so (mode X) - (mode NULL) is that routine and
        ; nothing else. Reading (mode) inside the loop, as span.asm's first
        ; draft did, makes every figure carry the dispatch.
        ld      a, (mode)
        add     a, a
        ld      e, a
        ld      d, 0
        ld      hl, mode_table
        add     hl, de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ld      (call_op + 1), de
call_op:
        jp      0000                    ; each routine RETs to one_pass's caller

mode_table:
        dw      ret_only        ; 0 NULL
        dw      r_adv           ; 1
        dw      r_v1            ; 2
        dw      r_v1a           ; 3
        dw      r_v4            ; 4
        dw      r_v1u           ; 5
        dw      r_v4u           ; 6
        dw      r_mul           ; 7
        dw      r_bias          ; 8
        dw      r_interp        ; 9

ret_only:
        ret

r_adv:      ld ix, voice0
            jp mix_advance
r_v1:       ld ix, voice0
            jp mix_first
r_v1a:      ld ix, voice0
            jp mix_add
r_v1u:      ld ix, voice0
            jp mix_add_u4
r_mul:      ld ix, voice0
            jp mix_mul
r_interp:   ld ix, voice0
            jp mix_interp
r_bias:     jp mix_bias

r_v4:
        ld      ix, voice0
        call    mix_first               ; the first active voice stores...
        ld      ix, voice1
        call    mix_add                 ; ...the rest accumulate and saturate
        ld      ix, voice2
        call    mix_add
        ld      ix, voice3
        jp      mix_add

r_v4u:
        ld      ix, voice0
        call    mix_first_u4
        ld      ix, voice1
        call    mix_add_u4
        ld      ix, voice2
        call    mix_add_u4
        ld      ix, voice3
        jp      mix_add_u4

;-----------------------------------------------------------------------------
; scale_byte - A = a raw byte read as int8; returns clamp(A * VOLUME / 64).
; Init time only: the shipped port has this as a table, not as code. Written as
; magnitude-then-sign because MUL D,E is unsigned - the same shape, and the same
; trap, as the vertex scale.
;-----------------------------------------------------------------------------
scale_byte:
        bit     7, a
        jr      nz, sb_neg
        call    sb_mul
        ret
sb_neg:
        neg
        call    sb_mul
        neg
        ret
sb_mul:
        ld      e, a
        ld      d, VOLUME
        mul     d, e                    ; Z80N: D*E -> DE, unsigned
        ld      a, e                    ; >> 6 of the 16-bit product
        ld      b, d
        srl     b
        rr      a
        srl     b
        rr      a
        srl     b
        rr      a
        srl     b
        rr      a
        srl     b
        rr      a
        srl     b
        rr      a
        ret

;-----------------------------------------------------------------------------
; setup_voices - the state for one pass. Four different increments, so no two
; voices walk their sample in step and the measurement cannot accidentally
; benefit from a shared pattern.
;
; inc = (freq << 8) / rate, the reference's chunkInc (mixer.cpp:44), as 16.8,
; at an 11,025 Hz output rate and against real rates from the trace:
;   voice 0  10,559 Hz -> 0.958 -> 0.F5      voice 1  25,031 Hz -> 2.270 -> 2.45
;   voice 2   3,327 Hz -> 0.302 -> 0.4D      voice 3  14,915 Hz -> 1.353 -> 1.5A
;-----------------------------------------------------------------------------
setup_voices:
        ld      ix, voice0
        ld      iy, voice_incs
        ld      hl, sampbuf
        ld      b, 4
sv_loop:
        ld      (ix + V_POS), l
        ld      (ix + V_POS + 1), h
        xor     a
        ld      (ix + V_FRAC), a
        ld      a, (iy + 0)
        ld      (ix + V_INCF), a
        ld      a, (iy + 1)
        ld      (ix + V_INCI), a
        ld      a, (iy + 2)
        ld      (ix + V_INCI + 1), a
        ld      a, voltab >> 8
        ld      (ix + V_VOL), a
        ; next voice, and a different start so the four do not share a pointer
        ld      de, V_SIZE
        add     ix, de
        ld      de, 3
        add     iy, de
        ld      de, 32
        add     hl, de
        dec     b
        jr      nz, sv_loop
        ret

voice_incs:
        db $F5
        dw 0
        db $45
        dw 2
        db $4D
        dw 0
        db $5A
        dw 1

;-----------------------------------------------------------------------------
; voice_regs - load a voice into the registers the inner loops expect, and
; patch its fractional increment into every immediate that needs it.
;
; The patch sites are LABELLED, not counted. The first draft of this file
; computed byte offsets by hand, which is the same class of mistake as the
; band's three RRCA: it assembles, it runs, and it is wrong somewhere else.
;-----------------------------------------------------------------------------
voice_regs:
        ld      a, (ix + V_INCF)
        ld      (p_adv + 1), a
        ld      (p_first + 1), a
        ld      (p_add + 1), a
        ld      (p_mul + 1), a
        ld      (p_int + 1), a
        ld      (p_fu0 + 1), a
        ld      (p_fu1 + 1), a
        ld      (p_fu2 + 1), a
        ld      (p_fu3 + 1), a
        ld      (p_au0 + 1), a
        ld      (p_au1 + 1), a
        ld      (p_au2 + 1), a
        ld      (p_au3 + 1), a

        ld      l, (ix + V_POS)
        ld      h, (ix + V_POS + 1)
        ld      e, (ix + V_INCI)
        ld      d, (ix + V_INCI + 1)
        ld      c, (ix + V_FRAC)
        ld      a, (blocklen)
        ld      b, a
        ld      a, (ix + V_VOL)
        exx
        ld      hl, mixbuf
        ld      d, a
        exx
        ret

voice_save:
        ld      (ix + V_POS), l
        ld      (ix + V_POS + 1), h
        ld      (ix + V_FRAC), c
        ret

;-----------------------------------------------------------------------------
; mix_advance - the advance and nothing else: the floor under any mixer.
;-----------------------------------------------------------------------------
mix_advance:
        call    voice_regs
ma_loop:
        ld      a, c
p_adv:  add     a, 0                    ; patched: the fractional increment
        ld      c, a
        adc     hl, de
        dec     b
        jp      nz, ma_loop
        jp      voice_save

;-----------------------------------------------------------------------------
; mix_first - the first active voice: scale and STORE. No read-modify-write and
; no saturation, because nothing is there yet to overflow. The bias to the DAC's
; unsigned centre is folded in here for one XOR, which is why there is no
; separate pass for it - see MODE_BIAS for what that would have cost.
;-----------------------------------------------------------------------------
mix_first:
        call    voice_regs
mf_loop:
        ld      a, (hl)                 ; the raw sample
        exx
        ld      e, a
        ld      a, (de)                 ; scaled by volume
        xor     $80                     ; signed -> DAC unsigned, free here
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_first:
        add     a, 0                    ; patched
        ld      c, a
        adc     hl, de
        dec     b
        jp      nz, mf_loop
        jp      voice_save

;-----------------------------------------------------------------------------
; mix_add - every voice after the first. The buffer is DAC-unsigned with 128 as
; silence, so this is an unsigned add of a signed delta and the saturation test
; is on the delta's sign, decided before the add.
;-----------------------------------------------------------------------------
mix_add:
        call    voice_regs
mad_loop:
        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)                 ; A = the signed delta
        bit     7, a
        jr      nz, mad_neg
        add     a, (hl)
        jr      nc, mad_st
        ld      a, 255                  ; saturate high
        jr      mad_st
mad_neg:
        add     a, (hl)
        jr      c, mad_st
        xor     a                       ; saturate low
mad_st:
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_add:  add     a, 0                    ; patched
        ld      c, a
        adc     hl, de
        dec     b
        jp      nz, mad_loop
        jp      voice_save

;-----------------------------------------------------------------------------
; mix_mul - the same voice with Z80N's MUL D,E instead of a table, to price the
; 16K the 64 tables cost.
;-----------------------------------------------------------------------------
mix_mul:
        call    voice_regs
mm_loop:
        ld      a, (hl)
        exx
        push    bc
        bit     7, a
        jr      nz, mm_neg
        call    mm_scale
        jr      mm_have
mm_neg:
        neg
        call    mm_scale
        neg
mm_have:
        pop     bc
        xor     $80
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_mul:  add     a, 0                    ; patched
        ld      c, a
        adc     hl, de
        dec     b
        jp      nz, mm_loop
        jp      voice_save

mm_scale:
        push    de
        ld      e, a
        ld      d, VOLUME
        mul     d, e
        ld      a, e
        ld      b, d
        srl     b
        rr      a
        srl     b
        rr      a
        srl     b
        rr      a
        srl     b
        rr      a
        srl     b
        rr      a
        srl     b
        rr      a
        pop     de
        ret

;-----------------------------------------------------------------------------
; mix_interp - what the reference's linear interpolation costs.
;   b = (b1 * (0xFF - f) + b2 * f) >> 8              (mixer.cpp:138-140)
; Two multiplies and a second fetch a sample. Worked on DAC-biased values so
; MUL D,E stays usable; the reference works signed and clamps later, which is
; the same curve shifted. Priced, not assumed: interpolation exists to soften
; the aliasing of an Amiga sample played at the wrong rate, and whether that is
; audible here is a listening question, not an arithmetic one.
;-----------------------------------------------------------------------------
mix_interp:
        call    voice_regs
mi_loop:
        push    bc                      ; C = the fraction, needed after
        push    de                      ; DE = the integer increment
        ld      a, (hl)
        xor     $80                     ; b1, biased
        ld      b, a
        inc     hl
        ld      a, (hl)
        dec     hl
        xor     $80                     ; b2, biased
        ld      e, a
        ld      d, c
        mul     d, e                    ; b2 * f
        push    de
        ld      a, c
        neg                             ; 256 - f
        ld      d, a
        ld      e, b
        mul     d, e                    ; b1 * (256 - f)
        pop     bc
        ex      de, hl
        add     hl, bc
        ld      a, h                    ; >> 8
        ex      de, hl
        exx
        ld      e, a
        ld      a, (de)
        ld      (hl), a
        inc     l
        exx
        pop     de
        pop     bc
        ld      a, c
p_int:  add     a, 0                    ; patched
        ld      c, a
        adc     hl, de
        dec     b
        jp      nz, mi_loop
        jp      voice_save

;-----------------------------------------------------------------------------
; mix_bias - a separate signed-to-unsigned pass, measured only to show why
; mix_first folds it in instead.
;-----------------------------------------------------------------------------
mix_bias:
        ld      hl, mixbuf
        ld      a, (blocklen)
        ld      b, a
mb_loop:
        ld      a, (hl)
        xor     $80
        ld      (hl), a
        inc     l
        dec     b
        jp      nz, mb_loop
        ret

;-----------------------------------------------------------------------------
; The unrolled pair: four samples a turn, so the counter costs a quarter.
; blocklen must be a multiple of 4 for these, which the checker honours.
;-----------------------------------------------------------------------------
mix_first_u4:
        call    voice_regs
        srl     b
        srl     b
mfu_loop:
        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        xor     $80
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_fu0:  add     a, 0
        ld      c, a
        adc     hl, de

        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        xor     $80
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_fu1:  add     a, 0
        ld      c, a
        adc     hl, de

        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        xor     $80
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_fu2:  add     a, 0
        ld      c, a
        adc     hl, de

        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        xor     $80
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_fu3:  add     a, 0
        ld      c, a
        adc     hl, de

        dec     b
        jp      nz, mfu_loop
        jp      voice_save

mix_add_u4:
        call    voice_regs
        srl     b
        srl     b
mau_loop:
        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        bit     7, a
        jr      nz, mau0_neg
        add     a, (hl)
        jr      nc, mau0_st
        ld      a, 255
        jr      mau0_st
mau0_neg:
        add     a, (hl)
        jr      c, mau0_st
        xor     a
mau0_st:
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_au0:  add     a, 0
        ld      c, a
        adc     hl, de

        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        bit     7, a
        jr      nz, mau1_neg
        add     a, (hl)
        jr      nc, mau1_st
        ld      a, 255
        jr      mau1_st
mau1_neg:
        add     a, (hl)
        jr      c, mau1_st
        xor     a
mau1_st:
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_au1:  add     a, 0
        ld      c, a
        adc     hl, de

        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        bit     7, a
        jr      nz, mau2_neg
        add     a, (hl)
        jr      nc, mau2_st
        ld      a, 255
        jr      mau2_st
mau2_neg:
        add     a, (hl)
        jr      c, mau2_st
        xor     a
mau2_st:
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_au2:  add     a, 0
        ld      c, a
        adc     hl, de

        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        bit     7, a
        jr      nz, mau3_neg
        add     a, (hl)
        jr      nc, mau3_st
        ld      a, 255
        jr      mau3_st
mau3_neg:
        add     a, (hl)
        jr      c, mau3_st
        xor     a
mau3_st:
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_au3:  add     a, 0
        ld      c, a
        adc     hl, de

        dec     b
        jp      nz, mau_loop
        jp      voice_save

;-----------------------------------------------------------------------------
        EXPORT ready
ready:      db 0
        EXPORT mode
mode:       db 0
        EXPORT hold
hold:       db 0
        EXPORT blocklen
blocklen:   db MIXLEN               ; the checker sweeps this to fit T/sample
        EXPORT passes
passes:     dw 0
        EXPORT mixbuf
        EXPORT voltab
        EXPORT sampbuf

        ALIGN 8
voice0:     ds V_SIZE
voice1:     ds V_SIZE
voice2:     ds V_SIZE
voice3:     ds V_SIZE

        ALIGN 256
voltab:     ds 256                  ; one volume level; the port ships 64
        ALIGN 256
mixbuf:     ds 256
        ALIGN 256
sampbuf:    ds 512                  ; a ramp, two pages, so no advance runs off

        ASSERT $ < $BF00
        SAVENEX OPEN "build/mixtest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
