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
CC_ORG          EQU $9C00               ; must match VM_ORG in the Makefile
NR_TURBO        EQU $07
NR_MMU0         EQU $50
NR_MMU1         EQU $51
NR_MMU2         EQU $52
NR_MMU3         EQU $53
NR_MMU6         EQU $56
NR_MMU7         EQU $57

CODE_WIN        EQU $0000               ; what vmhost.inc slides the bytecode through
CODE_PAGE       EQU 48                  ; eight 8K pages for the bytecode segment
POLY_PAGE       EQU 56                  ; and eight for the cinematic segment
; I3's heap: resources the bytecode asks for at runtime, allocated a page at a time.
; The reference's own high-water mark across the parts measured is 305,919 bytes - 38
; pages - so 40 is the reservation, and running past it is a fault rather than a wrap.
RES_FIRST_PAGE  EQU 72
RES_MAX_PAGES   EQU 40
DST_WIN         EQU $E000               ; the loader's staging, MMU7

CTL             EQU $C000
STACK_TOP       EQU $D400               ; grows down to $CF00: 1,280 bytes
STACK_FLOOR     EQU $CF00
INTERP_AT       EQU $C500               ; the 2,048-byte reciprocal table
; I3's tables, in MMU6's page rather than the resident region, which the rasteriser and
; the C had already filled: 584 bytes of resource table and 146 of load state is 730, and
; putting it below $9900 left the VM 951 bytes of stack. The room comes from the trace
; buffer, which dropped from 256 records to 32 - check-boot gates the opcode stream at 763
; in the harness, so the game's copy of it is a post-mortem convenience and not a claim.
RES_TABLE_AT    EQU $C0A0
; The palette moved OUT of MMU6's page and into the text page, because MMU6 had to give up
; 1,024 bytes for the stack. It is read only by apply_palette, which runs at a blit and never
; during a draw, so mapping the text page at MMU2 for it is free.
PAL_BASE        EQU $EE00               ; in the text page: 32 palettes x 16 x 2 = 1,024
NR_PAL_CTRL     EQU $43
NR_PAL_INDEX    EQU $40
NR_PAL_VALUE    EQU $44
; $43 selects which palette the index and value registers address. %0001_0000 is
; "Layer 2, first palette", with auto-increment left ON - which is what makes two
; writes per entry work, and it is the layout mkassets.py already emits.
PAL_SEL_L2      EQU %00010000
RING_ADDR       EQU $D400               ; permanently mapped; see the header
VOLTAB          EQU $DC00
VOICES          EQU $DD00
; THE C AND THE ASSEMBLY MUST AGREE ON THESE, and they are set in two files: AW_IN and
; AW_DRAW in the Makefile, IN_BLOCK and DRAW_BLOCK here. Moving one without the other made
; the C write its polygon parameters to $D310 while this read $C390 - all zeros, so the
; reader was called 151 times and drew nothing, and check-aw reported "the reader draws
; nothing" with no hint that the address was the problem. There is no way to assert across
; two toolchains, so they are named together here instead.
IN_BLOCK        EQU $C380               ; the six input words the C reads; = AW_IN
DRAW_BLOCK      EQU $C390               ; aw_draw_poly's parameters; = AW_DRAW
; TEN BYTES A DRAW: the page, and the five parameters the C computed from the opcode.
;
; This replaced a one-byte-a-draw page log, which did its job and proved the pages right -
; every one of 55 draws went where the engine's went. So the remaining suspect is the one
; thing nothing has ever compared: Gate D proves the opcode STREAM - thread, pc, opcode -
; and says nothing about the OPERANDS the C derives from it. The two polygon forms compute
; an offset, a zoom, a centre and a colour, with a diagonal slide in one of them and a
; zoom applied before the scale in the other, and the engine's trace records exactly those
; five for every draw.
; I4's text data lives in bank 0's SECOND half - the 8K page that is MMU7=1 at boot and
; unused after it. The font and the string dictionary are 3.5K together and the resident
; region has nothing like that left, so they stay in their own page and get mapped at MMU2
; while a string is drawn. MMU2 is the polygon window, which is idle during text: nothing
; reads a polygon segment and draws a glyph at the same time.
TEXT_PAGE       EQU 1                   ; bank 0's second half
TEXT_WIN        EQU $4000               ; where it appears while text is drawn
NR_TEXT_MMU     EQU $52
FONT6_AT        EQU $E000               ; as ASSEMBLED; read at TEXT_WIN + (x - $E000)
STR_INDEX_AT    EQU $E300
; NOT a hand-computed address: str_index and str_blob are labels in the generated file, and
; the code uses those. The first version guessed $E53C for the blob where the index's 556
; bytes actually put it at $E52C, which would have made every string sixteen bytes adrift
; with nothing to say so.
STR_BLOCK       EQU $C3A0               ; colour, x, y, id - what the C leaves for us
MUS_BLOCK       EQU $C3B0               ; resNum, delay, pos - what op_playMusic leaves
; The module's window. Its patterns run to 15,552 bytes so they cannot be resident; the
; header and order table are copied out once at load, and a pattern block is read through
; a window when an event is due. MMU2 is free at the FRAME BOUNDARY, which is where events
; are handled - not in the interrupt, where a polygon draw may own MMU2 mid-record.
; The order table and the instrument list are copied out of the module once and read on
; every event, so they are DATA in MMU6's page rather than beside the code - the resident
; region is the binding constraint at every step now, and 158 bytes of table there costs
; 158 bytes of stack.
MUS_ORDER_AT    EQU $C400               ; 128 bytes
MUS_INSTR_AT    EQU $C480               ; 15 x 2
MUS_WIN         EQU $4000
NR_MUS_MMU      EQU $52
DRAW_LOG        EQU $C4A0
DRAW_LOG_MAX    EQU 8                   ; 8 x 10 bytes: the stack took the rest, and
                                        ; check-draw only ever prints the first eight

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
; The engine keeps FOUR pages and selects among them, so DST_P0 is only a starting value -
; dst_p0 tracks selectVideoPage from then on.
;
; SRC_PAGE IS PAGE 0 AND IT IS NOT A CHOICE. The rasteriser's copy-mode fill - the one a
; colour of $FF selects - reads its source from page 0 and nothing else: video.cpp:352 is
; `colb = *(_pages[0] + off)`. The harness had SRC_PAGE 2 because its own test drew from
; page 2, and inheriting that number put the game's copy-fill on the wrong source. It cost
; 2,756 wrong bytes on the intro's very first record, which is a full-screen black polygon
; drawn in exactly that mode - and it was invisible until page 0 had anything in it, which
; is why a one-record probe into a blank page came out identical.
DST_PAGE        EQU 1
SRC_PAGE        EQU 0
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
VEC_TABLE       EQU $CD00
VEC_FILL        EQU $CE
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
        jp      aw_load_res             ; $8018  void aw_load_res(uint16_t id)
        jp      aw_inval_res            ; $801B  void aw_inval_res(void)
        jp      aw_draw_string          ; $801E  I4
        jp      aw_play_music           ; $8021  I5
        ; THIRTY-SIX. src/aw/jumptab.asm declares the same addresses to the C and this ASSERT
        ; is the only thing that catches a slot added to one file and not the other - which is
        ; exactly what happened: the edits that were supposed to add these two slots used a
        ; string replacement with no check and matched nothing, so the table stayed at 30
        ; bytes while jumptab.asm declared _aw_play_music at $8021. $8021 is INSIDE start:.
        ; The C called into the middle of an instruction and the VM faulted eleven records in.
        ;
        ; I4 did not notice because its gate calls aw_draw_string directly in assembly and
        ; never through the table. A slot nothing calls is a slot nothing tests.
        ASSERT $ - jump_table == 36

