;-----------------------------------------------------------------------------
; Another World on the ZX Spectrum Next - THE GAME. One program.
;
; Chain 2, step I1. Eight harnesses proved the parts; this is the first file that
; runs more than one of them at once, and its gate is that nothing breaks when they
; are all live: the frame interrupt ticking, the zxnDMA streaming a ring to the DAC,
; the mixer refilling that ring every frame, the loader reading a segment off the
; card, and the virtual machine dispatching the engine's own opcode stream through
; all of it.
;
; THE SLOT MAP, proven by make check-map before any of this was written:
;
;   $0000-$3FFF  MMU0/1  the bytecode window. Two 8K pages of a segment up to
;                        62,683 bytes. The ROM during an esxDOS call.
;   $4000-$7FFF  MMU2/3  the polygon/cinematic window, for a segment up to 65,230.
;                        RESERVED HERE, used at I2. This region was written off in
;                        the memory map as "not available" - true only for the
;                        duration of a DOS call, and check-map proved it ours
;                        otherwise. There is no other slot for a second window, so
;                        I2 could not have been built without it.
;   $8000-$BFFF  MMU4/5  resident: this code, the C, the IM 2 table, the stack.
;   $C000-$DFFF  MMU6    NEVER REMAPPED, and that is the point. Bank 0's first half
;                        is part of the 48K image, so SAVENEX loads data here and it
;                        is mapped every cycle of every frame. The sound ring has to
;                        be somewhere like that: the zxnDMA reads through the CPU's
;                        own memory decode, so a ring in a sliding window is a ring
;                        that vanishes. sndtest.asm puts its ring at MMU0 because the
;                        harness has the slot spare; the game cannot.
;   $E000-$FFFF  MMU7    time-shared - the Layer 2 band being drawn, a sample page,
;                        and the loader's staging. Whoever borrows it puts it back.
;
; WHAT IS INSIDE MMU6's PAGE, which is the crowded one:
;
;   $C000-$C01F  the control block the C writes its verdict into
;   $C020-$C41F  256 trace records, four bytes each
;   $C500-$D0EB  the engine's own opcode stream, 763 records, for the on-machine
;                comparison that closed Gate D
;   $D400-$DBFF  THE RING, 2,048 bytes, where the DMA reads
;   $DC00-$DCFF  the volume table, page-aligned because V_VOL is a page number
;   $DD00-$DD2F  four voice records
;   $DE00-$DFFF  a ramp, standing in for a sample until I5 loads real ones
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

; $9600, not $8C00. The rasteriser and the reader are 1,248 lines and their data, and
; with them in the resident region the assembly now ends at $95D4. What that leaves the
; C's stack is the number to watch: $BF00 down to the end of its image. Gate D needed
; more than 779 bytes and was given 4,500; this is less, and if it is not enough the
; symptom is now a known one.
CC_ORG          EQU $9700               ; must match VM_ORG in the Makefile
NR_TURBO        EQU $07
NR_MMU0         EQU $50
NR_MMU1         EQU $51
NR_MMU2         EQU $52
NR_MMU3         EQU $53
NR_MMU6         EQU $56
NR_MMU7         EQU $57

CODE_WIN        EQU $0000               ; what vmhost.inc slides the bytecode through
CODE_PAGE       EQU 48
DST_WIN         EQU $E000               ; the loader's staging, MMU7

CTL             EQU $C000
INTERP_AT       EQU $C500               ; the 2,048-byte reciprocal table
RING_ADDR       EQU $D400               ; permanently mapped; see the header
VOLTAB          EQU $DC00
VOICES          EQU $DD00
IN_BLOCK        EQU $D300               ; the six input words the C reads

