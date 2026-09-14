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
;   NR_SAMP_MMU      the slot SND_MAP_PAGES maps a sample page into, if it does
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
; WHICH 8K PAGE THIS VOICE'S SAMPLE IS IN. I1 recorded that the gated mixer maps ONE sample
; page for all four voices - sndtest hard-codes it - and that the game needs four. Real samples
; are up to 41,506 bytes, six pages, so the window slides within a sample as well as between
; voices. sndtest's sample is resident, so its SND_MAP_PAGES ignores this and check-snd is
; unaffected; the game's maps it.
V_PAGE          EQU 12
; BYTES STILL TO COME AFTER THE WINDOW'S END. A sample can be 41,506 bytes - six pages - and
; the window is one 8K page, so V_END marks the end of what is REACHABLE now and V_LEFT says
; whether there is more behind it. When the window runs out and V_LEFT is not zero, the page
; advances and V_POS goes back to the window's base. sndtest's sample is 1,024 bytes in one
; resident page, so its V_LEFT is zero and nothing about it changes.
V_LEFT          EQU 13                  ; word
; THE SAMPLE'S FIRST PAGE AND ITS WHOLE LENGTH, which looping needs and nothing else does.
; V_LOOP is an address in the sample's FIRST window - voice_setup only records a loop point it
; can reach there - so returning to it means restoring the page and the window with it. Setting
; V_POS alone left V_PAGE and V_END describing the LAST window, where V_LOOP is past the end:
; voice_run returned zero for ever, voice_advance looped straight back, and the interrupt never
; came back. check-aw caught it as "the interrupt advanced 0 ticks in 5s" - the module's own
; instruments are multi-page and looped, so the intro hit it within a minute.
V_PAGE0         EQU 15
V_TOTAL         EQU 16                  ; word
V_SIZE          EQU 18

; The ring's DMA programme, from wolf3d-next's ringtest.asm, which measured it
; against a recording: port A the ring in memory and incrementing, port B the DAC
; as a FIXED I/O address with a prescalar, WR5 auto-restart so it loops, and WR6's
; read mask so the tick can ask where it is.
    IFNDEF SND_NO_DMA                   ; the game drives the DAC from the copper instead
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
    ENDIF

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
; THE GAME DOES NOT ASSEMBLE THIS. Its mix_block fills each block with 128 and has every voice
; accumulate, because `mva` onto 128 is byte-identical to the biased store below and it means a
; voice that stops mid-block leaves silence rather than stale ring. sndtest still stores, so the
; routine stays - but the game had four bytes left in its resident block and no use for it.
        IFNDEF SND_NO_FIRST
mix_voice_first:
        call    voice_regs
mvf:
        ld      a, (hl)
        exx
        ld      e, a
        ld      a, (de)
        xor     $80                     ; signed -> the DAC's unsigned centre
        ld      (hl), a
        inc     hl                      ; hl, NOT l: the destination has to CARRY. `inc l` meant
        exx                             ; a block could not cross a 256-byte boundary in the
                                        ; ring, and with BLK_A of 221 into 2,048 bytes it does -
                                        ; the write wrapped back into the same page instead. Two
                                        ; T-states a sample a voice, 0.63% of the machine, and
                                        ; it removes a whole class of splitting from the caller.
        ld      a, c
p_first:
        add     a, 0
        ld      c, a
        adc     hl, de
        dec     b
        jp      nz, mvf
        jp      voice_save
        ENDIF

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
    IFDEF SND_STRIDE4
        add     hl, bc                  ; the copper list: a line's sample is every fourth byte
    ELSE
        inc     hl                      ; hl, NOT l: the destination has to CARRY. `inc l` meant
    ENDIF
        exx                             ; a block could not cross a 256-byte boundary in the
                                        ; ring, and with BLK_A of 221 into 2,048 bytes it does -
                                        ; the write wrapped back into the same page instead. Two
                                        ; T-states a sample a voice, 0.63% of the machine, and
                                        ; it removes a whole class of splitting from the caller.
        ld      a, c
