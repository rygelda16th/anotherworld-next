; The gated sound core, extracted from src/sndtest.asm so the game and the harness
; run the SAME code. A sound bug found in one and not the other is worth nothing.
;
; make check-snd proves every line below: four voices byte-exact against the host at
; three block lengths, nine ring wraps, nothing written outside the ring. make
; check-mix priced the inner loop at 295 T an output sample and checked its volume
; table against the reference.
;
; THIS FILE CONTAINS CODE ONLY. Its data stays where each program puts it, because
; sndtest.asm's voltab and sampbuf live INSIDE the banked page it maps at MMU1, and
; moving them would have broken a passing gate to tidy a file.
;
; voice_run is the block-splitting the design always described and never did. See its own
; comment: the inner loop has no end-of-sample test and must not run past V_END.
;
; THE INCLUDER MUST PROVIDE:
;
;   RING_ADDR        where the ring is, and where the DMA reads it. IT MUST BE
;                    PERMANENTLY MAPPED - the zxnDMA reads through the CPU's own
;                    memory decode, so a ring in a sliding window is a ring that
;                    vanishes. sndtest puts it at $0000 through MMU0, which it has
;                    spare. THE GAME CANNOT: MMU0 is the bytecode window, so the
;                    game's ring is resident RAM inside $8000-$BFFF. That was the
;                    first real conflict integration turned up.
;   SND_MAP_PAGES    a macro, run once per voice before its block is mixed, which
;                    maps whatever that voice needs. sndtest maps its ring page and
;                    its one shared sample page. The game maps the voice's OWN sample
;                    page and nothing else - and must put back what was there, since
;                    the loader stages through the same slot.
;   blocklen         byte: how many output samples this block is
;   mix_dst          word: where in the ring this block starts
;   voice0           four V_SIZE records
;   voltab           256 bytes, page-aligned; V_VOL holds its page

DMA_PORT        EQU $6B
DAC_PORT        EQU $DF
RING_LEN        EQU 2048

; 875 kHz / prescalar is the byte rate, so 22,050 Hz wants 39.7 and 40 gives
; 21,875 - a tenth of a semitone flat, and the closest the divider allows.
PRESCALAR       EQU 40
RATE_NUM        EQU 875000
VOLUME          EQU 48

V_FRAC          EQU 0
V_POS           EQU 1                   ; word: a pointer into the sample window
V_INCF          EQU 3
V_INCI          EQU 4                   ; word
V_VOL           EQU 6                   ; the volume table's page
V_END           EQU 7                   ; word: one past the last sample byte
V_LOOP          EQU 9                   ; word: where to go back to, 0 for none
V_ACTIVE        EQU 11
V_SIZE          EQU 12

; The ring's DMA programme, from wolf3d-next's ringtest.asm, which measured it
; against a recording: port A the ring in memory and incrementing, port B the DAC
; as a FIXED I/O address with a prescalar, WR5 auto-restart so it loops, and WR6's
; read mask so the tick can ask where it is.
dma_prog:
        db      $C3                     ; RESET
        db      $7D                     ; WR0: A -> B, address and length follow
        dw      RING_ADDR
        dw      RING_LEN
        db      $54, $02                ; WR1: port A memory, incrementing
        db      $68, $22, PRESCALAR     ; WR2: port B I/O, fixed, prescalar
        db      $CD                     ; WR4: burst, port B address follows
        dw      DAC_PORT
        db      $A2                     ; WR5: auto-restart at end of block
        db      $BB, $18                ; WR6: the read mask
        db      $CF                     ; LOAD
        db      $87                     ; ENABLE
dma_prog_end:

;-----------------------------------------------------------------------------
; The mixer. check-mix priced this loop and proved its arithmetic against the
; reference; this is the same loop reading a real sample and writing a real ring.
;
;   main    HL = sample pointer   DE = integer increment   C = fraction
;           B = samples left
;   shadow  HL' = the ring        DE' = the volume table
;
; The fractional add sets carry, LD does not disturb it, so ADC HL,DE applies the
; integer increment and the fraction's carry in one 15 T instruction.
;-----------------------------------------------------------------------------
mix_voice_first:
        call    voice_regs
mvf:
        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        xor     $80                     ; signed -> the DAC's unsigned centre
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_first:
        add     a, 0
        ld      c, a
        adc     hl, de
        dec     b
        jp      nz, mvf
        jp      voice_save

mix_voice_add:
        call    voice_regs
mva:
        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        bit     7, a
        jr      nz, mva_neg
        add     a, (hl)
        jr      nc, mva_st
        ld      a, 255
        jr      mva_st