; Layer 2. The destination band goes at MMU7, because MMU2/MMU3 are the polygon window
; and the reader is reading it at the moment the rasteriser writes a band. The source
; band for a page copy borrows MMU2, which is safe only because no copy happens during
; a draw.
L2_BASE_BANK    EQU 12                  ; page 0 = banks 12,13,14
BANDS           EQU 6                   ; 8K pages of 32 scanlines each
DWIN            EQU $E000
NR_DWIN_MMU     EQU $57
; The polygon/cinematic segment's sliding window: $4000-$7FFF, MMU2 and MMU3. polytest
; puts it over $0000 through MMU0/MMU1, which it has spare; the game cannot, because
; that is its BYTECODE window and the VM is mid-opcode whenever the reader runs. This
; is the third slot conflict integration has turned up, and it is why check-map's proof
; that $4000-$7FFF is ours mattered: without it there is nowhere for this to go.
SEG_WIN         EQU $4000
NR_SEG_MMU_LO   EQU $52
NR_SEG_MMU_HI   EQU $53

; THE SOURCE BAND FOR A COPY-MODE FILL IS THE AWKWARD ONE, and it is worth writing
; down before aw_draw_poly is wired, because it decides how that routine is built.
;
; The rasteriser's copy fill reads its colour from page 0 (video.cpp:352,
; `colb = *(_pages[0] + off)`), so a copy-mode POLYGON needs a source band mapped while
; it draws - at the same time as the bytecode window, the segment window, the resident
; code, the ring and the destination band. That is eight slots for eight slots, with
; nothing spare.
;
; So the source band borrows MMU0 and aw_draw_poly must put back what was there. The
; VM's own window pointer survives that only because the borrow is returned before the
; C runs another instruction - the same discipline the reader already uses for rd_page,
; which had to be learned the hard way when a parent's pointer addressed a child's
; pages. Nothing is at risk today: aw_draw_poly still only counts.
SWIN            EQU $0000
NR_SWIN_MMU     EQU $50

; AND copyVideoPage GETS ITS OWN SLOT, which is not that one.
;
; The first version pointed the page copy's source at MMU0 as well, and check-aw failed
; within 2,067 records with "an invalid opcode": forty-five page copies had each mapped
; a Layer 2 band over the BYTECODE WINDOW and never put it back, so the VM was
; dispatching framebuffer. The rasteriser's copy-fill borrow and a whole-page copy are
; different problems - a copy happens BETWEEN draws, when the segment window is idle, so
; it can have MMU2 outright. seg_map remaps on every draw, so nothing needs restoring.
CPWIN           EQU $4000
NR_CPWIN_MMU    EQU $52
NR_L2_BANK      EQU $12
NR_L2_CFG       EQU $70
L2_PORT         EQU $123B
L2_VISIBLE      EQU %00000010
SCR_W           EQU 256
SCR_H           EQU 192
; The engine keeps FOUR pages and selects among them; these two constants are what the
; harness had, and I2's page model is what replaces them. For now they name page 1 as
; the destination and page 2 as the source, which is what the intro's first frames use.
DST_PAGE        EQU 1
SRC_PAGE        EQU 2
DST_P0          EQU (L2_BASE_BANK + DST_PAGE * 3) * 2
SRC_P0          EQU (L2_BASE_BANK + SRC_PAGE * 3) * 2
SAMPLE          EQU $DE00
SAMPLE_LEN      EQU 512

; 22,050 output samples a second at 50 frames is 441 a frame. blocklen is a byte, so
; it goes in two: 221 and 220.
BLK_A           EQU 221
BLK_B           EQU 220