p_add:  add     a, 0
        ld      c, a
        adc     hl, de
        dec     b
        jp      nz, mva
        jp      voice_save

voice_regs:
        ld      a, (ix + V_INCF)
        IFNDEF SND_NO_FIRST
        ld      (p_first + 1), a
        ENDIF
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
    IFDEF SND_STRIDE4
        ld      bc, 4                   ; the shadow BC is free, and add hl,bc costs 5 T over inc hl
    ENDIF
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
; The bound: with an integer increment of zero the pointer advances at most one byte a sample,
; so V_END - V_POS samples is always safe. Otherwise divide by the integer part PLUS ONE,
; because a sample advances inci or inci+1 depending on the fraction's carry.
;
; This used to divide by the integer part alone, on the stated reasoning that it "under-
; estimates because the fraction also advances". That is backwards: dividing by inci OVER-
; estimates, and at 1.4453 bytes a sample it returned bytes_left samples where only
; bytes_left/1.4453 fit - so the pointer ran past V_END, wrapped through $0000, and the voice
; read on from the bottom of memory. Dividing by inci+1 can only under-estimate, which costs
; the caller another turn of its loop and nothing else.
;-----------------------------------------------------------------------------
; voice_advance - the window has run out for this voice. If there is more sample behind it,
; step to the next page and rewind V_POS to the window's base; otherwise loop or stop.
; The pages a sample occupies are CONSECUTIVE because aw_load_res allocates them that way,
; so stepping is an increment and not a lookup.
voice_advance:
        ld      l, (ix + V_LEFT)
        ld      h, (ix + V_LEFT + 1)
        ld      a, h
        or      l
        jr      z, .no_more
        ; another page: up to 8K of it becomes reachable
        inc     (ix + V_PAGE)
        ; CARRY THE OVERSHOOT. The pointer crossed the window's end, and wrapping left the
        ; remainder in it - so the new position is the window's base PLUS that, not the base.
        ; Rewinding to the base dropped up to inci + 1 bytes at every page boundary, which
        ; showed as a one-byte error at the first crossing and a drift after it. SAMP_WIN's low
        ; byte is zero, so this is one add.
        ld      a, (ix + V_POS + 1)
        add     a, SAMP_WIN >> 8
        ld      (ix + V_POS + 1), a
        ld      de, $2000
        or      a
        sbc     hl, de
        jr      nc, .full_page
        ; less than a page left: the end lands inside the window
        add     hl, de
        ld      de, SAMP_WIN
        add     hl, de
        ld      (ix + V_END), l
        ld      (ix + V_END + 1), h
        ld      (ix + V_LEFT), 0
        ld      (ix + V_LEFT + 1), 0
        ret
.full_page:
        ld      (ix + V_LEFT), l
        ld      (ix + V_LEFT + 1), h
        ; $0000, DELIBERATELY: the window's end is $10000 and no word holds it. voice_run
        ; knows this encoding - see the borrow it allows. Written as zero rather than let the
        ; assembler truncate $100, so a real truncation warning is never buried under this one.
        ld      (ix + V_END), 0
        ld      (ix + V_END + 1), 0
        ret
.no_more:
        ; the sample is finished: loop if it has a loop point, otherwise go quiet
        ld      l, (ix + V_LOOP)
        ld      h, (ix + V_LOOP + 1)
        ld      a, h
        or      l
        jr      z, .stop
        ld      (ix + V_POS), l
        ld      (ix + V_POS + 1), h
        ld      (ix + V_FRAC), 0
        ; AND THE PAGE AND THE WINDOW WITH IT - see V_PAGE0 above for what going without
        ; cost. The state wanted is exactly what voice_setup left, bar the position.
        ld      a, (ix + V_PAGE0)
        ld      (ix + V_PAGE), a
        ld      l, (ix + V_TOTAL)
        ld      h, (ix + V_TOTAL + 1)
        ld      de, $2000
        or      a
        sbc     hl, de
        jr      nc, .loop_spans
        add     hl, de                  ; it all fits one window
        ld      de, SAMP_WIN
        add     hl, de
        ld      (ix + V_END), l
        ld      (ix + V_END + 1), h
        ld      (ix + V_LEFT), 0
        ld      (ix + V_LEFT + 1), 0
        ret
