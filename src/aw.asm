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

CC_ORG          EQU $8C00               ; must match VM_ORG in the Makefile
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
EXP_OPS         EQU $C500
RING_ADDR       EQU $D400               ; permanently mapped; see the header
VOLTAB          EQU $DC00
VOICES          EQU $DD00
IN_BLOCK        EQU $D300               ; the six input words the C reads
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
        ld      hl, EXPECTED_N
        ld      (CTL + $14), hl         ; how many records to compare against

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
; The video calls. STILL COUNTED, not drawn - I2 is what replaces them, and doing
; both at once would mean two things under test in one gate.
;-----------------------------------------------------------------------------
aw_draw_poly:
        ld      hl, (n_poly)
        inc     hl
        ld      (n_poly), hl
        ret
aw_select_page:
        ld      hl, (n_select)
        inc     hl
        ld      (n_select), hl
        ret
aw_fill_page:
        ld      hl, (n_fill)
        inc     hl
        ld      (n_fill), hl
        ret
aw_copy_page:
        ld      hl, (n_copy)
        inc     hl
        ld      (n_copy), hl
        ret
aw_blit:
        ld      hl, (n_blit)
        inc     hl
        ld      (n_blit), hl
        ret
aw_set_palette:
        ld      hl, (n_pal)
        inc     hl
        ld      (n_pal), hl
        ret

        INCLUDE "src/inc/vmhost.inc"
        INCLUDE "src/inc/input.inc"

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

        ASSERT $ < VEC_TABLE
        DISPLAY "> resident code and data end at ", /H, $

        ORG CTL
        EXPORT ctl
ctl:        ds 32 + 256 * 4             ; the control block, then 256 records
        ASSERT $ <= EXP_OPS

        ORG EXP_OPS
        EXPORT expected_ops
        INCLUDE "build/expected_ops.inc"
        DISPLAY "> expected stream is ", /D, EXPECTED_N, " records at ", /H, EXP_OPS
        ASSERT $ <= RING_ADDR

        ASSERT RING_ADDR + RING_LEN <= VOLTAB
        ASSERT VOLTAB + 256 <= VOICES
        ASSERT VOICES + V_SIZE * 4 <= SAMPLE
        ASSERT SAMPLE + SAMPLE_LEN <= $E000
        ; the vector table and its trampoline, in the gap the expected stream leaves
        ASSERT EXP_OPS + EXPECTED_N * 4 <= VEC_TABLE
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