; IM 2, above the C's data and below the stack. The table must be 257 bytes - the Z80
; reads the vector from I<<8|databus AND the byte after it - and every entry is
; VEC_FILL, so the vector is $ABAB and the trampoline goes there.
; THE VECTOR TABLE GOES IN MMU6's PAGE, not in the resident region, and that took two
; wrong answers to arrive at.
;
; First it was at $AA00, which the ASSERT caught: the C's image is 7,683 bytes from
; $8C00 and ends at $AA03, a three-byte overlap.
;
; Then it was at $AB00, which nothing caught until the machine hung with its tick
; counter frozen at 145. z88dk's CRT initialises a HEAP from $AA00 upward toward SP -
; `ld hl,$AA00 / call <heap init>` at $8C2C in this build - and the free-block header
; it writes there lands on the table. The next interrupt read a corrupt vector, jumped
; into nothing, and the interrupt that drives both the pacing and the sound simply
; stopped. Nothing in the resident region between the C and the stack is safe, because
; the CRT believes all of it is its heap.
;
; $C000-$DFFF is never remapped and the C knows nothing about it, so the table lives
; there, in the gap between the expected stream and the ring. Every entry is VEC_FILL,
; so the vector is $D2D2 and the trampoline goes there.
VEC_TABLE       EQU $D100
VEC_FILL        EQU $D2
VEC_TRAMP       EQU (VEC_FILL << 8) | VEC_FILL

        ORG $8000
jump_table:
        jp      aw_code_window          ; $8000
        jp      aw_draw_poly            ; $8003
        jp      aw_select_page          ; $8006
        jp      aw_fill_page            ; $8009
        jp      aw_copy_page            ; $800C
        jp      aw_blit                 ; $800F
        jp      aw_set_palette          ; $8012
        jp      aw_frame_sync           ; $8015
        ASSERT $ - jump_table == 24

start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3

        ; MMU6 is deliberately NOT touched: bank 0's first half is where the ring
        ; and the tables already are, loaded by the .nex.
        call    build_voltab
        call    silence_ring
        call    ramp_sample
        call    init_voices
        call    install_im2
        call    start_dma
        ei

        ld      a, $5A
        ld      (ready), a
.wait:  ld      a, (go)
        or      a
        jr      z, .wait

        ; DI ACROSS THE DOS CALL. esxDOS pages itself over the bottom 16K and keeps
        ; state across the RST $08; an interrupt taken inside that - even one whose
        ; vector table and handler are both in resident RAM - froze the machine dead
        ; the first time this ran, with the tick counter stopping at 147 and no
        ; records dispatched. The harnesses never saw it because they run with
        ; interrupts off from start to finish.
        ;
        ; The cost is real and the plan already names it: a load inside a frame is a
        ; frame the sound does not get refilled in, and the largest resource is 65,230
        ; bytes. That is I3's measurement, not something to model here.
        di
        call    load_code
        ei
        ld      a, (err)
        or      a
        jr      nz, .stop
        ld      hl, (got)
        ld      (CTL + $10), hl         ; the segment length, for the pc guard

        call    CC_ORG                  ; and the C runs the frame loop
        di                              ; the CRT's exit does `im 1 / ei / ret`
.stop:
        ld      a, $5A
        ld      (done), a
.hold:  di
        jr      .hold

;-----------------------------------------------------------------------------
; aw_frame_sync - the frame boundary, called once a frame by the C.
;
; The harness returns from this immediately; the game waits here for the frame
; interrupt. THAT IS ALL IT DOES - the sound is refilled by the interrupt itself, not
; from here, for two reasons. It is where E1 says the frame loop ends up anyway. And
; it means the sound survives the C's frame loop finishing: vm.c's main never returns,
; so a mixer called only from this hook would go silent the moment the last frame ran
; and there would be nothing left to soak-test.
;
; The pacing is one refresh a frame, NOT the script's requested pause. The script asks
; for four or five slices and E1 proved the arithmetic for honouring it; wiring that in
; is I2's business, because until the VM draws there is nothing whose deadline could be
; missed.
;-----------------------------------------------------------------------------
aw_frame_sync:
        ; EI, EVERY FRAME, AND IT IS NOT BELT-AND-BRACES. z88dk's CRT does `di` as its
        ; FIRST instruction - $8C00 is F3 - so the `ei` before `call CC_ORG` is undone
        ; before the C runs a line. The machine then spun here forever waiting for a
        ; tick that could not arrive: PC at $8066, ticks frozen at 165, IFF--.
        ;
        ; The CRT owns the interrupt state at BOTH ends. It disables on entry and, as
        ; Gate D found the hard way, enables on exit with `im 1 / ei / ret`. Anything
        ; that needs interrupts while C is running has to assert that for itself, and
        ; the frame boundary is the place to do it.
        ei
        push    hl
        push    de
        ld      hl, (ticks)