.loop_spans:
        ld      (ix + V_LEFT), l        ; what is left after this window
        ld      (ix + V_LEFT + 1), h
        ld      (ix + V_END), 0         ; $10000, deliberately; see voice_run
        ld      (ix + V_END + 1), 0
        ret
.stop:
        ld      (ix + V_ACTIVE), 0
        ret

voice_run:
        ld      l, (ix + V_POS)
        ld      h, (ix + V_POS + 1)
        ld      e, (ix + V_END)
        ld      d, (ix + V_END + 1)
        ex      de, hl
        or      a
        sbc     hl, de                  ; HL = V_END - V_POS, the bytes left
        jr      nc, .in_window
        ; A BORROW, WHICH IS NOT ALWAYS AN ERROR. V_END of $0000 means the end of the
        ; WINDOW - $10000, which no word holds - and that is what every FULL page gets, from
        ; voice_advance and from voice_setup alike. There the subtract above is already right:
        ; 0 - V_POS is 0x10000 - V_POS exactly. `ret c` therefore reported "past the end, mix
        ; nothing" for every voice sitting on a full page, so a sample spanning more than one
        ; page mixed only its last partial page. check-snd never saw it - its sample is 1,024
        ; bytes and never gets a full-page window - and check-mus checks the voice records that
        ; go in, not the bytes that come out.
        ; A BORROW MEANS ONE OF TWO THINGS. V_END may be the $0000 that means the window's end -
        ; $10000, which no word holds - in which case HL is already right, because 0 - V_POS is
        ; 0x10000 - V_POS exactly. Or the pointer has CROSSED that end and wrapped, which shows
        ; as V_POS below the window's base: DE still holds it after the subtract.
        ld      a, d
        cp      SAMP_WIN >> 8
        jr      c, .crossed
        ld      a, (ix + V_END)
        or      (ix + V_END + 1)
        jr      z, .have_left
.crossed:
        xor     a                       ; nothing here, and the caller must advance. This
        ret                             ; returned the OR's result before, which the caller
                                        ; would have read as a sample count.
.in_window:
        ld      a, h
        or      l
        ret     z                       ; exactly at the end
.have_left:

        ld      a, (ix + V_INCI + 1)
        or      a
        jr      nz, .huge               ; an increment above 255 bytes a sample
        ld      a, (ix + V_INCI)
        or      a
        jr      z, .whole               ; below 1:1 - every sample advances under a byte
        inc     a                       ; inci + 1: the most one sample can advance
        jr      z, .huge                ; inci was 255, so one sample at a time

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
        ret     nz
        ; AT LEAST ONE SAMPLE while any byte remains. The bound divides by inci + 1 and so
        ; under-estimates; near a window's edge that rounds to zero while a byte is still
        ; there, and rewinding to the next page from short of the edge drops those bytes and
        ; the fraction's phase with them. Letting the pointer CROSS instead - by at most
        ; inci + 1, and the byte it reads on the way is still inside - keeps the phase exact,
        ; and voice_advance picks the overshoot up.
        inc     a
        ret

;-----------------------------------------------------------------------------
; scale_byte - A read as int8, returns clamp(A * (vol_now) / 64). Init time only.
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
        ; THE VOLUME IS A VARIABLE, not the constant it was. The game builds two tables at two
        ; volumes - see VOLTAB_QUIET in src/aw.asm - and check-mix gates the arithmetic at
        ; VOLUME 48, which vol_now still holds by default, so nothing about that gate changes.
        ld      a, (vol_now)
        ld      d, a
        ld      a, e
        mul     d, e
        ld      a, e
        ld      b, d
        DUP 6
        srl     b
        rr      a
        EDUP
        ret