start:
        di
        ; THE STACK IS IN MMU6's PAGE, not below the C. The resident 16K holds the assembly
        ; and the C's 7.8K, and every table added to it came straight off the stack - 1,137
        ; bytes by the time the module player went in, at which point the VM started faulting
        ; with "ret with an empty stack" and two other gates broke.
        ;
        ; MMU6 is never remapped, so a stack there is always present. SAVENEX still declares
        ; $BF00 because the .nex LOADER uses it while bank 0 is being written, and pointing it
        ; at bank 0 is what broke the load when this was tried at $FF00. The switch happens
        ; here, once the loader is done.
        ld      sp, STACK_TOP
        nextreg NR_TURBO, 3

        ; MMU6 is deliberately NOT touched: bank 0's first half is where the ring
        ; and the tables already are, loaded by the .nex.
        ; the rasteriser's band base has to agree with pg_ptr1 before the first draw
        ld      a, (pg_ptr1)
        call    page_to_p0
        ld      (dst_p0), a
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
        call    load_code               ; the bytecode segment, into CODE_PAGE
        ld      a, (err)
        or      a
        jr      nz, .loaded

        ; AND THE CINEMATIC SEGMENT, which the polygon reader reads. A part is four
        ; resources (parts.cpp:14-28) and the intro's are palette $17, code $18,
        ; video1 $19 and no video2; this is $19. Loading it here rather than on demand is
        ; I2's scope: making updateMemList do it is I3.
        ld      a, POLY_PAGE
        ld      (ld_page), a
        ld      hl, poly_name
        ld      de, fname
        ld      bc, 10
        ldir
        call    load_code
        ld      a, CODE_PAGE
        ld      (ld_page), a            ; put it back for anything that follows

        ; and the part's palettes, 1,024 bytes at a fixed address
        ld      hl, pal_name
        ld      de, fname
        ld      bc, 10
        ldir
        ld      de, PAL_BASE            ; MMU7 still maps the text page here
        ld      bc, 1024
        call    load_flat
.loaded:
        ei
        ld      a, (err)
        or      a
        jr      nz, .stop
        ld      hl, (got)
        ld      (CTL + $10), hl         ; the segment length, for the pc guard

        ; A PROBE PATH: one draw from a poked DRAW_BLOCK, with the C never entered.
        ; It exists to settle one question - whether the reader gets a particular record
        ; wrong on its own, or whether aw_draw_poly sets it up wrong. Those need separating
        ; and no existing gate separates them: check-readmachine drives the reader from a
        ; poked list in the HARNESS, and check-draw drives it from the VM in the GAME.
        ; probe_mus holds a resource id: load it and hand it to the player, no VM. The
        ; module has to be RESIDENT before its header can be read, so this does the load
        ; through the same aw_load_res the bytecode would have used.
        ; probe_note: convert the period at MUS_BLOCK+4 and leave the increment beside it.
        ld      a, (probe_note)
        or      a
        jr      z, .not_note
        ld      hl, (MUS_BLOCK + 4)
        call    note_to_inc
        ld      (MUS_BLOCK + 6), hl
        jr      .stop
.not_note:
        ld      a, (probe_mus)
        or      a
        jr      z, .not_mus
        ld      l, a
        ld      h, 0
        call    aw_load_res
        call    aw_play_music
        jr      .stop