.spin:  ld      de, (ticks)
        ld      a, e
        cp      l
        jr      z, .spin                ; one frame interrupt
        pop     de
        pop     hl
        ret

;-----------------------------------------------------------------------------
; mix_block - A = how many samples, into the ring at (ring_wr), which wraps.
; The first active voice stores and the rest accumulate, which is what makes the
; inner loop test-free; sndtest.asm's do_mix is the same shape and check-snd proves
; the arithmetic of both.
;-----------------------------------------------------------------------------
mix_block:
        ld      (blocklen), a
        ld      hl, (ring_wr)
        ld      (mix_dst), hl

        ld      ix, VOICES
        ld      b, 4
        ld      c, 0                    ; have we stored yet
.each:
        ld      a, (ix + V_ACTIVE)
        or      a
        jr      z, .next

        ; KEEP THE VOICE INSIDE ITS SAMPLE, because the mixer will not.
        ;
        ; The gated inner loop has NO end-of-sample test - deliberately, because a test
        ; per sample costs 18 T a voice and the design resolves it by cutting the block
        ; short instead. But sndtest.asm only DESCRIBES that cut in a comment; its
        ; setup_voices copies fields and never performs it, and check-snd never caught
        ; the omission because its sample is 1,024 bytes against blocks that never
        ; reach the end. So the mixer is gated for its ARITHMETIC and not for the
        ; lifecycle of a sample.
        ;
        ; Here that showed as V_POS at $D610 after a few seconds: the voice had run off
        ; its 512-byte ramp, past V_END, and was reading the RING as sample data and
        ; writing the result back over it. The ring filled with what that produces.
        ;
        ; This is the crude version - rewind when the next block would not fit - and it
        ; is enough for a voice that loops. Proper end-of-sample and loop-point handling
        ; is I5's, with real resources behind it, and it is more unwritten code than the
        ; plan credited.
        ld      l, (ix + V_POS)
        ld      h, (ix + V_POS + 1)
        ld      a, (blocklen)
        ld      e, a
        ld      d, 0
        add     hl, de                  ; where this block would end
        ld      e, (ix + V_END)
        ld      d, (ix + V_END + 1)
        or      a
        sbc     hl, de
        jr      c, .in_range
        ld      a, (ix + V_LOOP)        ; it would overrun: back to the loop point
        ld      (ix + V_POS), a
        ld      a, (ix + V_LOOP + 1)
        ld      (ix + V_POS + 1), a
        ld      (ix + V_FRAC), 0
.in_range:
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

        ld      a, c
        or      a
        jr      nz, .advance
        ; nothing active: silence, which for a DAC centred at 128 is 128
        ld      hl, (ring_wr)
        ld      a, (blocklen)
        ld      b, a
.sil:   ld      (hl), 128
        inc     hl
        djnz    .sil
.advance:
        ; wrap the write pointer at the end of the ring
        ld      hl, (ring_wr)
        ld      a, (blocklen)
        ld      e, a
        ld      d, 0
        add     hl, de
        ld      de, RING_ADDR + RING_LEN
        or      a
        sbc     hl, de
        jr      c, .store
        ld      hl, RING_ADDR           ; past the end: back to the start
        ld      (ring_wr), hl
        ret
.store:
        add     hl, de
        ld      (ring_wr), hl
        ret

;-----------------------------------------------------------------------------
; publish_input - the six variables inp_updatePlayer sets, into a fixed block the C
; reads at the top of every frame. A fixed address on both sides rather than a symbol
; bridged between two assemblers, which is the arrangement that has worked here.
;-----------------------------------------------------------------------------
publish_input:
        ld      hl, (var_E5)
        ld      (IN_BLOCK + 0), hl
        ld      hl, (var_FA)
        ld      (IN_BLOCK + 2), hl
        ld      hl, (var_FB)
        ld      (IN_BLOCK + 4), hl
        ld      hl, (var_FC)
        ld      (IN_BLOCK + 6), hl
        ld      hl, (var_FD)
        ld      (IN_BLOCK + 8), hl
        ld      hl, (var_FE)
        ld      (IN_BLOCK + 10), hl
        ret