mva_neg:
        add     a, (hl)
        jr      c, mva_st
        xor     a
mva_st:
        ld      (hl), a
        inc     l
        exx
        ld      a, c
p_add:  add     a, 0
        ld      c, a
        adc     hl, de
        dec     b
        jp      nz, mva
        jp      voice_save

voice_regs:
        ld      a, (ix + V_INCF)
        ld      (p_first + 1), a
        ld      (p_add + 1), a
        SND_MAP_PAGES                   ; the includer's; see the header
        ld      l, (ix + V_POS)
        ld      h, (ix + V_POS + 1)
        ld      e, (ix + V_INCI)
        ld      d, (ix + V_INCI + 1)
        ld      c, (ix + V_FRAC)
        ld      a, (blocklen)
        ld      b, a
        ld      a, (ix + V_VOL)
        exx
        ld      hl, (mix_dst)
        ld      d, a
        exx
        ret

voice_save:
        ld      (ix + V_POS), l
        ld      (ix + V_POS + 1), h
        ld      (ix + V_FRAC), c
        ret

;-----------------------------------------------------------------------------
; voice_run - how many of (blocklen) samples this voice may mix before it reaches
; V_END. IX = the voice. Returns A = the count, and Z if it is zero.
;
; THE INNER LOOP HAS NO END-OF-SAMPLE TEST, BY DESIGN - a test costs 18 T a voice a sample
; and the design says to cut the block short instead. But that cut was only ever DESCRIBED:
; sndtest.asm's setup_voices copies fields and never performs it, and check-snd never caught
; the omission because its sample is 1,024 bytes against blocks that never reach the end. So
; the mixer has been gated for its arithmetic and not for the lifecycle of a sample, and I1
; found out the hard way when a voice ran off its 512-byte ramp, past V_END, and started
; reading the RING as sample data and writing the result back over it.
;
; The bound: with an integer increment of zero the pointer advances less than one byte a
; sample, so V_END - V_POS samples is always safe. Otherwise divide by the integer part,
; which UNDER-estimates because the fraction also advances - safe, and it only means the
; caller loops again.
;-----------------------------------------------------------------------------
voice_run:
        ld      l, (ix + V_POS)
        ld      h, (ix + V_POS + 1)
        ld      e, (ix + V_END)
        ld      d, (ix + V_END + 1)
        ex      de, hl
        or      a
        sbc     hl, de                  ; HL = V_END - V_POS, the bytes left
        ret     c                       ; already past the end: nothing, and NC->C says so
        ld      a, h
        or      l
        ret     z                       ; exactly at the end

        ld      a, (ix + V_INCI + 1)
        or      a
        jr      nz, .huge               ; an increment above 255 bytes a sample
        ld      a, (ix + V_INCI)
        or      a
        jr      z, .whole               ; below 1:1 - every sample advances under a byte

        ; HL / A, sixteen by eight, the schoolbook way: ~16 shifts, once a block a voice
        ; against 18 T a sample a voice for the test it replaces.
        ld      c, a
        ld      de, 0
        ld      b, 16
.div:
        add     hl, hl
        rl      e
        rl      d
        ld      a, e
        sub     c
        ld      a, d
        sbc     a, 0
        jr      c, .nofit
        ld      a, e
        sub     c
        ld      e, a
        ld      a, d
        sbc     a, 0
        ld      d, a
        inc     l                       ; the quotient builds in HL's low bits
.nofit:
        djnz    .div
        ; HL now holds the quotient; cap it at a byte and at blocklen
        ld      a, h
        or      a
        jr      z, .cap
        ld      l, 255
.cap:
        ld      a, l
        jr      .limit
.whole:
        ld      a, h
        or      a
        jr      z, .cap_l
        ld      l, 255
.cap_l:
        ld      a, l
        jr      .limit
.huge:
        ld      a, 1                    ; more than 255 bytes a sample: one at a time
.limit:
        ld      hl, blocklen
        cp      (hl)
        jr      c, .done
        ld      a, (hl)
.done:
        or      a
        ret

;-----------------------------------------------------------------------------
; scale_byte - A read as int8, returns clamp(A * VOLUME / 64). Init time only.
; Magnitude then sign, because MUL D,E is unsigned.
;-----------------------------------------------------------------------------
scale_byte:
        bit     7, a
        jr      nz, .neg
        call    .mul
        ret
.neg:
        neg
        call    .mul
        neg
        ret
.mul:
        ld      e, a
        ld      d, VOLUME
        mul     d, e
        ld      a, e
        ld      b, d
        DUP 6
        srl     b
        rr      a
        EDUP
        ret