.not_mus:
        ld      a, (probe_str)
        or      a
        jr      z, .not_str
        ld      a, (pg_ptr1)
        call    page_to_p0
        ld      (dst_p0), a
        ld      a, 255
        ld      (cur_band), a
        call    aw_draw_string
        jr      .stop
.not_str:
        ld      a, (probe_draw)
        or      a
        jr      z, .run_vm
        ld      a, (pg_ptr1)            ; the checker chooses the page
        call    page_to_p0
        ld      (dst_p0), a
        ld      a, 255
        ld      (cur_band), a
        ; OPTIONALLY FILL PAGE 0 FIRST, because that is the difference between the probe
        ; passing and the VM failing. A colour of $FF selects the copy-mode fill, which
        ; reads page 0 - so over a blank page it copies zeros onto zeros and cannot be
        ; wrong. probe_fill holds colour+1, so 0 means "leave it blank".
        ld      a, (probe_fill)
        or      a
        jr      z, .no_prefill
        dec     a
        ld      h, a
        ld      l, 0                    ; page 0, colour in H - aw_fill_page's argument
        call    aw_fill_page
.no_prefill:
        call    aw_draw_poly
        jr      .stop
.run_vm:
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
; I3. loadPartsOrMemoryEntry, resource.cpp:258, for the part of it that loads.
;
; The reference keeps two allocation zones in one block and walks a memList whose state
; bytes say what is wanted. Ours is simpler and has to be: a resource goes into whole 8K
; pages taken from a cursor, and res_page remembers where each one went so a second
; request for the same id is free - which the reference gets from its state byte.
;
; What it does NOT do is unload. invalidateRes resets the cursor wholesale, which is what
; the reference's own comment describes it as doing to everything not permanent. Keeping
; individual resources alive across an invalidate is I6's problem, when parts change.
;-----------------------------------------------------------------------------
aw_load_res:
        ld      (jt_arg), hl
        ld      a, h
        or      a
        ret     nz                      ; ids are bytes; anything larger is not ours
        ld      a, l
        cp      RES_COUNT
        ret     nc
        ; already loaded? res_page holds the first page, or zero
        ld      h, 0
        ld      l, a
        ld      de, res_page
        add     hl, de
        ld      a, (hl)
        or      a
        ret     nz                      ; the reference's LOADED state, in one byte

        ; look the entry up: four bytes each, type, size as a word, pages
        ld      a, (jt_arg)
        ld      h, 0
        ld      l, a
        add     hl, hl
        add     hl, hl
        ld      de, res_table
        add     hl, de
        ld      a, (hl)
        ld      (res_type), a
        inc     hl
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ld      (res_size), de
        inc     hl
        ld      a, (hl)
        ld      (res_pages), a
        or      a
        ret     z                       ; a zero-length entry: nothing to fetch

        ; is there room? running out is a fault, not a wrap onto something else
        ld      hl, next_page
        add     a, (hl)
        sub     RES_FIRST_PAGE
        cp      RES_MAX_PAGES + 1
        jr      c, .room
        ld      a, 1
        ld      (res_full), a
        ret
.room:
        ; the name: PAL for a palette, BMP for a full-screen bitmap, RES for the rest,
        ; which is exactly what mkassets.py writes
        ld      hl, nm_res
        ld      a, (res_type)
        cp      3
        jr      nz, .not_pal
        ld      hl, nm_pal
.not_pal:
        ld      a, (res_type)
        cp      2
        jr      nz, .not_bmp
        ld      hl, nm_bmp
.not_bmp:
        ld      de, fname
        ld      bc, 4
        ldir                            ; the three letters and the first hex digit slot
        ld      a, (jt_arg)
        rrca
        rrca
        rrca
        rrca
        call    hex_digit
        ld      (fname + 3), a
        ld      a, (jt_arg)
        call    hex_digit
        ld      (fname + 4), a
        ld      hl, nm_tail
        ld      de, fname + 5
        ld      bc, 5
        ldir                            ; ".BIN" and the terminator

        ld      a, (next_page)
        ld      (ld_page), a
        di                              ; esxDOS wants the interrupt off: see load_code
        call    load_code
        ei
        ld      a, CODE_PAGE
        ld      (ld_page), a

        ld      a, (err)
        or      a
        jr      z, .loaded
        ld      (res_err), a
        ret
.loaded:
        ld      a, (jt_arg)
        ld      h, 0
        ld      l, a
        ld      de, res_page
        add     hl, de
        ld      a, (next_page)
        ld      (hl), a                 ; where it went
        ld      hl, next_page
        ld      a, (res_pages)
        add     a, (hl)
        ld      (hl), a                 ; and the cursor past it
        ld      hl, (n_load)
        inc     hl
        ld      (n_load), hl
        ret

; invalidateRes, resource.cpp:229. The reference marks everything not permanent as
; absent; ours forgets the lot and rewinds the cursor.
aw_inval_res:
        ld      hl, res_page
        ld      de, res_page + 1
        ld      bc, RES_COUNT - 1
        ld      (hl), 0
        ldir
        ld      a, RES_FIRST_PAGE
        ld      (next_page), a
        ld      hl, (n_inval)
        inc     hl
        ld      (n_inval), hl
        ret