;-----------------------------------------------------------------------------
; Setup, once, at boot.
;-----------------------------------------------------------------------------
build_voltab:
        ld      hl, VOLTAB
        ld      b, 0
.vt:    ld      a, b
        push    bc
        push    hl
        call    scale_byte
        pop     hl
        pop     bc
        ld      (hl), a
        inc     hl
        inc     b
        jr      nz, .vt
        ret

silence_ring:
        ld      hl, RING_ADDR
        ld      de, RING_ADDR + 1
        ld      bc, RING_LEN - 1
        ld      (hl), 128
        ldir
        ld      hl, RING_ADDR
        ld      (ring_wr), hl
        ret

; A ramp until I5 loads a real sound resource. It exists so the mixer does its real
; work in this gate: 23.2% of the machine is a measured cost and a silent mixer would
; not pay it.
ramp_sample:
        ld      hl, SAMPLE
        ld      bc, SAMPLE_LEN
.r:     ld      a, l
        ld      (hl), a
        inc     hl
        dec     bc
        ld      a, b
        or      c
        jr      nz, .r
        ret

init_voices:
        ld      ix, VOICES
        ld      b, 4
        ld      c, 0
.one:
        ld      (ix + V_ACTIVE), 1
        ld      (ix + V_FRAC), 0
        ld      (ix + V_POS), SAMPLE & $FF
        ld      (ix + V_POS + 1), SAMPLE >> 8
        ld      (ix + V_INCF), 0
        ld      (ix + V_INCI), 1        ; one sample in, one out
        ld      (ix + V_INCI + 1), 0
        ld      a, VOLTAB >> 8
        ld      (ix + V_VOL), a
        ld      (ix + V_END), (SAMPLE + SAMPLE_LEN) & $FF
        ld      (ix + V_END + 1), (SAMPLE + SAMPLE_LEN) >> 8
        ld      (ix + V_LOOP), SAMPLE & $FF
        ld      (ix + V_LOOP + 1), SAMPLE >> 8
        ld      de, V_SIZE
        add     ix, de
        dec     b
        jp      nz, .one
        ret

install_im2:
        ld      hl, VEC_TABLE
        ld      (hl), VEC_FILL
        ld      de, VEC_TABLE + 1
        ld      bc, 256                 ; 257 bytes in total: see the header
        ldir
        ld      hl, VEC_TRAMP
        ld      (hl), $C3               ; JP isr
        inc     hl
        ld      (hl), isr & $FF
        inc     hl
        ld      (hl), isr >> 8
        ld      a, VEC_TABLE >> 8
        ld      i, a
        im      2
        ret

start_dma:
        ld      hl, dma_prog
        ld      bc, ((dma_prog_end - dma_prog) << 8) | DMA_PORT
        otir
        ret

; The frame interrupt: the tick the pacing counts, and 441 samples into the ring -
; 22,050 a second at 50 frames, which is the rate the DMA drains it. The mixer uses
; IX and the shadow set, so everything it touches is saved; an ISR that clobbered the
; shadow registers would corrupt the rasteriser at I2 and look like a rasteriser bug.
isr:
        push    af
        push    bc
        push    de
        push    hl
        push    ix
        ex      af, af'
        push    af
        exx
        push    bc
        push    de
        push    hl

        ld      hl, (ticks)
        inc     hl
        ld      (ticks), hl

        ; INPUT IS READ HERE, not at the frame boundary, and for the same reason the
        ; mixing is: vm.c's main never returns, so anything driven only from the frame
        ; hook stops the moment the last frame runs. Five port reads and the reference's
        ; own mapping, fifty times a second.
        call    read_keys
        call    do_input
        call    publish_input

        ld      a, BLK_A
        call    mix_block
        ld      a, BLK_B
        call    mix_block

        pop     hl
        pop     de
        pop     bc
        exx
        pop     af
        ex      af, af'
        pop     ix
        pop     hl
        pop     de
        pop     bc
        pop     af
        ei
        reti


;-----------------------------------------------------------------------------
; THE VIDEO CALLS, FOR REAL. I2.
;
; Each one is the reference's, cited. They keep their counters as well, because
; check-aw scores them and a callback that is reached zero times is worth knowing
; about.
;
; THE PAGE MODEL first, because everything else needs it. The engine keeps FOUR pages
; (video.cpp:49, `malloc(4 * VID_PAGE_SIZE)`) and three pointers into them:
;
;   ptr1  what drawing goes into      changePagePtr1, video.cpp:491
;   ptr2  what is being displayed     updateDisplay,  video.cpp:597
;   ptr3  the other display page, swapped with ptr2 when a blit asks for $FF
;
; We hold page NUMBERS rather than pointers, so a swap is two byte moves.
;-----------------------------------------------------------------------------

; resolve_page - A = a page id as the bytecode gives it, out as 0..3.
; getPage, video.cpp:468: 0..3 are themselves, $FF is ptr3, $FE is ptr2, and anything
; else is page 0 with a warning - which we keep, because a port that silently did
; something else there would diverge from the engine on exactly the records that are
; hardest to notice.
resolve_page:
        cp      4
        ret     c
        cp      $FF
        jr      nz, .not_ff
        ld      a, (pg_ptr3)
        ret
.not_ff:
        cp      $FE
        jr      nz, .other
        ld      a, (pg_ptr2)
        ret
.other:
        xor     a                       ; page 0, as the reference warns and does
        ret

; page_to_p0 - A = 0..3, out as the first of that page's six 8K pages.
; A Layer 2 page is three 16K banks from L2_BASE_BANK, so six 8K pages from
; (L2_BASE_BANK + page * 3) * 2.
page_to_p0:
        add     a, a                    ; page * 2
        ld      b, a
        add     a, a                    ; page * 4
        add     a, b                    ; page * 6
        add     a, L2_BASE_BANK * 2
        ret

aw_select_page:
        ld      (jt_arg), hl    ; the fastcall argument, before a counter clobbers HL
        ld      hl, (n_select)
        inc     hl
        ld      (n_select), hl
        ld      a, (jt_arg)
        call    resolve_page
        ld      (pg_ptr1), a
        call    page_to_p0
        ld      (dst_p0), a             ; where the rasteriser writes its bands
        ld      a, 255
        ld      (cur_band), a           ; force the next band map
        ret

; fillPage, video.cpp:498. The reference duplicates the colour into both nibbles
; because its page is 4bpp; ours is 8bpp with one index a byte, so the byte IS the
; colour and the duplication would be wrong.
aw_fill_page:
        ld      (jt_arg), hl    ; the fastcall argument, before a counter clobbers HL
        ld      hl, (n_fill)
        inc     hl
        ld      (n_fill), hl
        ld      a, (jt_arg + 1)
        ld      (fill_col), a
        ld      a, (jt_arg)
        call    resolve_page
        call    page_to_p0
        ld      c, a                    ; C = the page's first 8K page
        ld      b, BANDS
.band:
        ld      a, c
        nextreg NR_DWIN_MMU, a
        push    bc
        ld      hl, DWIN
        ld      de, DWIN + 1
        ld      bc, $2000 - 1
        ld      a, (fill_col)
        ld      (hl), a
        ldir
        pop     bc
        inc     c
        djnz    .band
        ld      a, 255
        ld      (cur_band), a
        ret