; A = low nibble in, the ASCII hex digit out. Uppercase, because that is what
; mkassets.py wrote and esxDOS on a FAT card does not have to be case-blind.
hex_digit:
        and     $0F
        add     a, '0'
        cp      '9' + 1
        ret     c
        add     a, 'A' - '0' - 10
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

        ; snd_off exists to answer one question: does the mixing inside this interrupt
        ; disturb a draw in progress? The rasteriser and the mixer both patch immediate
        ; operands in their own code, and both use the shadow registers, so the question
        ; is a fair one and no gate has ever asked it.
        ld      a, (snd_off)
        or      a
        jr      nz, .no_mix
        ld      a, BLK_A
        call    mix_block
        ld      a, BLK_B
        call    mix_block
.no_mix:

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
        ld      (cp_dstid), a           ; the destination id, in MEMORY not in B -
                                        ; page_to_p0 uses B (`ld b, a`) and clobbered it,
                                        ; so the `ld a, b` meant to recover the
                                        ; destination read rubbish and both ends resolved
                                        ; to page 0. The copy then copied page 0 onto
                                        ; itself and pages 1 and 2 stayed empty. This
                                        ; project's own traps list warns about exactly
                                        ; this - helpers that build an index clobber the
                                        ; register you were holding a value in.
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
        ld      a, (cp_dstid)
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
        ; STOPPING AT A BLIT is how the picture gets compared. A blit is the one moment
        ; both the machine and the reference agree what the frame IS - the VM's frames and
        ; the probe's frames are different quantities, since instrFrame hangs off
        ; updateDisplay and counts blits. So the checker names a blit and the C's own
        ; out-of-budget flag stops the frame loop cleanly after it.
        ld      de, (stop_blit)
        ld      a, d
        or      e
        jr      z, .no_stop
        ld      a, l
        cp      e
        jr      nz, .no_stop
        ld      a, h
        cp      d
        jr      nz, .no_stop
        ld      a, 1
        ld      (CTL + $0B), a          ; CTL_OUT_OF_BUDGET: the loop breaks on it
.no_stop:
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
; changePal, video.cpp:587. The reference copies sixteen 2-byte colours into the host's
; palette; ours writes them into Layer 2's first palette, which is the same operation on
; different hardware. mkassets.py has already converted every colour to the two bytes
; NextReg $44 wants - RRRGGGBB then the low bit of blue - and laid the part's 32 palettes
; out in order, so this is an index write and 32 value writes with auto-increment doing
; the rest.
;
; It is NOT a bank select, which is what this comment used to claim. Two 256-entry
; palettes do hold all 512 entries, but Layer 2 indexes its palette from the pixel byte
; with no offset to add, so a part's sixteen live colours have to BE entries 0-15. The
; second palette is for a double-buffered palette change, not for holding palette 17.
apply_palette:
        ld      (pal_now), a
        ld      l, a
        ld      h, 0
        add     hl, hl                  ; * 32: sixteen entries of two bytes
        add     hl, hl
        add     hl, hl
        add     hl, hl
        add     hl, hl
        ld      de, PAL_BASE - $E000 + TEXT_WIN
        add     hl, de                  ; HL = this palette's first byte, through the window
        nextreg NR_TEXT_MMU, TEXT_PAGE  ; the palette lives in the text page
        nextreg NR_PAL_CTRL, PAL_SEL_L2
        nextreg NR_PAL_INDEX, 0
        ld      b, 32
.one:
        ld      a, (hl)
        inc     hl
        nextreg NR_PAL_VALUE, a
        djnz    .one
        ret

;-----------------------------------------------------------------------------
; load_flat - (fname) straight into memory at DE, BC bytes, no paging.
;
; The banked loader stages through a window and walks eight pages; a palette is 1,024
; bytes and belongs at a fixed address, so it gets its own three calls rather than a
; special case inside the other one.
;-----------------------------------------------------------------------------
load_flat:
        ld      (lf_dst), de
        ld      (lf_len), bc
        ld      a, ESX_DRIVE
        ld      ix, fname
        ld      hl, fname
        ld      b, FA_READ
        rst     $08
        db      F_OPEN
        jr      nc, .opened
        ld      (err), a
        ret
.opened:
        ld      (handle), a
        ; esxDOS takes the buffer in IX for a machine-code caller and HL for a BASIC
        ; one, so both are set - the trap wolf3d-next paid for when CSpect wrote a
        ; filename over the code that followed it.
        ld      ix, (lf_dst)
        ld      hl, (lf_dst)
        ld      bc, (lf_len)
        ld      a, (handle)
        rst     $08
        db      F_READ
        jr      nc, .read
        ld      (err), a
.read:
        ld      a, (handle)
        rst     $08
        db      F_CLOSE
        ret

lf_dst:     dw 0
lf_len:     dw 0

; readAndDrawPolygon / readAndDrawPolygonHierarchy, video.cpp:85 and :222. The C has
; already computed the six parameters the two opcode forms produce and left them in
; DRAW_BLOCK; this sets the reader's state from them and calls the reader that
; check-readmachine gates over 17 real draws and 59 polygons.
aw_draw_poly:
        ; THE STOP TEST COMES FIRST AND SKIPS THE DRAW, which took one wrong attempt to
        ; get right. Setting the out-of-budget flag AFTER drawing stops the frame LOOP,
        ; but the thread already running carries on until it yields - so asking to stop
        ; after draw 1 let 51 through. To hold the page at exactly N draws the test has to
        ; refuse the draw, not end the loop after it.
        ; $FFFF means never, so that zero can mean "not even the first one".
        ld      hl, (stop_draw)
        ld      a, h
        and     l
        inc     a                       ; $FFFF -> 0
        jr      z, .no_limit
        ld      de, (n_poly)
        ld      hl, (stop_draw)
        or      a
        sbc     hl, de
        jr      nz, .no_limit           ; not there yet, or already past
        ld      a, 1
        ld      (CTL + $0B), a          ; CTL_OUT_OF_BUDGET ends the frame loop
        ret                             ; and this draw does NOT happen