; copyPage, video.cpp:513. Same page in and out does nothing. The scrolled form is
; NOT implemented here and says so: it needs vscroll, which our op_copyVideoPage does
; not yet pass, and the scroll is in the reference's 200-line geometry so it has to be
; scaled the way every other Y is. Recorded as I2's remaining work rather than guessed.
aw_copy_page:
        ld      (jt_arg), hl    ; the fastcall argument, before a counter clobbers HL
        ld      hl, (n_copy)
        inc     hl
        ld      (n_copy), hl
        ld      a, (jt_arg)
        ld      c, a                    ; C = src as given
        ld      a, (jt_arg + 1)
        ld      b, a                    ; B = dst as given
        cp      c
        ret     z                       ; src == dst: the reference returns
        ld      a, c
        cp      $FE
        jr      nc, .plain              ; >= $FE is always a plain copy
        and     $BF
        ld      c, a
        bit     7, a
        jr      nz, .scrolled
.plain:
        ld      a, c
        call    resolve_page
        call    page_to_p0
        ld      (cp_src), a
        ld      a, b
        call    resolve_page
        call    page_to_p0
        ld      (cp_dst), a
        ld      d, BANDS
        ld      e, 0
.cband:
        ld      a, (cp_src)
        add     a, e
        nextreg NR_CPWIN_MMU, a
        ld      a, (cp_dst)
        add     a, e
        nextreg NR_DWIN_MMU, a
        push    de
        ld      hl, CPWIN
        ld      de, DWIN
        ld      bc, $2000
        ldir
        pop     de
        inc     e
        dec     d
        jr      nz, .cband
        ld      a, 255
        ld      (cur_band), a
        ret
.scrolled:
        ld      a, 1
        ld      (cp_unimpl), a          ; counted, not guessed: see the comment
        ret

; updateDisplay, video.cpp:597. $FE changes nothing, $FF swaps the two display pages,
; anything else selects one - and THEN the requested palette is applied, before the
; page is presented. That order is the reference's and it is the one a port gets wrong.
aw_blit:
        ld      (jt_arg), hl    ; the fastcall argument, before a counter clobbers HL
        ld      hl, (n_blit)
        inc     hl
        ld      (n_blit), hl
        ld      a, (jt_arg)
        cp      $FE
        jr      z, .palette             ; $FE: no page change at all
        cp      $FF
        jr      nz, .select
        ld      a, (pg_ptr2)            ; $FF: swap ptr2 and ptr3
        ld      b, a
        ld      a, (pg_ptr3)
        ld      (pg_ptr2), a
        ld      a, b
        ld      (pg_ptr3), a
        jr      .palette
.select:
        call    resolve_page
        ld      (pg_ptr2), a
.palette:
        ld      a, (pal_req)
        cp      $FF
        jr      z, .present
        call    apply_palette
        ld      a, $FF
        ld      (pal_req), a
.present:
        ; the visible Layer 2 bank is the page's first 16K bank
        ld      a, (pg_ptr2)
        ld      b, a
        add     a, a
        add     a, b                    ; page * 3
        add     a, L2_BASE_BANK
        nextreg NR_L2_BANK, a
        ret

; op_setPalette only REQUESTS. changePal runs inside updateDisplay (video.cpp:610),
; so a palette set mid-frame does not appear until the frame is presented.
aw_set_palette:
        ld      (jt_arg), hl    ; the fastcall argument, before a counter clobbers HL
        ld      hl, (n_pal)
        inc     hl
        ld      (n_pal), hl
        ld      a, (jt_arg)
        cp      32                      ; changePal ignores >= 32, video.cpp:589
        ret     nc
        ld      (pal_req), a
        ret

; The 512 Layer 2 palette entries are already resident as two 256-entry banks, so a
; palette change is a bank select rather than a transfer: 32 palettes of 16 across the
; two banks, which is exactly what mkassets.py lays out.
apply_palette:
        ld      (pal_now), a
        ret                             ; I2 remainder: select the entries

aw_draw_poly:
        ld      (jt_arg), hl    ; the fastcall argument, before a counter clobbers HL
        ld      hl, (n_poly)
        inc     hl
        ld      (n_poly), hl
        ret                             ; I2 remainder: call poly_read

        INCLUDE "src/inc/vmhost.inc"
        INCLUDE "src/inc/input.inc"
        INCLUDE "src/inc/raster.inc"