.no_limit:
        ld      hl, (n_poly)
        inc     hl
        ld      (n_poly), hl

        ; log this draw's page and parameters, while HL still holds the count
        ; HL is the count AFTER incrementing, so the index is one less - and the bound
        ; has to be tested on the index, not the count, or the last slot is never written.
        ; It showed as draw 19 of 20 reading back as zeros.
        dec     hl                      ; zero-based index
        ld      de, DRAW_LOG_MAX
        or      a
        sbc     hl, de
        jr      nc, .no_log
        add     hl, de
        ld      d, h
        ld      e, l
        add     hl, hl                  ; * 10
        add     hl, hl
        add     hl, de
        add     hl, hl
        ld      de, DRAW_LOG
        add     hl, de
        ex      de, hl                  ; DE = this entry
        ld      a, (pg_ptr1)
        ld      (de), a
        inc     de
        ld      hl, DRAW_BLOCK
        ld      bc, 10 - 1              ; off, zoom, x, y, colour, video2 - 9 of 10
        ldir
.no_log:

        ; THE COPY-MODE FILL'S SOURCE BAND BORROWS MMU0, which is the bytecode window,
        ; so what was there is saved and put back before the C runs another instruction.
        ; Reading a NextReg back needs the register selected on $243B and the value read
        ; from $253B; the project already learned that port $123B is write-only here, so
        ; nothing is assumed to be readable without checking it is.
        ld      bc, $243B
        ld      a, NR_MMU0
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      (saved_mmu0), a

        ld      hl, (DRAW_BLOCK + 0)
        ld      (rd_off), hl
        ld      hl, (DRAW_BLOCK + 2)
        ld      (rd_zoom), hl
        ld      hl, (DRAW_BLOCK + 4)
        ld      (rd_ptx), hl
        ld      hl, (DRAW_BLOCK + 6)
        ld      (rd_pty), hl
        ld      a, (DRAW_BLOCK + 8)
        ld      (rd_col), a

        ; video2 chooses the SEGMENT, not the page: setDataBuffer is handed either the
        ; part's cinematic data or its video2 data (vm.cpp's two polygon forms). Only the
        ; cinematic segment is loaded so far, so a video2 draw is counted and skipped
        ; rather than drawn out of the wrong segment.
        ld      a, (DRAW_BLOCK + 9)
        or      a
        jr      z, .cinematic
        ld      hl, (n_video2)
        inc     hl
        ld      (n_video2), hl
        jr      .restore
.cinematic:
        ld      a, POLY_PAGE
        ld      (seg_base), a
        xor     a
        ld      (rd_depth), a
        ld      (rd_stop), a
        call    poly_read
.restore:
        ld      a, (saved_mmu0)
        nextreg NR_MMU0, a
        ret

;-----------------------------------------------------------------------------
; I5. loadSfxModule, sfxplayer.cpp. The header is copied out of the module once, because
; every field in it is read on every event and paging a window in to fetch two bytes is
; absurd. The patterns are not: they run to 15,552 bytes.
;
; The layout, big-endian throughout:
;   0x00  delay, a word - the default if op_playMusic passes zero
;   0x02  fifteen instruments of four bytes: a resource number and a volume, both words
;   0x3E  numOrder, a word
;   0x40  the order table, 0x80 bytes
;   0xC0  the pattern blocks, 1024 bytes each, selected by the order table
;
; tools/sfxmod.py decodes the same thing on the host and is this routine's oracle.
;-----------------------------------------------------------------------------
aw_play_music:
        ld      a, (MUS_BLOCK + 0)      ; the resource number
        or      a
        jr      nz, .have
        ; resNum zero: the reference treats that as "carry on", and pos zero as a rewind
        ret
.have:
        ld      (mus_res), a
        ; where did aw_load_res put it? zero means it never arrived
        ld      h, 0
        ld      l, a
        ld      de, res_page
        add     hl, de
        ld      a, (hl)
        or      a
        jr      nz, .resident
        ld      hl, (n_mus_miss)
        inc     hl
        ld      (n_mus_miss), hl
        ret
.resident:
        ld      (mus_page), a
        nextreg NR_MUS_MMU, a           ; the module's first 8K at $4000

        ; the default delay, big-endian at 0x00
        ld      a, (MUS_WIN + 0)
        ld      h, a
        ld      a, (MUS_WIN + 1)
        ld      l, a
        ld      (mus_delay_raw), hl
        ; op_playMusic's delay wins if it is not zero
        ld      hl, (MUS_BLOCK + 1)
        ld      a, h
        or      l
        jr      z, .use_default
        ld      (mus_delay_raw), hl
.use_default:
        ; numOrder, big-endian at 0x3E - a byte in practice, and the reference reads a word
        ld      a, (MUS_WIN + $3F)
        ld      (mus_num_order), a
        ; the order table, 0x80 bytes from 0x40, copied out
        ld      hl, MUS_WIN + $40
        ld      de, MUS_ORDER_AT
        ld      bc, $80
        ldir
        ; the fifteen instruments: a resource number and a volume, both big-endian
        ld      hl, MUS_WIN + 2
        ld      de, MUS_INSTR_AT
        ld      b, 15