; The game's ring and its sample are both resident in MMU6's page, so a voice needs
; nothing mapped for it. I5 gives each voice its own sample page and this macro
; becomes a borrow-and-restore of MMU7.
        MACRO SND_MAP_PAGES
        ENDM

        INCLUDE "src/inc/sound.inc"

;-----------------------------------------------------------------------------
; The loader's own state lives in vmhost.inc; these say which of it the checker reads.
        EXPORT fname
        EXPORT err
        EXPORT got
        EXPORT in_mask
        EXPORT in_button

        EXPORT ready
ready:      db 0
        EXPORT go
go:         db 0
        EXPORT done
done:       db 0
        EXPORT ticks
ticks:      dw 0
ring_wr:    dw RING_ADDR
blocklen:   db 0
mix_dst:    dw 0
        EXPORT n_poly
n_poly:     dw 0
        EXPORT n_select
n_select:   dw 0
        EXPORT n_fill
n_fill:     dw 0
        EXPORT n_copy
n_copy:     dw 0
        EXPORT n_blit
n_blit:     dw 0
        EXPORT n_pal
n_pal:      dw 0

jt_arg:     dw 0                        ; whichever callback's argument, stashed
        EXPORT pg_ptr1
pg_ptr1:    db 0                        ; the page drawing goes into
        EXPORT pg_ptr2
pg_ptr2:    db 1                        ; the page being displayed - video.cpp:56-57
        EXPORT pg_ptr3
pg_ptr3:    db 2                        ; the other display page
fill_col:   db 0
cp_src:     db 0
cp_dst:     db 0
        EXPORT cp_unimpl
cp_unimpl:  db 0                        ; a scrolled copy was asked for: I2 remainder
        EXPORT pal_req
pal_req:    db $FF                      ; $FF = no palette change requested
        EXPORT pal_now
pal_now:    db $FF
rd_log:     ds 8 * 8                    ; the reader's leaf log, small: nothing reads it

        DISPLAY "> resident code and data end at ", /H, $
        ASSERT $ < CC_ORG

        ORG CTL
        EXPORT ctl
ctl:        ds 32 + 256 * 4             ; the control block, then 256 records
        ASSERT $ <= INTERP_AT

        ; THE RECIPROCAL TABLE, where the expected opcode stream used to be.
        ;
        ; I1's gate compared the game's opcode stream against the engine's from inside
        ; the .nex, and it passed - 763 of 763. But the rasteriser needs 1,024
        ; reciprocals resident and the resident 16K cannot hold the assembly, the C and
        ; 2KB of table at once. I2's gate is the PICTURE, compared page for page against
        ; the engine, which is a stronger claim than the stream anyway: a wrong opcode
        ; that does not change what is drawn is not interesting, and one that does shows
        ; up here.
        ORG INTERP_AT
        ALIGN 2
        INCLUDE "build/interp.inc"
        DISPLAY "> reciprocals at ", /H, INTERP_AT, " ending ", /H, $
        ASSERT $ <= RING_ADDR

        ASSERT RING_ADDR + RING_LEN <= VOLTAB
        ASSERT VOLTAB + 256 <= VOICES
        ASSERT VOICES + V_SIZE * 4 <= SAMPLE
        ASSERT SAMPLE + SAMPLE_LEN <= $E000
        ; the vector table and its trampoline, in the gap the expected stream leaves
        ASSERT VEC_TABLE + 257 <= VEC_TRAMP
        ASSERT VEC_TRAMP + 3 <= RING_ADDR
        ASSERT IN_BLOCK + 12 <= VEC_TABLE || IN_BLOCK >= VEC_TRAMP + 3

        ORG CC_ORG
        INCBIN  "build/aw_vm_CODE.bin"
        DISPLAY "> the C is ", /D, $ - CC_ORG, " bytes at ", /H, CC_ORG
        ASSERT $ < VEC_TABLE

        SAVENEX OPEN "build/aw.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