.instr:
        ld      a, (hl)                 ; resource, high byte
        inc     hl
        ld      c, (hl)                 ; low
        inc     hl
        ld      a, c
        ld      (de), a                 ; only the low byte can be a resource id
        inc     de
        inc     hl                      ; volume, high byte - always zero here
        ld      a, (hl)
        inc     hl
        ld      (de), a                 ; the volume
        inc     de
        djnz    .instr

        ld      a, (MUS_BLOCK + 3)      ; the starting order
        ld      (mus_cur_order), a
        ld      hl, 0
        ld      (mus_cur_pos), hl
        ld      a, 1
        ld      (mus_playing), a
        ld      hl, (n_mus)
        inc     hl
        ld      (n_mus), hl
        ret

;-----------------------------------------------------------------------------
; note_to_inc - HL = an Amiga period, out as the mixer's 8.8 sample increment.
;
; The reference turns a period into a frequency with `7159092 / (note_1 * 2)`
; (sfxplayer.cpp) and our mixer steps its pointer in 8.8 fixed point at the DAC's rate,
; which prescalar 40 makes 875,000 / 40 = 21,875 Hz. So the increment wanted is
;
;     freq * 256 / 21875  =  (7159092 / (2 * note)) * 256 / 21875  =  41891 / note
;
; ONE 16-BY-16 DIVIDE instead of a 24-bit divide followed by a multiply and another divide.
; Checked against the reference's own arithmetic over every valid period, 0x37 to 0xFFF: the
; largest disagreement is 0.012 of a 1/256th step, which is four thousandths of a semitone.
;
; A period of zero cannot happen - handlePattern tests note_1 against 0, 0xFFFD and 0xFFFE
; before ever reaching here - but it returns the maximum rather than dividing by it.
;-----------------------------------------------------------------------------
NOTE_NUM        EQU 41891               ; 7159092 * 256 / (2 * 21875)

note_to_inc:
        ld      a, h
        or      l
        jr      nz, .ok
        ld      hl, $FFFF
        ret
.ok:
        ld      c, l
        ld      b, h                    ; BC = the divisor
        ld      hl, 0                   ; HL = the remainder as it builds
        ld      de, NOTE_NUM            ; DE = the dividend, and the quotient replaces it
        ld      a, 16
.loop:
        ex      de, hl
        add     hl, hl                  ; shift the dividend left, top bit into carry
        ex      de, hl
        adc     hl, hl                  ; and into the remainder
        sbc     hl, bc
        jr      nc, .fits
        add     hl, bc                  ; it did not fit: put it back
        dec     e                       ; and the quotient bit stays clear
        inc     e
        jr      .next
.fits:
        inc     e                       ; set the quotient's low bit
.next:
        dec     a
        jr      nz, .loop
        ex      de, hl                  ; HL = the quotient, 8.8
        ret

;-----------------------------------------------------------------------------
; I4. drawString, video.cpp:267, and drawChar, video.cpp:299.
;
; The string id, colour and position arrive in STR_BLOCK. The dictionary is searched by
; BISECTION rather than walked - the reference walks 264 entries per string because it can
; afford to, and mkstrings.py sorts the index so we need not.
;
; A newline moves down eight rows and back to the starting column (video.cpp:288), so it is
; a line break and never a glyph.
;-----------------------------------------------------------------------------
aw_draw_string:
        ld      a, (STR_BLOCK + 0)
        ld      (str_col), a
        ld      a, (STR_BLOCK + 1)
        ld      (str_x), a
        ld      (str_x0), a             ; a newline returns here
        ld      a, (STR_BLOCK + 2)
        ld      (str_y), a
        ld      hl, (STR_BLOCK + 4)
        ld      (str_id), hl

        nextreg NR_TEXT_MMU, TEXT_PAGE  ; the font and the dictionary, at $4000

        ; bisect str_index for the id: four bytes an entry, id then blob offset
        ld      bc, 0                   ; B = lo, C = hi
        ld      c, STR_COUNT
.bisect:
        ld      a, b
        cp      c
        jr      nc, .not_found
        add     a, c
        rra                             ; mid = (lo + hi) / 2, carry is safe: < 512
        ld      e, a                    ; E = mid
        ld      h, 0
        ld      l, a
        add     hl, hl
        add     hl, hl
        ld      de, str_index - $E000 + TEXT_WIN
        add     hl, de                  ; HL = &entry
        ld      e, (hl)
        inc     hl
        ld      d, (hl)                 ; DE = this entry's id
        inc     hl
        push    hl                      ; -> the offset
        ld      hl, (str_id)
        or      a
        sbc     hl, de
        pop     hl
        jr      z, .found
        jr      c, .lower
        ; wanted > this: lo = mid + 1
        ld      a, b
        add     a, c
        rra
        inc     a
        ld      b, a
        jr      .bisect
.lower:
        ld      a, b
        add     a, c
        rra
        ld      c, a                    ; hi = mid
        jr      .bisect
.not_found:
        ld      hl, (n_str_miss)
        inc     hl
        ld      (n_str_miss), hl
        ret                             ; drawString returns silently too
.found:
        ld      e, (hl)
        inc     hl
        ld      d, (hl)                 ; DE = offset into the blob
        ld      hl, str_blob - $E000 + TEXT_WIN
        add     hl, de
        ld      (str_ptr), hl
        ld      hl, (n_str)
        inc     hl
        ld      (n_str), hl

.next_ch:
        ld      hl, (str_ptr)
        ld      a, (hl)
        inc     hl
        ld      (str_ptr), hl
        or      a
        ret     z                       ; the terminator
        cp      10                      ; '\n': down eight rows, back to the start
        jr      nz, .glyph
        ld      a, (str_y)
        add     a, 8
        ld      (str_y), a
        ld      a, (str_x0)
        ld      (str_x), a
        jr      .next_ch
.glyph:
        call    draw_char6
        ld      a, (str_x)
        inc     a
        ld      (str_x), a
        jr      .next_ch

;-----------------------------------------------------------------------------
; draw_char6 - A = the character, at (str_x) cells and (str_y) rows, in (str_col).
;
; Six pixels a cell and forty cells in 240 of our 256: the decision in tools/mkfont6.py.
; The y origin is SCALED like every other coordinate and the glyph is not, because a
; vertically scaled eight-row glyph is unreadable.
;
; Each of the eight rows may sit in a different Layer 2 band, so the band is mapped per row
; rather than per glyph - cheap, and it is the only way a glyph that straddles row 32 comes
; out whole.
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

        ld      a, (str_x)
        cp      40
        ret     nc                      ; x <= 39, as drawChar requires
        ld      b, a
        add     a, a
        add     a, b
        add     a, a                    ; x * 6
        ld      (gl_x), a

        ; scale_uy takes HL, NOT A. Passing the row in A scaled whatever HL happened to
        ; hold, and the glyph landed a row out - which showed as both sides drawing exactly
        ; twenty pixels for an 'A' with the first disagreement one row above the machine's.
        ld      a, (str_y)
        ld      l, a
        ld      h, 0
        call    scale_uy                ; the same Y scale every coordinate gets
        ld      a, l
        ld      (gl_y), a

        ld      b, 8                    ; eight rows
.row:
        ld      a, (gl_y)
        cp      SCR_H
        ret     nc                      ; off the bottom: stop, do not wrap
        ; the band, mapped per row
        rlca
        rlca
        rlca
        and     7
        ld      hl, cur_band
        cp      (hl)
        jr      z, .band_ok
        ld      (hl), a
        ld      hl, dst_p0
        add     a, (hl)
        nextreg NR_DWIN_MMU, a
.band_ok:
        ld      a, (gl_y)
        and     31
        ld      h, a
        ld      l, 0                    ; (y & 31) << 8
        ld      a, (gl_x)
        ld      e, a
        ld      d, 0
        add     hl, de
        ld      de, DWIN
        add     hl, de                  ; HL = the pixel row's first byte
        ld      de, (gl_src)
        ld      a, (de)                 ; the glyph row
        inc     de
        ld      (gl_src), de
        ld      c, a
        ld      a, (str_col)
        ld      d, a                    ; D = the colour
        ld      e, 6                    ; six columns
.col:
        rl      c                       ; the top bit out into carry
        jr      nc, .skip
        ld      (hl), d
.skip:
        inc     hl
        dec     e
        jr      nz, .col

        ld      a, (gl_y)
        inc     a
        ld      (gl_y), a
        dec     b
        jp      nz, .row
        ret

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
; PAGE 2, NOT PAGE 0. Video::init sets ptr3 to page 1 and ptr2 to page 2 and then calls
; changePagePtr1($FE) - video.cpp:56-60 - and $FE resolves to ptr2, so drawing starts on
; page 2. Starting it at 0 put every early polygon in the wrong page, which check-draw
; showed as our content in page 0 and the engine's in pages 1 and 2.
pg_ptr1:    db 2                        ; the page drawing goes into
        EXPORT pg_ptr2
; THESE TWO WERE THE WRONG WAY ROUND. video.cpp:56-57 is
;     _curPagePtr3 = getPage(1);
;     _curPagePtr2 = getPage(2);
; so ptr2 is page 2 and ptr3 is page 1, and I had them swapped. The cost: `copy dst=$FF`
; resolves through ptr3, so the intro's page-0-to-page-1 copies went to page 2 instead,
; and every display swap after that was offset by one. check-draw showed it as the
; engine's content in pages 1 and 2 against zeros in ours.
pg_ptr2:    db 2                        ; the page being displayed
        EXPORT pg_ptr3
pg_ptr3:    db 1                        ; the other display page
fill_col:   db 0
        EXPORT stop_blit
stop_blit:  dw 0            ; stop the frame loop after this many blits; 0 = never
        EXPORT snd_off
snd_off:    db 0            ; 1 = the interrupt ticks but does not mix: a discriminator
        EXPORT cur_band_x
cur_band_x: db 0
        EXPORT probe_note
probe_note: db 0            ; 1 = convert one period and stop
        EXPORT probe_mus
probe_mus:  db 0            ; a resource id: load it and parse it, no VM
        EXPORT probe_str
probe_str:  db 0            ; 1 = draw one string from STR_BLOCK and stop, no VM
        EXPORT probe_fill
probe_fill: db 0            ; colour+1 to fill page 0 with before the probe draw
        EXPORT probe_draw
probe_draw: db 0            ; 1 = do one draw from DRAW_BLOCK and stop, no VM
        EXPORT stop_draw
stop_draw:  dw $FFFF        ; refuse the draw once this many have happened; $FFFF = no limit
saved_mmu0: db 0
        EXPORT n_video2
n_video2:   dw 0        ; draws that wanted the video2 segment, which is not loaded yet
        EXPORT cp_src
cp_src:     db 0
        EXPORT cp_dst
cp_dst:     db 0
cp_dstid:   db 0
        EXPORT cp_unimpl
cp_unimpl:  db 0                        ; a scrolled copy was asked for: I2 remainder
        EXPORT pal_req
pal_req:    db $FF                      ; $FF = no palette change requested
        EXPORT pal_now
pal_now:    db $FF
poly_name:  db "RES19.BIN", 0
nm_res:     db "RES", 0
nm_pal:     db "PAL", 0
nm_bmp:     db "BMP", 0
nm_tail:    db ".BIN", 0
        EXPORT mus_res
mus_res:        db 0
        EXPORT mus_page
mus_page:       db 0
        EXPORT mus_delay_raw
mus_delay_raw:  dw 0
        EXPORT mus_num_order
mus_num_order:  db 0
        EXPORT mus_cur_order
mus_cur_order:  db 0
        EXPORT mus_cur_pos
mus_cur_pos:    dw 0
        EXPORT mus_playing
mus_playing:    db 0
        EXPORT n_mus
n_mus:          dw 0
        EXPORT n_mus_miss
n_mus_miss:     dw 0
str_col:    db 0
str_x:      db 0
str_x0:     db 0
str_y:      db 0
str_id:     dw 0
str_ptr:    dw 0
gl_src:     dw 0
gl_x:       db 0
gl_y:       db 0
        EXPORT n_str
n_str:      dw 0
        EXPORT n_str_miss
n_str_miss: dw 0
res_type:   db 0
res_size:   dw 0
res_pages:  db 0
        EXPORT res_err
res_err:    db 0
        EXPORT res_full
res_full:   db 0            ; the heap reservation was exceeded
        EXPORT next_page
next_page:  db RES_FIRST_PAGE
        EXPORT n_load
n_load:     dw 0
        EXPORT n_inval
n_inval:    dw 0

pal_name:   db "PAL17.BIN", 0
rd_log:     ds 8 * 8                    ; the reader's leaf log, small: nothing reads it

        DISPLAY "> resident code and data end at ", /H, $
        ASSERT $ < CC_ORG

        ORG CTL
        EXPORT ctl
; THIRTY-TWO records, matching AW_LOG_RECS in the Makefile - which is the number the C was
; given. This said 256 while the C used 32, so the assembly reserved 1,056 bytes to $C41F and
; every table placed from $C0A0 onward - the resource tables, the input and draw blocks, the
; music blocks - sat INSIDE that reservation. Nothing corrupted, because `ds` only reserves,
; but the layout could not be reasoned about and the asserts were all measuring the wrong end.
AW_LOG_RECS     EQU 32                  ; = AW_LOG_RECS in the Makefile
ctl:        ds 32 + AW_LOG_RECS * 4     ; the control block, then its records
        ASSERT $ <= RES_TABLE_AT        ; the records must not reach the resource tables

        ; THE RECIPROCAL TABLE, where the expected opcode stream used to be.
        ;
        ; I1's gate compared the game's opcode stream against the engine's from inside
        ; the .nex, and it passed - 763 of 763. But the rasteriser needs 1,024
        ; reciprocals resident and the resident 16K cannot hold the assembly, the C and
        ; 2KB of table at once. I2's gate is the PICTURE, compared page for page against
        ; the engine, which is a stronger claim than the stream anyway: a wrong opcode
        ; that does not change what is drawn is not interesting, and one that does shows
        ; up here.
        ; I3's tables, after the trace buffer's 32 records
        ORG RES_TABLE_AT
        EXPORT res_page
res_page:   ds RES_COUNT    ; the first page of each loaded resource, 0 = absent
        INCLUDE "build/reslist.inc"
        DISPLAY "> resource tables end at ", /H, $
        ASSERT $ <= PAL_BASE

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
        ; EVERY small block asserted, because STR_BLOCK sat inside DRAW_LOG's 200 bytes
        ; for three commits and only escaped notice because the two probe paths that use
        ; them never run together.
        ASSERT IN_BLOCK    >= RES_TABLE_AT + RES_COUNT + RES_COUNT * 4
        ASSERT DRAW_BLOCK  >= IN_BLOCK + 12
        ASSERT STR_BLOCK   >= DRAW_BLOCK + 10
        ASSERT MUS_ORDER_AT >= STR_BLOCK + 16
        ASSERT MUS_INSTR_AT >= MUS_ORDER_AT + $80
        ASSERT INTERP_AT    >= MUS_INSTR_AT + 30
        ASSERT VEC_TABLE   >= MUS_INSTR_AT + 30
        ASSERT VEC_TRAMP   >= VEC_TABLE + 257
        ASSERT STACK_FLOOR >= VEC_TRAMP + 3
        ASSERT STACK_TOP   <= RING_ADDR
        ASSERT DRAW_LOG    >= MUS_INSTR_AT + 30
        ASSERT DRAW_LOG + DRAW_LOG_MAX * 10 <= INTERP_AT

        ; I4's font and dictionary, in bank 0's second half. Mapped at MMU2 during text.
        ORG FONT6_AT
        INCBIN  "build/font6.bin"
        ASSERT $ <= STR_INDEX_AT
        ORG STR_INDEX_AT
        INCLUDE "build/strings.inc"
        DISPLAY "> text data ends at ", /H, $
        ASSERT $ < $FF00

        ORG CC_ORG
        INCBIN  "build/aw_vm_CODE.bin"
        DISPLAY "> the C is ", /D, $ - CC_ORG, " bytes at ", /H, CC_ORG
        ASSERT $ < VEC_TABLE

        SAVENEX OPEN "build/aw.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
