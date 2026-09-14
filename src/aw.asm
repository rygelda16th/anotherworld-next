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
CC_ORG          EQU $9C08               ; must match AW_VM_ORG in the Makefile
NR_TURBO        EQU $07
NR_MMU0         EQU $50
NR_MMU1         EQU $51
NR_MMU2         EQU $52
NR_MMU3         EQU $53
NR_MMU6         EQU $56
NR_MMU7         EQU $57

CODE_WIN        EQU $0000               ; what vmhost.inc slides the bytecode through
CODE_PAGE       EQU 48                  ; eight 8K pages for the bytecode segment
; I8. WHERE THE GAME STARTS. engine.cpp:71-73 - the protection screen IS GAME_PART1, and the
; bypass is `part = GAME_PART2` instead. Both are ordinary parts, so this is a starting index
; and not a feature: 0 is the wheel screen, 1 is the introduction cinematic. Build with
; -DBYPASS_PROTECTION (sjasmplus: --define BYPASS_PROTECTION) to skip the wheel.
    IFDEF BYPASS_PROTECTION
START_PART      EQU 1
    ELSE
START_PART      EQU 0
    ENDIF
POLY_PAGE       EQU 56                  ; and eight for the cinematic segment
; I3's heap: resources the bytecode asks for at runtime, allocated a page at a time.
;
; NINETY-SIX PAGES, NOT FORTY, and the forty was sized against the wrong number. The
; reference's high-water across the parts measured is 305,919 bytes - 38 pages - but that is
; a BYTE heap. Ours rounds every resource up to a whole 8K page, and this file's own memory-map
; section had already measured that waste at about 4K a resource across the 53 seen live, which
; is 27 pages of slack nobody added to the reservation.
;
; Part 2 found it. It asks for 45 loads, and at page 112 - exactly RES_FIRST_PAGE + 40 - the
; heap refused the rest: 23 resident, 22 dropped silently, and the polygon reader then walked a
; cinematic segment with holes in it for as long as it was left running. Pages 80-223 are free
; on the 2 MB profile the .nex asks for, so this costs nothing that was being used.
; I7. SIX PAGES OF BITMAP SCRATCH, between the cinematic segment's eight and the heap's forty.
; A full-screen bitmap is never resident: loadMarkedAsNeeded loads an RT_POLY_ANIM into a scratch
; pointer, presents it at once and marks it NOT_NEEDED (resource.cpp:193, :211-214). Part 7 loads
; seventy of them, and seventy times six pages is more memory than the machine has.
BMP_PAGE        EQU 64
; THE PROGRAM RAN OUT OF THE 48K IT CAN ADDRESS AT ONCE, and this is where the room comes from.
; Every ORG in this file is at $8000 or above, so $4000-$7FFF - pages 10 and 11, bank 5, sixteen
; kilobytes - is empty in the .nex image and SAVENEX never writes it. Code ORGed there lands in
; page 10 and runs at its own assembled address the moment page 10 is mapped at MMU2, which is
; where it lives at boot anyway.
;
; That is the right home for work that is RARE: save and load run at a frame boundary, once, so
; the two NextReg writes to page it in cost nothing measurable. It is NOT a home for anything
; per-frame, because MMU2 and MMU3 are the polygon segment window and every draw re-maps them.
;
; esxDOS pages ITSELF over the bottom 16K during a file call - $0000-$3FFF, not $4000 - so file
; calls made from code up here are safe, which is the whole reason the writer can live in it.
PAGED_PAGE      EQU 10
PAGED_WIN       EQU $4000
NR_PAGED_MMU    EQU $52                 ; MMU2, page 10's own slot at boot
RES_FIRST_PAGE  EQU 72
RES_MAX_PAGES   EQU 96                  ; pages 72..167; banks 40-111 stay free
DST_WIN         EQU $E000               ; the loader's staging, MMU7

CTL             EQU $C000
STACK_TOP       EQU $D400               ; grows down to $D0A0: 864 bytes
; THE STACK WAS 1,280 BYTES BY ESTIMATE AND USES 514 BY MEASUREMENT. awprobe trapped every write
; to $CF00-$D3FF under CSpect (AWPROBE_STACK) through the intro and parts 2 to 7, and the lowest
; address written was $D1FE in all seven - the same spot every time, so the deepest point is a
; path they share rather than anything scene-dependent. The bottom 416 bytes are code now: the
; music clock took 256, the dirty-band copies 128 and the blit's pacing 32. The stack keeps 1.68
; times the most it has been seen to use, which leaves room for polygon nesting deeper than those
; runs reached. Do not take more without measuring again.
STACK_FLOOR     EQU $D0A0
STACK_CODE      EQU $CF00               ; up to STACK_FLOOR: load_flat, the music clock, dirty bands
DIRTY_BANDS     EQU 1                   ; raster.inc's band_set reports every band it draws into
; Code ABOVE the C's image, in the tail the stack vacated when it moved into MMU6. The C is
; 7.8K from $9C00 and ends near $BB50, so this is the 1,100-odd bytes between that and $BF00 -
; which used to be stack and is now the only resident space left. Asserted at both ends.
; $BAD0, which is a dozen bytes past where the C's image ends. The ASSERT below the C's INCLUDE
; polices it, so a C that grows past here fails the build loudly rather than quietly overwriting
; the music code - and the 136 bytes reclaimed from the old $BB58 are what let I7's present_bitmap
; and voice_locate move up here when the resident block had nothing left.
MUSIC_CODE      EQU $BAE0
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
RING_END        EQU RING_ADDR + RING_LEN  ; page-aligned, which every wrap test relies on
VOLTAB          EQU $DC00
VOICES          EQU $DD00
; part_table, in the half of VOICES' slot that four 18-byte records do not use. It had been
; sitting wherever the part code happened to end, which put all but its first row on top of
; VOLTAB_QUIET - see the ORG for it, and its bound, near the reciprocal table.
;
; AND THE GAP HAS TO BE FREE AT RUN TIME, not just unclaimed by an ORG. The first attempt at
; this put the table at $CD00 because the assembled blocks left it empty - but VEC_TABLE is
; $CD00, built by install_im2 at boot, and the machine came up with no interrupt at all. A
; list of what the assembler places is not a map of memory.
PART_TABLE_AT   EQU $DD48               ; ten four-byte rows, directly after VOICES'
                                        ; four 18-byte records, which end at $DD48
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
SND_BLOCK       EQU $C3B4               ; resource, frequency index, volume, channel; = AW_SND
NOTE_CODE       EQU $C3B8               ; note_to_inc, in the gap before the order table
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
; A voice's sample page, borrowed into MMU7 by the mixer. MMU7 is also the Layer 2 draw band,
; so the interrupt that mixes has to put back what it found - see the ISR.
SAMP_WIN        EQU $E000
NR_SAMP_MMU     EQU $57

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
L2_VISIBLE      EQU %00000010           ; $123B bit 1: show Layer 2 at all
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
; $DE00 HELD A 256-BYTE RAMP and now holds code. It was I1's scaffolding: init_voices used to
; start four voices ACTIVE on it and ramp_sample filled it; check-snd's synthetic voices are
; sndtest's own, not these. The game starts silent, so nothing has read it since - and MMU6 is
; mapped at every moment, which is what aw_setup_part and probe_walk need and the resident block
; could not give them.
PART_CODE       EQU $DE00               ; aw_setup_part and probe_walk live here
; MMU3, NOT MMU2. aw_setup_part is called by the LOAD, which executes from page 10 - and page 10
; is mapped at MMU2. Mapping the palette resource there pulled the ground out from under the
; routine doing the mapping: the next instruction fetch came from palette data. It showed as a
; load that never finished with no esxDOS error to explain it. MMU3 holds page 11, which is
; empty, and the segment window is re-mapped from seg_base before every draw anyway.
NR_PAL_SRC_MMU  EQU $53
PAL_SRC_WIN     EQU $6000
NR_TEXT_MMU_HI  EQU $57                 ; MMU7: the text page, where PAL_BASE lives
; TWO VOLUME TABLES, which is David's decision of 2026-09-14 and not an omission. The mixer
; scales through a 256-byte table and only two page-aligned slots were free here, against nine
; distinct instrument volumes and effects that move them further. The alternatives were a
; multiply per sample - exact, and about nine percent more of a machine whose worst measured
; frame is already 74% - or four quantised levels needing a restructure. Two now, revisited at
; I10 once a real playthrough has been measured.
;
; VOLTAB is the loud one and it is the table check-snd already gates, built with VOLUME 48.
VOLTAB_QUIET    EQU $DF00
VOLUME_QUIET    EQU 24
VOL_SPLIT       EQU 32                  ; at or below this, quiet

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
; op_playSound's forty pitches, as 8.8 increments - eighty bytes, and they go in the gap the
; IM 2 VECTOR TABLE leaves. The table is 257 bytes of the one fill byte from $CD00, so it ends
; at $CE01, and its trampoline sits at $CECE because that is where a vector of $CE points. The
; 205 bytes between the two are otherwise dead, and this is the only region mapped at every
; moment - which a table read mid-opcode, outside the frame boundary, needs it to be.
SND_FREQ        EQU $CE04
; and the reader's leaf log goes in the same gap. It is 64 bytes of DATA in the block that had
; one byte left in it, and MMU6 is mapped at every moment too - which is what the log needs,
; since the reader writes it mid-draw.
RD_LOG_RECS     EQU 8
RD_LOG_AT       EQU $CE54
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
        jp      aw_play_sound           ; $8024  I5
        jp      aw_setup_part           ; $8027  I6
        ; THIRTY-SIX. src/aw/jumptab.asm declares the same addresses to the C and this ASSERT
        ; is the only thing that catches a slot added to one file and not the other - which is
        ; exactly what happened: the edits that were supposed to add these two slots used a
        ; string replacement with no check and matched nothing, so the table stayed at 30
        ; bytes while jumptab.asm declared _aw_play_music at $8021. $8021 is INSIDE start:.
        ; The C called into the middle of an instruction and the VM faulted eleven records in.
        ;
        ; I4 did not notice because its gate calls aw_draw_string directly in assembly and
        ; never through the table. A slot nothing calls is a slot nothing tests.
        ASSERT $ - jump_table == 42      ; fourteen slots; aw_setup_part made it fourteen

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
        call    l2_display              ; 28 MHz, and Layer 2 actually on the screen

        ; MMU6 is deliberately NOT touched: bank 0's first half is where the ring
        ; and the tables already are, loaded by the .nex.
        ; the rasteriser's band base has to agree with pg_ptr1 before the first draw
        ld      a, (pg_ptr1)
        call    page_to_p0
        ld      (dst_p0), a
        call    build_voltab
        call    silence_ring
        ; ramp_sample went with I1's scaffolding. It filled SAMPLE with a ramp for the four
        ; voices init_voices used to start ACTIVE; the game starts silent now, so nothing ever
        ; read it. The buffer stays where it is - init_voices still parks V_POS and V_END in it,
        ; which costs nothing for a voice that is off and voice_setup overwrites both - but
        ; filling it was dead work in the boot path, and the resident block wanted the bytes.
        ; TURN THE LAYER 2 DISPLAY ON. Everything this program draws goes into Layer 2, and
        ; until 2026-09-14 nothing ever made Layer 2 VISIBLE - so the machine showed the ULA,
        ; which holds whatever was in bank 5 at boot: an attribute lattice, flashing.
        ;
        ; Every harness did it. ctest.asm, span.asm and polytest.asm all set NR_L2_CFG and
        ; polytest writes $123B as well, because those programs were written TO BE LOOKED AT.
        ; The game was only ever read from: every gate reads Layer 2's memory over ZRCP and the
        ; emulator runs headless, so sixteen gates proved the pixels correct - check-draw has
        ; them byte-exact against the engine - without one of them ever asking whether they
        ; reach a screen. It took playing it to find.
        call    init_voices
        call    install_im2
    IFNDEF NO_SOUND
        call    start_dma
    ELSE
        ; NO_SOUND: a DIAGNOSTIC BUILD, to find out whether a fault is in the sound path.
        ;
        ; Every number in this project was taken against ZEsarUX carrying three local patches -
        ; prescalar, readback, autorestart - that exist nowhere else. Without them the prescalar
        ; reads as a boolean, a read of the DMA port returns zero and a block stops at its end
        ; whatever WR5 says. So in ANY other emulator the DAC rate is wrong and the mixer, which
        ; asks the DMA where it is and mixes ahead of it, is reasoning from a number that is not
        ; the truth.
        ;
        ; This leaves the frame interrupt running - the VM is paced by it - and starts no DMA,
        ; mixes nothing. If the game then behaves, the fault is confined to the sound path and
        ; is the H1 risk arriving early. If it behaves the same, the sound path is innocent and
        ; the search moves elsewhere. Either answer is worth one build.
        ld      a, 1
        ld      (snd_off), a
    ENDIF
        ei

        ld      a, $5A
        ld      (ready), a

        ; AND ENTER STARTS IT TOO, because nothing pokes `go` on a real Next.
        ;
        ; `go` exists so a checker can set fname, the control block and the probe bytes AFTER
        ; the image has loaded and before the game reads any of them - smartload starts the
        ; program itself, so there is no earlier moment to do it in. On hardware there is no
        ; checker, and a .nex that waits for a byte nobody will ever write is a .nex that never
        ; starts.
        ;
        ; ENTER, AND NOT FIRE, and that distinction cost a gate. The first version of this
        ; released on in_button, which is Space or the Kempston fire button - and check-input
        ; runs all thirty-two of its key combinations BEFORE it pokes `go`, reading what the
        ; interrupt publishes while the boot path waits. Pressing fire started the game
        ; underneath it and five combinations came back as zeros. ENTER is on a row the game
        ; never reads and no gate ever presses, and testing it here directly also leaves
        ; in_mask and in_button alone, which is the other half of why that broke.
.wait:  ld      a, (go)
        or      a
        jr      nz, .begin
        ld      a, ROW_ENTER
        in      a, ($FE)
        bit     0, a                    ; 0 = pressed, as the whole matrix is
        jr      nz, .wait
.begin:

        ; I8. WHERE THE GAME STARTS, and how one binary serves both it and every gate.
        ;
        ; fname is zero-filled in the image and every checker POKES it before setting go - so an
        ; empty first byte means nothing asked for a particular segment, which is the game
        ; starting normally. It starts by setting up a PART: engine.cpp:75 is
        ; `vm.initForPart(part)` with `part = GAME_PART1`, and there is no special-case code for
        ; the protection screen to port, because the wheel is drawn by the same opcodes as
        ; everything else. The bypass is a different starting part number and nothing more.
        ;
        ; A poked name keeps the fixed load every gate so far is built on, unchanged.
        ld      a, (fname)
        or      a
        jr      nz, .fixed
        ; WHICH PART, and start_part generalises what BYPASS_PROTECTION does at build time to
        ; something a checker can choose at run time: the index PLUS ONE, so zero means "the
        ; build's own choice" and the byte can be left alone. I10 needs it - "playable to the
        ; end" is a claim about every part, and until now the only way to reach one was to set
        ; it up with probe_part, which stops before the VM ever runs.
        ld      a, (start_part)
        or      a
        jr      nz, .chosen
        ld      a, START_PART + 1
.chosen:
        dec     a
        call    aw_setup_part
        jp      .ready                  ; NOT .loaded: that sets the pc guard from the loader's
                                        ; last read, and aw_setup_part has already set it right
.fixed:
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
        ; THE PC GUARD IS THE FIXED PATH'S ALONE. It takes the length from what the loader last
        ; read, and for a PART that is the wrong resource entirely - the cinematic, because that
        ; is loaded after the bytecode. aw_setup_part sets the guard from the resource table
        ; instead, and the part path joins below this. It cost a gate: the boot case came back
        ; with a guard of 5,124, which is resource $16, part 0's polygons.
        ld      hl, (got)
        ld      (CTL + $10), hl
.ready:
        ei
        ld      a, (err)
        or      a
        jp      nz, show_err            ; a RED BORDER, then .stop - see show_err. Same three
                                        ; bytes as the `jp nz, .stop` this replaces.

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
        jp      .stop
.not_note:
        ld      a, (probe_mus)
        or      a
        jp      z, .not_mus             ; jp: probe_mix pushed the next test out of reach
        ld      l, a
        ld      h, 0
        call    aw_load_res
        call    aw_play_music
        call    probe_walk              ; lives in MMU6 now: see PART_CODE
        jp      .stop
.not_mus:
        ; probe_snd: SND_BLOCK already holds op_playSound's four operands. Load the resource
        ; the way the bytecode would have, then hand it over - so the gate tests aw_play_sound
        ; and voice_setup, not the loader.
        ld      a, (probe_snd)
        or      a
        jr      z, .not_snd
        ; THE INTERRUPT'S MIXER OFF FIRST, before the voice can go live: with probe_mix set,
        ; the ring has to be a function of the voice and the block count alone, not of how many
        ; interrupts landed before the checker looked.
        ld      a, 1
        ld      (snd_off), a
        ld      a, (SND_BLOCK + 0)
        ld      l, a
        ld      h, 0
        call    aw_load_res
        call    aw_play_sound
        ld      a, (probe_mix)
        or      a
        jp      z, .stop
        ; AND START FROM A KNOWN RING. ring_wr is not at RING_ADDR by now: the interrupt has
        ; been mixing since boot - silently, since every voice was inactive, but mix_block
        ; advances the cursor whether or not a voice contributes. Where the cursor had reached
        ; depends on how long the load took, which is not something a byte-exact comparison can
        ; carry. silence_ring puts back both the 128s and the cursor.
        call    silence_ring
        ld      a, (probe_mix)
        ld      b, a
.mixb:
        push    bc
        ld      a, BLK_A                ; one block length throughout, so the model is the
        call    mix_block               ; mixer's arithmetic and not the pacing's
        pop     bc
        djnz    .mixb
        jp      .stop
.not_snd:
        ; probe_part: hand aw_setup_part a part index and stop, so the transition can be checked
        ; without the VM asking for it. index + 1, because zero means "no probe".
        ld      a, (probe_part)
        or      a
        jr      z, .not_part
        dec     a
        call    aw_setup_part
        jp      .stop
.not_part:
        ; probe_bmp: hand a bitmap resource to the loader, which presents it and forgets it, and
        ; stop - so page 0 can be compared without the VM asking for it.
        ld      a, (probe_bmp)
        or      a
        jr      z, .not_bmp2
        ld      l, a
        ld      h, 0
        call    aw_load_res
        jp      .stop
.not_bmp2:
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
boot_stop:                              ; a global alias so MMU6 code can jump here; 0 bytes
        ld      a, $5A
        ld      (done), a
.hold:  di
        jr      .hold

;-----------------------------------------------------------------------------
; mix_block - A = how many samples, into the ring at (ring_wr), which wraps.
;
; THE BLOCK IS SPLIT, which is what I5 owed. The old version had a crude guard - rewind if the
; next block would not fit - and its own comment said proper end-of-sample and loop-point
; handling was still to come. It was worse than crude: a FULL window has V_END = $0000, so
; `V_POS + blocklen` never borrowed against it, the guard read "would overrun", and V_POS went
; to V_LOOP - zero for an unlooped sample. The voice then read from address $0000. Measured
; after 40 blocks of RES54: V_POS = $0096, V_LEFT still 14,506, V_PAGE unmoved.
;
; Three things can cut a piece short and all three have to:
;   the sample's end, or the window's edge     voice_run, which voice_advance then steps
;   a 256-byte boundary in the RING            because mix_voice_* does `inc l`, which does
;                                              not carry - and BLK_A of 221 into 2,048 crosses
;
; AND EVERY VOICE ACCUMULATES; none stores. The block is filled with 128 first, which is what
; the DAC reads as silence, and `mva` accumulating onto 128 is byte-identical to `mvf`s biased
; store over the whole signed range: for s >= 0 it is 128 + s and cannot carry, and for s < 0
; the carry produces exactly what the XOR would. That buys two things for one pass of stores,
; 0.55% of the machine: a voice that stops part way through a block leaves silence behind it
; rather than stale ring, and there is no "which voice stores" state left to get wrong.
;-----------------------------------------------------------------------------
mix_block:
        ld      (blk_total), a
        ld      hl, (ring_wr)
        ld      (blk_dst), hl

        ; silence first: every voice accumulates onto it. The ring's end is page-aligned, so
        ; the wrap test is one high-byte compare.
        ld      b, a
.fill:  ld      (hl), 128
        inc     hl
        ld      a, h
        cp      RING_END >> 8
        jr      nz, .fill_on
        ld      hl, RING_ADDR
.fill_on:
        djnz    .fill

        ld      ix, VOICES
        ld      b, 4
.each:
        ld      a, (ix + V_ACTIVE)
        or      a
        jr      z, .next
        ld      a, (blk_total)
        ld      (mix_left), a
        ld      hl, (blk_dst)
        ld      (mix_pc), hl
.piece:
        ; the piece is the lesser of what is left of the block and what fits before the RING's
        ; end. The 256-byte boundary is no longer a cut: mix_voice_* advances its destination
        ; with `inc hl` now, which carries.
        ; only the ring's LAST page can hold less than 256 bytes of room, the end being
        ; page-aligned, so the room is 256 - L there and more than a cap's worth anywhere else.
        ld      hl, (mix_pc)
        ld      a, h
        cp      (RING_END >> 8) - 1
        jr      nz, .room_full
        ld      a, l
        neg
        jr      nz, .have_room
.room_full:
        ld      a, 255
.have_room:
        ld      hl, mix_left
        cp      (hl)
        jr      c, .capped
        ld      a, (hl)
.capped:
        ld      (blocklen), a           ; voice_run caps against this, voice_regs counts by it
        push    bc                      ; B IS THE VOICE COUNTER and voice_run's divide uses B
        call    voice_run               ; as its own sixteen-step counter
        pop     bc
        jr      nz, .have
        ; nothing available in this window: step the page, take the loop, or go quiet
        push    bc
        call    voice_advance
        pop     bc
        ld      a, (ix + V_ACTIVE)
        or      a
        jr      nz, .piece
        jr      .next                   ; stopped, and the 128s already there are the rest
.have:
        ld      (blocklen), a           ; what voice_run settled on, which may be less
        ld      e, a
        ld      hl, (mix_pc)
        ld      (mix_dst), hl
        push    bc
        push    de
        call    mix_voice_add
        pop     de
        pop     bc
        ld      d, 0
        ld      hl, (mix_pc)
        add     hl, de                  ; a piece can land ON the end but never past it
        ld      a, h
        cp      RING_END >> 8
        jr      nz, .pc_in
        ld      hl, RING_ADDR
.pc_in:
        ld      (mix_pc), hl
        ld      a, (mix_left)
        sub     e
        ld      (mix_left), a
        jr      nz, .piece
.next:
        ld      de, V_SIZE
        add     ix, de
        dec     b
        jp      nz, .each

        ; THE WRITE POINTER WRAPS MODULO, not by jumping back to the start. It used to test
        ; `ring_wr + blocklen` against the end AFTER the block had been written and reset to
        ; RING_ADDR if it passed - so the block that took it over the edge wrote up to 158
        ; bytes PAST the ring, over VOLTAB, and the bytes near the end were never written at
        ; all. Nine blocks of 221 reach 1,985 of 2,048, and the tenth did both.
        ld      hl, (ring_wr)
        ld      a, (blk_total)
        ld      e, a
        ld      d, 0
        add     hl, de
        ld      de, RING_END
        or      a
        sbc     hl, de
        jr      c, .store
        ld      de, RING_ADDR           ; HL is how far past the end it went
        add     hl, de
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

        ; is there room? running out is a fault, not a wrap onto something else. A BITMAP is
        ; exempt: it goes to its own scratch and the heap never sees it.
        ld      a, (res_type)
        cp      2
        jr      z, .room
        ld      a, (res_pages)
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

        ld      a, (res_type)           ; the heap, unless this is a bitmap
        cp      2
        ld      a, BMP_PAGE
        jr      z, .dest
        ld      a, (next_page)
.dest:
        ld      (ld_page), a
        di                              ; esxDOS wants the interrupt off: see load_code
        call    load_code
        ei
        ld      a, CODE_PAGE
        ld      (ld_page), a

        ld      a, (err)
        or      a
        jr      z, .read
        ld      (res_err), a
        ret
.read:
        ; A BITMAP IS PRESENTED AND FORGOTTEN. It never enters res_page and the cursor does not
        ; move, so the next one reuses the same scratch - which is what MEMENTRY_STATE_NOT_NEEDED
        ; amounts to (resource.cpp:214).
        ld      a, (res_type)
        cp      2
        jr      nz, .loaded
        ld      hl, (n_bmp)
        inc     hl
        ld      (n_bmp), hl
        jp      present_bitmap
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
        ; the loud table, then the quiet one - the same scale_byte check-mix verified, at two
        ; different volumes
        ld      a, VOLUME
        ld      (vol_now), a
        ld      hl, VOLTAB
        call    build_one
        ld      a, VOLUME_QUIET
        ld      (vol_now), a
        ld      hl, VOLTAB_QUIET
        call    build_one
        ret

build_one:
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
init_voices:
        ld      ix, VOICES
        ld      b, 4
        ld      c, 0
.one:
        ld      (ix + V_ACTIVE), 0      ; SILENT until a note says otherwise
        ld      (ix + V_FRAC), 0
        ; PARKED, not meaningful: an inactive voice's position is never read, and voice_setup
        ; writes all of these before one plays. The window's base is the honest place to park.
        ld      (ix + V_POS), SAMP_WIN & $FF
        ld      (ix + V_POS + 1), SAMP_WIN >> 8
        ld      (ix + V_INCF), 0
        ld      (ix + V_INCI), 1        ; one sample in, one out
        ld      (ix + V_INCI + 1), 0
        ld      a, VOLTAB >> 8
        ld      (ix + V_VOL), a
        ld      (ix + V_END), SAMP_WIN & $FF
        ld      (ix + V_END + 1), SAMP_WIN >> 8
        ld      (ix + V_LOOP), 0
        ld      (ix + V_LOOP + 1), 0
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
        ; AND THE SYNTHETIC PLAYER, when one is asked for. auto_input returns at once unless
        ; autoplay is set, so this costs three resident bytes - which is what is left. The
        ; routine itself lives in MMU6 beside the part table. See auto_input for why the
        ; machine needs the probe's own input function and not merely some input.
        call    auto_input
        call    do_input
        call    publish_input

        ; snd_off exists to answer one question: does the mixing inside this interrupt
        ; disturb a draw in progress? The rasteriser and the mixer both patch immediate
        ; operands in their own code, and both use the shadow registers, so the question
        ; is a fair one and no gate has ever asked it.
        ld      a, (snd_off)
        or      a
        jr      nz, .no_mix
        ; BORROW MMU7 AROUND BOTH BLOCKS. It is the Layer 2 draw band, and this interrupt can
        ; land in the middle of a draw that owns it - the rasteriser does not stop for the
        ; mixer. Saved by READING the NextReg rather than by tracking it, because the frame
        ; boundary borrows the same slot for a sample header and the two must nest: whoever
        ; borrows puts back exactly what they found.
        ld      bc, $243B
        ld      a, NR_SAMP_MMU
        out     (c), a
        ld      b, $25
        in      a, (c)
        push    af
        ld      a, BLK_A
        call    mix_block
        ld      a, BLK_B
        call    mix_block
        pop     af
        nextreg NR_SAMP_MMU, a
        ld      hl, (n_mix)
        inc     hl
        ld      (n_mix), hl
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
        call    dt_forget               ; see dirty_band
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
        ld      (cp_sidx), a
        call    page_to_p0
        ld      (cp_src), a
        ld      a, (cp_dstid)
        call    resolve_page
        ld      (cp_didx), a
        call    page_to_p0
        ld      (cp_dst), a
        call    dt_copy_mask            ; which bands actually differ; see dirty_band
        ld      d, BANDS
        ld      e, 0
.cband:
        srl     b                       ; dt_copy_mask left the band mask in B
        jr      nc, .cskip
        ld      a, (cp_src)
        add     a, e
        nextreg NR_CPWIN_MMU, a
        ld      a, (cp_dst)
        add     a, e
        nextreg NR_DWIN_MMU, a
        push    bc                      ; the mask: LDIR takes BC
        push    de
        ld      hl, CPWIN
        ld      de, DWIN
        ld      bc, $2000
        ldir
        pop     de
        pop     bc
.cskip:
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
        ; CTL_FAULT, NOT CTL_OUT_OF_BUDGET, and the difference is one blit's worth of drawing.
        ;
        ; aw_host_frame tests CTL_OUT_OF_BUDGET BETWEEN THREADS, so setting it leaves the thread
        ; that is running to carry on to its own pauseThread - and everything it draws after the
        ; blit lands on the page. The reference stops exactly AT the blit, so the two were being
        ; compared a variable amount of work apart. The intro never showed it because its blit is
        ; the last thing that thread does; part 2 selects another page straight afterwards and
        ; draws into it, which presented as page 2 differing in 100% of its bytes while the other
        ; three agreed - the extra polygons, on a page the engine had not touched since.
        ;
        ; execute_thread tests CTL_FAULT after EVERY opcode, so a fault set here ends the thread
        ; on the blit itself. Same two instructions; one byte of address.
        ld      a, 1
        ld      (CTL + $0D), a          ; CTL_FAULT: execute_thread breaks on the next check
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
        call    pace_blit               ; the script's pause, before the frame appears
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
    IFDEF DIAG_BORDER
        ; THE DIAGNOSTIC PALETTE HAS TO SURVIVE. The first version of this test wrote sixteen
        ; known colours at boot and then let the game upload its own on the first blit, which
        ; overwrote them - so a black screen proved nothing at all. One byte fixes it.
        ret
    ENDIF
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
        ; AND FORGET WHICH BAND IS MAPPED. The rasteriser writes NR_SWIN_MMU only when the
        ; band number changes, so its cache is a claim about what MMU0 holds - and .restore
        ; below makes that claim false by putting the bytecode page back. The next draw that
        ; starts in the band the last one ended in then skips the write and copies from
        ; BYTECODE instead of page 0: the multicoloured speckle under the lift at intro
        ; blit 218, 807 bytes in rows 165-191 while page 0 itself was identical.
        ld      a, 255
        ld      (cur_band), a

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
        ; VIDEO2 IS A SECOND SEGMENT, and five of the ten parts have one: setDataBuffer is
        ; handed either the part's cinematic data or its video2 data, which is what the two
        ; polygon opcodes choose between. A part with no video2 (vid2_base zero) still counts
        ; and skips, because there is nothing to read.
        ld      a, (vid2_base)
        or      a
        jr      nz, .have_seg
        ld      hl, (n_video2)
        inc     hl
        ld      (n_video2), hl
        jr      .restore
.cinematic:
        ld      a, (cin_base)
.have_seg:
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
        ; resNum ZERO IS NOT "CARRY ON". snd_playMusic (vm.cpp:726-733) retimes the running module
        ; when the delay is non-zero and stops it when the delay is zero, and the intro does both:
        ; 15,700 -> 15,900 at 45 s, and a stop at 117 s. This used to return, so the music kept
        ; its first tempo and never stopped.
        jp      mus_zero
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
        ; THE EVENT TIMER STARTS HERE, in milliseconds; see music_clock. It used to be a count of
        ; VM frames, which the intro's 80 ms frames turned into a quarter-speed tune.
        call    mus_clock_start

        ld      a, 1
        ld      (mus_playing), a
        ld      hl, (n_mus)
        inc     hl
        ld      (n_mus), hl
        ret

resident_end:                           ; where the ordinary resident block reached
        ORG     MUSIC_CODE

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
        ; I9. A SAVE HAPPENS AT THE FRAME BOUNDARY, which is where the reference does it - the
        ; engine tests sys->input.save between frames (engine.cpp:98-104), never mid-opcode, and
        ; for the same reason: half the state is the VM's and it is only consistent here.
        ; save_req is a byte so that a key, a checker or a menu can all set it the same way.
        ld      a, (save_req)
        or      a
        jr      z, .no_save
        call    aw_saveload             ; 1 saves, 2 loads; it reads the byte and clears it
.no_save:
    IFNDEF NO_MUSIC
        call    music_clock
    ELSE
        ; NO_MUSIC: does the module player return?
        ;
        ; music_tick runs HERE - inside aw_frame_sync, before the `ei` below - so it runs with
        ; interrupts OFF. If it ever fails to return, the interrupt never comes back on, `ticks`
        ; stops, the spin below can never end, and the zxnDMA keeps streaming because it is
        ; autonomous. The machine is then dead with a steady tone and a frozen picture, and no
        ; fault is ever recorded, because nothing is left running to record one.
    ENDIF
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
        ; NO WAIT HERE ANY MORE. This used to spin until the next tick, which made one refresh a
        ; frame the whole of the pacing and ignored the pause the script asks for. The reference
        ; waits in exactly one place - op_blitFramebuffer, vm.cpp:285-297, before the frame is
        ; shown - and runs a frame with no blit straight on into the next. pace_blit does that
        ; now. The spin was also dead time: a frame that finished late still idled to a tick edge.
        ret


;-----------------------------------------------------------------------------
; voice_locate - A = a resource id and (mp_chan) = the channel. On exit mv_page holds the
; resource's first page and IX points at that channel's voice. Carry set means the resource is
; not resident, and nothing was written.
;
; Both callers want exactly this and each had its own copy: thirty-six bytes of table lookup
; and multiply, twice, in the block with the least room left in the program.
;-----------------------------------------------------------------------------
voice_locate:
        ld      h, 0
        ld      l, a
        ld      de, res_page
        add     hl, de
        ld      a, (hl)
        or      a
        scf
        ret     z                       ; not resident: carry set, mv_page untouched
        ld      (mv_page), a
        ld      hl, VOICES
        ld      a, (mp_chan)
        or      a
        jr      z, .got
        ld      de, V_SIZE
.mul:
        add     hl, de
        dec     a
        jr      nz, .mul
.got:
        push    hl
        pop     ix
        or      a                       ; carry clear: IX is the voice
        ret

;-----------------------------------------------------------------------------
; I7. present_bitmap - copyPage(const uint8_t *src), video.cpp:550.
;
; The reference DEPLANES here: four planes 8,000 bytes apart, eight bits at a time, into 320x200
; at four bits a pixel. mkassets.py has already done that at build time and written the result as
; OUR page - 256x192 at 8bpp, 49,152 bytes - which check-bitmap proves pixel for pixel against
; the engine's own deplaner on real resources. So the machine's half is a copy, and the deplaning
; never has to happen at 28 MHz.
;
; Into PAGE 0 always: video.cpp:554 takes _pages[0] and not a page id. Six 8K bands, through MMU2
; and MMU3 - the polygon segment window, which every draw re-maps from seg_base before it reads,
; so clobbering it between opcodes costs nothing.
;
; 49,152 bytes of LDIR is about 1.8 frames at 28 MHz. The reference's deplane of 32,000 bytes is
; not cheap either, and this is the path nothing has ever measured: part 7 loads seventy of these
; and parts 2 and 3 load none, so no budget so far has paid for it.
;-----------------------------------------------------------------------------
present_bitmap:
        xor     a
        call    dt_forget               ; page 0 is replaced; see dirty_band
        ld      a, BMP_PAGE
        ld      (bmp_src), a
        ld      a, L2_BASE_BANK * 2     ; page 0's first 8K band
        ld      (bmp_dst), a
        ld      b, 6
.band:
        push    bc
        ld      a, (bmp_src)
        nextreg NR_SEG_MMU_LO, a
        ld      a, (bmp_dst)
        nextreg NR_SEG_MMU_HI, a
        ld      hl, SEG_WIN
        ld      de, SEG_WIN + $2000
        ld      bc, $2000
        ldir
        ld      hl, bmp_src
        inc     (hl)
        ld      hl, bmp_dst
        inc     (hl)
        pop     bc
        djnz    .band
        ret
;-----------------------------------------------------------------------------
; music_tick - ONE event, now; music_clock decides when. handleEvents,
; sfxplayer.cpp: the order table selects a 1024-byte pattern block, four channels of four
; bytes are read at curPos, curPos advances sixteen, and at 1024 it wraps to the next order.
; Reaching numOrder stops the module - the reference removes its timer and stops every
; channel.
;
; THIS RUNS AT THE FRAME BOUNDARY, not in the interrupt, because it has to page the module's
; pattern block into MMU2 - and MMU2 is the polygon window, which a draw may own mid-record.
; The mixer stays in the interrupt, where it belongs; only the event walk is out here.
;-----------------------------------------------------------------------------
music_tick:
        ld      a, (mus_playing)
        or      a
        ret     z

        ld      hl, (n_mus_ev)
        inc     hl
        ld      (n_mus_ev), hl

        ; the pattern block: 0xC0 + order * 1024 + curPos, into the module's own pages
        ld      a, (mus_cur_order)
        ld      e, a
        ld      d, 0
        ld      hl, MUS_ORDER_AT
        add     hl, de
        ld      a, (hl)                 ; the order table's entry selects the block
        ; entry * 1024 is (entry * 4) << 8, so it is a byte shift and a zero low byte. The
        ; first version shifted HL twice and then tried to shift the HIGH byte three more
        ; times, which for entry 1 produced 4 instead of 1024 - and every block after the
        ; first came out at the wrong offset. It passed 64 events and failed at 66, because
        ; order 0 selects block 0 and nothing is wrong with zero.
        add     a, a
        add     a, a                    ; entry * 4
        ld      h, a
        ld      l, 0                    ; HL = entry * 1024
        ld      de, (mus_cur_pos)
        add     hl, de
        ld      de, $C0
        add     hl, de                  ; HL = the byte offset within the module

        ; map the two pages covering it, the same shape as the bytecode window
        ld      a, h
        rlca
        rlca
        rlca
        and     7
        ld      e, a
        ld      a, (mus_page)
        add     a, e
        nextreg NR_MUS_MMU, a
        inc     a
        nextreg NR_MUS_MMU + 1, a
        ld      a, h
        and     $1F
        add     a, MUS_WIN >> 8
        ld      h, a                    ; HL = the four channels, in the window

        ld      b, 4
        ld      c, 0                    ; C = the channel number
.chan:
        push    bc
        push    hl
        call    mus_pattern
        pop     hl
        ld      de, 4
        add     hl, de
        pop     bc
        inc     c
        djnz    .chan

        ; curPos advances by four channels of four bytes
        ld      hl, (mus_cur_pos)
        ld      de, 16
        add     hl, de
        ld      (mus_cur_pos), hl
        ld      de, 1024
        or      a
        sbc     hl, de
        ret     c                       ; still inside this block
        ld      hl, 0
        ld      (mus_cur_pos), hl
        ld      a, (mus_cur_order)
        inc     a
        ld      hl, mus_num_order
        cp      (hl)
        jr      nz, .next_order
        ; the module has finished: the reference clears its resource and stops everything
        xor     a
        ld      (mus_playing), a
        ld      (mus_res), a
        ret
.next_order:
        ld      (mus_cur_order), a
        ret

;-----------------------------------------------------------------------------
; mus_pattern - HL = this channel's four bytes, C = the channel. handlePattern,
; sfxplayer.cpp. Two big-endian words: note_1 then note_2.
;
;   note_1 == 0xFFFD  write note_2 into variable 0xF4 and do nothing else
;   note_1 == 0xFFFE  stop this channel
;   note_1 == 0       leave the channel alone
;   otherwise         play, at 41891 / note_1, using the instrument note_2 names
;
; The instrument is the top nibble of note_2 and effects 5 and 6 in its second nibble move
; the volume up and down, clamped to 0x3F.
;-----------------------------------------------------------------------------
mus_pattern:
        ; THE CHANNEL GOES IN MEMORY FIRST. This routine loads note_2's low byte into C, which
        ; is where the caller put the channel number - so mus_voice indexed the voice array by
        ; a note operand and wrote all four voices to whatever offset that happened to be. It
        ; showed as every channel reporting the same increment.
        ld      a, c
        ld      (mp_chan), a
        ld      d, (hl)                 ; note_1, big-endian
        inc     hl
        ld      e, (hl)
        inc     hl
        ld      b, (hl)                 ; note_2
        inc     hl
        ld      a, (hl)
        ld      c, a                    ; BC = note_2; the channel is in (mp_chan) now
        ld      (mp_note1), de
        ld      (mp_note2), bc

        ld      a, d
        and     e
        inc     a                       ; $FFFF -> 0; catches neither marker on its own
        ld      a, d
        cp      $FF
        jr      nz, .not_special
        ld      a, e
        cp      $FD
        jr      nz, .not_fd
        ld      hl, (mp_note2)          ; the mark: variable 0xF4
        ld      (mus_mark), hl
        ret
.not_fd:
        cp      $FE
        ; AN ODD $FFxx IS NOT IGNORED BY THE REFERENCE - it falls out of the note_1 chain at
        ; sfxplayer.cpp:185 and plays like any other period, and only the assert at :196
        ; (note_1 < 0x1000) says it should not arise. Returning here is a real divergence, and
        ; it is safe only because it cannot be reached: across all three modules the game has -
        ; 0x07, 0x89 and 0x8A, the only resources MEMLIST types RT_MUSIC - all 7,680 rows of
        ; every block their order tables name contain not one $FFxx besides $FFFD and $FFFE.
        ret     nz
        ld      hl, (n_mus_stop)
        inc     hl
        ld      (n_mus_stop), hl
        ret                             ; stopping the channel is the voice work, still to come
.not_special:
        ld      a, d
        or      e
        ret     z                       ; note_1 zero: leave the channel be
        ld      hl, (mp_note1)
        call    note_to_inc
        ld      (mp_inc), hl
        ld      hl, (n_mus_note)
        inc     hl
        ld      (n_mus_note), hl
        jp      mus_voice

;-----------------------------------------------------------------------------
; mus_voice - turn the decoded row into a live voice. C = the channel.
;
; handlePattern's second half: the instrument is the top nibble of note_2, and a zero there
; means "keep whatever this channel already has" rather than "silence". Effects 5 and 6 in the
; next nibble move the volume up and down, clamped to 0x3F.
;
; The sample's shape comes from its own first four bytes, both big-endian words doubled:
; sampleLen at 0 and loopLen at 2, with the data starting at byte 8. The reference plays
; 0..sampleLen and then jumps to loopPos = sampleLen for loopLen - which is the same thing as
; playing 0..sampleLen+loopLen once and looping back to sampleLen, so that is what this sets.
;-----------------------------------------------------------------------------
mus_voice:
        ; A NOTE ONLY PLAYS IF THIS ROW NAMES AN INSTRUMENT. handlePattern's `pat` is a local
        ; struct memset to zero on every call, so pat.sampleBuffer is set only inside the
        ; `if (sample != 0)` block - and the play at the bottom is guarded by
        ; `else if (pat.sampleBuffer != 0)`. So a zero instrument nibble means the row is
        ; IGNORED, not "keep the previous sample", which is what the first version assumed.
        ; The gate caught it: two channels came out at the wrong frequency because the machine
        ; had updated their pitch from a row the reference discards.
        ld      a, (mp_note2 + 1)       ; note_2's high byte
        and     $F0
        ret     z
        rrca
        rrca
        rrca
        rrca                            ; the instrument number, 1..15
        dec     a
        ; TWO bytes an entry, because MUS_INSTR_AT is not the module's layout. The module has
        ; four bytes an entry - a resource word then a volume word, both big-endian
        ; (prepareInstruments, sfxplayer.cpp:83-95) - but aw_play_music COMPACTS it on the way
        ; out, keeping only each word's low byte, so the resident table is thirty bytes and
        ; DRAW_LOG starts thirty-two bytes along. Read the module's stride here and instrument
        ; 8 lands in DRAW_LOG.
        add     a, a                    ; two bytes an entry, as aw_play_music wrote it
        ld      e, a
        ld      d, 0
        ld      hl, MUS_INSTR_AT
        add     hl, de
        ld      a, (hl)                 ; the instrument's resource
        or      a
        ret     z                       ; an unused slot: no sample, so nothing plays
        ld      (mv_res), a
        inc     hl
        ld      a, (hl)
        ld      (mv_vol), a

        ; where did aw_load_res put it, and which voice is this?
        ld      a, (mv_res)
        call    voice_locate
        jr      nc, .have_page
        ld      hl, (n_mus_nores)
        inc     hl
        ld      (n_mus_nores), hl
        ret
.have_page:

        ; THE MODULE'S OWN VOLUME WORK, before the setup that op_playSound shares.
.volume:
        ; effects 5 and 6 move the instrument's volume, clamped to 0x3F
        ld      a, (mp_note2 + 1)
        and     $0F
        ld      b, a                    ; the effect
        ld      a, (mv_vol)
        ld      c, a
        ld      a, b
        cp      5
        jr      nz, .not_up
        ld      a, (mp_note2)           ; note_2's low byte is the amount
        add     a, c
        jr      nc, .clamp
        ld      a, $3F
.clamp:
        cp      $40
        jr      c, .set_vol
        ld      a, $3F
        jr      .set_vol
.not_up:
        cp      6
        jr      nz, .plain_vol
        ld      a, c
        ld      b, a
        ld      a, (mp_note2)
        neg
        add     a, b
        jr      nc, .set_vol
        xor     a                       ; it went below zero
        jr      .set_vol
.plain_vol:
        ld      a, c
.set_vol:
        ld      (mv_vol), a
        ld      a, 1
        ld      (vs_zero8), a           ; a module instrument opens on four zero samples
        jp      voice_setup

;-----------------------------------------------------------------------------
; voice_setup - IX = the voice, and mv_page, mv_vol and mp_inc already decided. Reads the
; sample's own header for its shape and hands the voice to the mixer.
;
; Shared by mus_voice and aw_play_sound because it is all of both of them bar the pitch and
; the volume: handlePattern and snd_playSound differ in where those two numbers come from and
; in nothing else (sfxplayer.cpp:189-201 against vm.cpp:705-716). vs_zero8 is the one other
; difference - prepareInstruments zeroes four bytes at data+8 for a MODULE instrument
; (sfxplayer.cpp:89) and snd_playSound does no such thing to a plain sound.
;-----------------------------------------------------------------------------
voice_setup:
        ; BORROW MMU7 to read the sample's header. MMU7 is the Layer 2 draw band, and this runs
        ; at the frame boundary where no draw is in progress - but the interrupt mixes through
        ; the same slot, so it is saved and restored rather than assumed.
        ld      bc, $243B
        ld      a, NR_SAMP_MMU
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      (mv_saved), a
        ld      a, (mv_page)
        nextreg NR_SAMP_MMU, a
        ld      a, (SAMP_WIN + 0)       ; sampleLen, big-endian, doubled
        ld      h, a
        ld      a, (SAMP_WIN + 1)
        ld      l, a
        add     hl, hl
        ld      (mv_len), hl
        ld      a, (SAMP_WIN + 2)       ; loopLen, likewise
        ld      h, a
        ld      a, (SAMP_WIN + 3)
        ld      l, a
        add     hl, hl
        ld      (mv_loop), hl
        ; FOUR ZERO BYTES AT THE START OF THE DATA. prepareInstruments does
        ; `memset(ins->data + 8, 0, 4)` - sfxplayer.cpp:89 - to every instrument it loads, so
        ; every module note opens on four samples of silence. The reference does it once when
        ; the module loads; this does it when the note is set up, which is the same thing to
        ; the mixer because nothing reads a sample the player has not set up. It is idempotent,
        ; so repeating it per note costs four writes and changes nothing.
        ld      a, (vs_zero8)
        or      a
        jr      z, .no_zero8
        xor     a
        ld      (SAMP_WIN + 8), a
        ld      (SAMP_WIN + 9), a
        ld      (SAMP_WIN + 10), a
        ld      (SAMP_WIN + 11), a
.no_zero8:
        ld      a, (mv_saved)
        nextreg NR_SAMP_MMU, a

        ; total = 8 + sampleLen + loopLen
        ld      hl, (mv_len)
        ld      de, (mv_loop)
        add     hl, de
        ld      de, 8
        add     hl, de
        ld      (mv_total), hl

        ld      a, (mv_page)
        ld      (ix + V_PAGE), a
        ld      (ix + V_PAGE0), a       ; where a loop has to come back to
        ld      hl, (mv_total)
        ld      (ix + V_TOTAL), l
        ld      (ix + V_TOTAL + 1), h
        ld      (ix + V_POS), (SAMP_WIN + 8) & $FF
        ld      (ix + V_POS + 1), (SAMP_WIN + 8) >> 8
        ld      (ix + V_FRAC), 0

        ; does it all fit in one window?
        ld      hl, (mv_total)
        ld      de, $2000
        or      a
        sbc     hl, de
        jr      nc, .spans
        add     hl, de
        ld      de, SAMP_WIN
        add     hl, de
        ld      (ix + V_END), l
        ld      (ix + V_END + 1), h
        ld      (ix + V_LEFT), 0
        ld      (ix + V_LEFT + 1), 0
        jr      .loop_point
.spans:
        ld      (ix + V_LEFT), l        ; what is left after this window
        ld      (ix + V_LEFT + 1), h
        ; $0000, DELIBERATELY: the window's end is $10000 and no word holds it. voice_run
        ; knows this encoding - see the borrow it allows. Written as zero rather than let the
        ; assembler truncate $100, so a real truncation warning is never buried under this one.
        ld      (ix + V_END), 0
        ld      (ix + V_END + 1), 0
.loop_point:
        ; the loop begins at 8 + sampleLen, and only if it is reachable in this window - a loop
        ; point on a later page is not modelled and the voice simply stops instead. Recorded
        ; rather than faked: n_mus_farloop counts it.
        ld      hl, (mv_loop)
        ld      a, h
        or      l
        jr      z, .no_loop
        ld      hl, (mv_len)
        ld      de, 8
        add     hl, de
        ld      de, $2000
        or      a
        sbc     hl, de
        jr      nc, .far_loop
        add     hl, de
        ld      de, SAMP_WIN
        add     hl, de
        ld      (ix + V_LOOP), l
        ld      (ix + V_LOOP + 1), h
        jr      .vol_page
.far_loop:
        ld      hl, (n_mus_farloop)
        inc     hl
        ld      (n_mus_farloop), hl
.no_loop:
        ld      (ix + V_LOOP), 0
        ld      (ix + V_LOOP + 1), 0
.vol_page:
        ; which of the two volume tables. The caller has already settled the number: the module
        ; path through its effects, op_playSound with MIN(vol, 0x3F) - vm.cpp:715.
        ld      a, (mv_vol)
        cp      VOL_SPLIT + 1
        jr      c, .quiet
        ld      a, VOLTAB >> 8
        jr      .store_vol
.quiet:
        ld      a, VOLTAB_QUIET >> 8
.store_vol:
        ld      (ix + V_VOL), a

        ; the increment, and the voice goes live
        ; The 8.8 increment: H is the integer part and L the fraction. V_INCI is a WORD, so its
        ; high byte is cleared - an increment above 255 bytes a sample cannot happen, because
        ; the shortest period 0x37 gives 761.
        ld      hl, (mp_inc)
        ld      a, l
        ld      (ix + V_INCF), a
        ld      a, h
        ld      (ix + V_INCI), a
        ld      (ix + V_INCI + 1), 0
        ld      (ix + V_ACTIVE), 1
        ld      hl, (n_voice_set)
        inc     hl
        ld      (n_voice_set), hl
        ret


;-----------------------------------------------------------------------------
; aw_play_sound - op_playSound, vm.cpp:357, into snd_playSound, vm.cpp:692.
;
; SND_BLOCK holds the four operands the C fetched: resource, frequency index, volume, channel.
;
;   not loaded   return, and the reference does the same (vm.cpp:698)
;   volume 0     stop the channel and nothing else (vm.cpp:702-704)
;   otherwise    play at frequenceTable[freq], at MIN(volume, 0x3F)
;
; THE CHANNEL IS MASKED WITH 3 ON BOTH PATHS. The reference masks it for the play
; (vm.cpp:715-716) and does NOT for the stop, where `mixer->stopChannel(channel)` only asserts
; `channel < AUDIO_NUM_CHANNELS`. Masking is the safe reading of the same intent, and it costs
; a byte: across the 970 op_playSound calls the host probe logged, every channel is already
; 0..3 and every frequency index 0..26 against the reference's own assert of 40.
;
; No divide: snd_freq is the forty pitches already reduced to 8.8 increments at load time.
;-----------------------------------------------------------------------------
aw_play_sound:
        ld      a, (SND_BLOCK + 3)      ; the channel, masked
        and     3
        ld      (mp_chan), a
        ld      a, (SND_BLOCK + 0)      ; the resource
        call    voice_locate
        jr      nc, .resident
        ld      hl, (n_snd_miss)
        inc     hl
        ld      (n_snd_miss), hl
        ret                             ; not loaded, and the reference returns here too
                                        ; (vm.cpp:698) - BEFORE the volume-zero test, so a
                                        ; missing resource does not stop the channel either
.resident:
        ; volume zero stops the channel, and that is all it does
        ld      a, (SND_BLOCK + 2)
        or      a
        jr      nz, .play
        ld      (ix + V_ACTIVE), 0
        ld      hl, (n_snd_stop)
        inc     hl
        ld      (n_snd_stop), hl
        ret
.play:
        cp      $40                     ; MIN(vol, 0x3F), vm.cpp:715
        jr      c, .vol_ok
        ld      a, $3F
.vol_ok:
        ld      (mv_vol), a

        ; the pitch, straight out of the table
        ld      a, (SND_BLOCK + 1)
        add     a, a                    ; two bytes an entry
        ld      e, a
        ld      d, 0
        ld      hl, SND_FREQ
        add     hl, de
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ld      (mp_inc), de

        xor     a
        ld      (vs_zero8), a           ; a plain sound is NOT zeroed at data+8 - only a
                                        ; module instrument is, in prepareInstruments
        ld      hl, (n_snd)
        inc     hl
        ld      (n_snd), hl
        jp      voice_setup

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
        call    dirty_band              ; text draws into this band too
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

        DISPLAY "> the upper block ends at ", /H, $
        ASSERT $ < $BF00
        ORG     resident_end

        INCLUDE "src/inc/vmhost.inc"
        INCLUDE "src/inc/input.inc"
        INCLUDE "src/inc/raster.inc"

; The ring is resident in MMU6's page, so nothing needs mapping for it - but from I5 each
; voice plays out of its OWN sample page, which does. This runs once per voice, with IX on
; that voice's record, and only maps: the putting back is the interrupt's, once, around both
; blocks, because doing it here would cost four restores a frame to no purpose.
        MACRO SND_MAP_PAGES
        ld      a, (ix + V_PAGE)
        nextreg NR_SAMP_MMU, a
        ENDM

        DEFINE SND_NO_FIRST             ; every voice accumulates; see mix_block
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
    IFDEF AUTOSTART
go:         db 1                        ; an unattended run has nobody at the keyboard to press ENTER
    ELSE
go:         db 0
    ENDIF
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

vol_now:    db VOLUME       ; which volume scale_byte is building for
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
        EXPORT probe_ticks
probe_ticks: db 0           ; how many events to walk in the probe
pw_left:     db 0           ; probe_walk's saved count, across the instrument loop
        EXPORT probe_note
probe_note: db 0            ; 1 = convert one period and stop
        EXPORT probe_mus
probe_mus:  db 0            ; a resource id: load it and parse it, no VM
        EXPORT probe_snd
probe_snd:  db 0            ; 1 = load SND_BLOCK's resource and run aw_play_sound
        EXPORT probe_mix
probe_mix:  db 0            ; blocks to mix after it, with the interrupt's mixer off
        EXPORT probe_part
probe_part: db 0            ; a part index + 1: set that part up and stop
        EXPORT start_part
start_part: db 0            ; a part index + 1 to boot into and RUN; 0 = the build's own
        EXPORT probe_bmp
probe_bmp:  db 0            ; a bitmap resource id: load and present it, then stop
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
n_video2:   dw 0        ; draws that wanted a video2 segment the part does not have
        EXPORT cin_base
cin_base:   db POLY_PAGE    ; the part's cinematic polygons; the gates' fixed page until I6 sets it
        EXPORT vid2_base
vid2_base:  db 0            ; and its second polygon set, 0 when the part names none
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
        EXPORT mus_acc
mus_acc:        dw 0            ; milliseconds owed to the event timer; see music_clock
        EXPORT n_mus_ev
n_mus_ev:       dw 0            ; events handled
        EXPORT n_mus_note
n_mus_note:     dw 0            ; notes decoded
        EXPORT n_mus_stop
n_mus_stop:     dw 0            ; channel stops seen
        EXPORT mus_mark
mus_mark:       dw 0            ; what a 0xFFFD row wrote, for variable 0xF4
part_ptr:       dw 0            ; the part's four-byte row in part_table
mp_chan:        db 0
mp_note1:       dw 0
mp_note2:       dw 0
        EXPORT mp_inc
mp_inc:         dw 0
mv_res:         db 0
        EXPORT mv_vol
mv_vol:         db 0
        EXPORT mv_page
mv_page:        db 0
mv_saved:       db 0
        EXPORT mv_len
mv_len:         dw 0
        EXPORT mv_loop
mv_loop:        dw 0
        EXPORT mv_total
mv_total:       dw 0
        EXPORT n_snd
n_snd:          dw 0            ; op_playSound calls that reached the mixer
        EXPORT n_snd_stop
n_snd_stop:     dw 0            ; op_playSound calls with volume zero
        EXPORT n_snd_miss
n_snd_miss:     dw 0            ; op_playSound calls for a resource not resident
        EXPORT n_voice_set
n_voice_set:    dw 0            ; voices handed to the mixer, by either caller
vs_zero8:       db 0            ; 1 = zero four bytes at data+8, the module path only
        EXPORT n_mus_nores
n_mus_nores:    dw 0
        EXPORT n_mus_farloop
n_mus_farloop:  dw 0
blk_total:      db 0            ; the whole block, kept while blocklen holds one piece
blk_dst:        dw 0            ; where the block starts in the ring
mix_left:       db 0            ; samples of it this voice still owes
mix_pc:         dw 0            ; where in the ring this voice's next piece goes
        EXPORT n_mix
n_mix:          dw 0            ; interrupts that mixed; the game starts silent, so the ring
                                ; alone cannot say whether the mixer ran
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
        EXPORT save_req
save_req:   db 0            ; nonzero at a frame boundary: write the save and clear this
paged_saved: db 0           ; what MMU2 held before the paged code was called in
bmp_src:    db 0            ; present_bitmap's walking source and destination bands
bmp_dst:    db 0
        EXPORT n_bmp
n_bmp:      dw 0            ; full-screen bitmaps presented
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

        ; NOTE_TO_INC LIVES IN MMU6, not in the resident block, which ran out of room when
        ; the mixer's loop restore went in. MMU6 is mapped at every moment, so code runs
        ; from it as happily as data sits in it, and the seventy-two bytes between
        ; SND_BLOCK and the order table were the largest gap left anywhere in the program.
;-----------------------------------------------------------------------------
; PAGE 10, at $4000. See PAGED_PAGE for why anything is here at all.
;-----------------------------------------------------------------------------
        ; THE C'S OWN SYMBOL TABLE. tools/mkexp.py turns the C's link map into EQUs, which is
        ; how the paged save reads aw_vars and the rest without a byte of C code - and the C
        ; could not have grown by a byte to help. It is included here rather than at the top
        ; because only this region needs it.
        INCLUDE "build/aw_vm_c.exp"

        ORG PAGED_WIN
;-----------------------------------------------------------------------------
; I9. THE SAVE, all of it, in page 10. See PAGED_PAGE for why it is up here: the resident block
; has four bytes left and the C cannot grow by one, and this is the only region with room.
;
; It needs NO new resident state, which is the point worth recording. Both things a save has to
; know that nothing keeps are DERIVED here instead:
;
;   which part is running   part_table's rows name a bytecode resource each, and code_add + 1
;                           holds the page that resource landed at - so matching one against the
;                           other identifies the part, and no cur_part byte has to exist
;   the heap's load order   res_page maps id to first page, so walking pages upward from
;                           RES_FIRST_PAGE and asking which id owns each recovers the order
;                           saveOrLoad writes (resource.cpp:358 derives it the same way, by
;                           walking _memPtrStart)
;
; Five objects serialise in the reference, in this order (engine.cpp:136-138): the VM, the
; resources, the video, the player and the mixer. Ours is not their layout - nothing reads our
; saves but us - so what matters is that every one of the five is here.
;
; INTERRUPTS ARE OFF throughout. esxDOS wants them off across a call, and a band is written out
; of MMU7 which the mixer borrows fifty times a second - so a save is silent for its duration,
; as the reference's is.
;-----------------------------------------------------------------------------
SV_HDR          EQU PAGED_WIN + $1000   ; 256 bytes of header, built here before it is written
SV_BANDS        EQU 24                  ; four Layer 2 pages of six 8K bands

; save_req carries the mode so that a second byte does not have to exist: the resident block has
; four spare and MMU6's last gap has four. Clearing it here rather than in the caller makes the
; caller shorter too.
sv_entry:
        ld      a, (save_req)
        ld      b, a
        xor     a
        ld      (save_req), a
        ld      a, b
        dec     a
        jr      nz, .load
        call    sv_save
        jr      .stopped
.load:
        call    sv_load
.stopped:
        ; AND OPTIONALLY STOP THE MACHINE HERE, which is the only place it can be done exactly.
        ;
        ; A save is a SNAPSHOT, so a gate comparing it against the machine has to read a machine
        ; that has not moved since. Every way of arranging that from OUTSIDE is a race with the
        ; frame boundary, and this gate lost it four times: the C breaks on a fault or an empty
        ; budget at the check right after aw_frame_sync, so a stopper poked before the request
        ; can break the loop before the request is ever read, and one poked after can arrive too
        ; late - a save through ZEsarUX's esxDOS finishes in well under a tenth of a second, far
        ; inside one ZRCP round trip, which is what a measured run finally showed.
        ;
        ; Setting the fault HERE cannot race anything: the save has returned, the C's next act is
        ; the check that reads it, and no thread has run in between. sv_stop is zero in the image
        ; and only a checker writes it, so the shipped game never takes this branch - the same
        ; arrangement as the probe_ bytes the boot path already carries.
        ld      a, (sv_stop)
        or      a
        ret     z
        ld      (CTL + $0D), a          ; CTL_FAULT, and any non-zero value is a fault
        ret

;-----------------------------------------------------------------------------
; I9. THE LOAD. The mirror of the save, with one piece of real work: the resident resources are
; reloaded IN THE SAVED ORDER, so the heap lands exactly as it did - which is what makes the
; restored bytecode window and polygon window point at the right pages.
;
; IN TWO PASSES over the file, because esxDOS gives no seek. The first reads the header alone and
; closes; the part is then set up and the resources replayed, which toggles interrupts freely
; because aw_load_res must. The second re-opens, reads the header again and throws it away to get
; back to the right offset, and then reads the VM's arrays and the four pages with interrupts off
; throughout. One wasted 256-byte read is cheaper than carrying a seek we do not have.
;-----------------------------------------------------------------------------
sv_load:
        xor     a
        ld      (err), a
        ld      (sv_first), a           ; a fresh run records a fresh first read
        ld      (sv_got), a
        ld      (sv_got + 1), a
        ld      (sv_byte), a
        ld      (sv_ferr), a
        ld      (sv_done), a            ; cleared here, stamped at the end: a checker has no other
                                        ; way to know a 198,272-byte read has finished
        ld      hl, sv_name
        ld      de, fname
        ld      bc, 11
        ldir

        ; pass one: the header
        di
        call    sv_ropen
        ld      a, (err)
        or      a
        jp      nz, .give_up
        ld      hl, SV_HDR
        ld      bc, 256
        call    sv_rblock
        call    sv_close
        ei

        ; is it ours? a wrong magic is a refusal, not a crash
        ld      hl, SV_HDR
        ld      de, sv_magic
        ld      b, 4
.magic:
        ld      a, (de)
        cp      (hl)
        jp      nz, .bad_magic          ; jp: the load's body puts the refusal out of jr's reach
        inc     hl
        inc     de
        djnz    .magic

        ; the part, which invalidates everything and loads its own four
        ld      a, (SV_HDR + 4)
        cp      10
        jp      nc, .bad_magic
        call    aw_setup_part

        ; then the rest of the heap, in the order it was built. aw_load_res returns at once for
        ; anything already resident, so the part's own resources cost nothing the second time.
        ld      a, (SV_HDR + 15)
        or      a
        jr      z, .no_order
        ld      b, a
        ld      hl, SV_HDR + 128
.each_res:
        push    bc
        push    hl
        ld      l, (hl)
        ld      h, 0
        call    aw_load_res
        pop     hl
        inc     hl
        pop     bc
        djnz    .each_res
.no_order:

        ; pass two: everything that is a straight copy back
        ;
        ; RESTATE THE FILENAME, AND CLEAR err, because pass one and pass two are separated by
        ; aw_setup_part and the replayed heap - and those load resources through load_code, which
        ; shares BOTH of the loader's globals with us. It writes err, and it builds its own name
        ; over fname. Neither is the loader's fault: there is one loader and one name buffer, and
        ; anything that reopens a file across a load has to say which file it means.
        ;
        ; The err half was found and fixed first, and fixing half of it is why the symptom
        ; survived. With fname left holding the LAST RESOURCE'S name, sv_ropen opened that file
        ; and succeeded, sv_rblock read 512 bytes from it and succeeded, and the VM's arrays were
        ; filled with resource bytes - a load that reported err = 0 and sv_got = 512 the whole
        ; way. A sentinel painted over the destinations is what finally told the two apart: every
        ; sentinel byte was gone, so the reads were landing; the bytes were nowhere in the save
        ; file, so they were not coming from it.
        ld      hl, sv_name
        ld      de, fname
        ld      bc, 11
        ldir
        xor     a
        ld      (err), a
        di
        call    sv_ropen
        ld      a, (err)
        or      a
        jp      nz, .give_up
        ld      hl, SV_HDR
        ld      bc, 256
        call    sv_rblock               ; the header again, thrown away: esxDOS has no seek
        ; RE-ARM THE RECORDER HERE. It fired on the first read of the run, which is pass one's
        ; header - and that one always worked, so it told me nothing about the reads that matter.
        xor     a
        ld      (sv_first), a
        ld      hl, _aw_vars
        ld      bc, 512
        call    sv_rblock
        ld      hl, _aw_call_stack
        ld      bc, 512
        call    sv_rblock
        ld      hl, _aw_pc
        ld      bc, 256
        call    sv_rblock
        ld      hl, _aw_state
        ld      bc, 128
        call    sv_rblock
        call    sv_rpages
        call    dt_reset                ; every page came off the card; see dirty_band
        call    sv_close

        ; and the scattered bytes, back out of the header
        ld      a, (SV_HDR + 6)
        ld      (pal_req), a
        ld      a, (SV_HDR + 7)
        ld      (pg_ptr1), a
        ld      a, (SV_HDR + 8)
        ld      (pg_ptr2), a
        ld      a, (SV_HDR + 9)
        ld      (pg_ptr3), a
        ld      a, (SV_HDR + 10)
        ld      (_aw_sp), a
        ld      a, (SV_HDR + 11)
        ld      (_aw_goto_next), a
        ld      hl, (SV_HDR + 12)
        ld      (_aw_part_req), hl
        ld      a, (SV_HDR + 16)
        ld      (mus_res), a
        ld      a, (SV_HDR + 17)
        ld      (mus_playing), a
        ld      a, (SV_HDR + 18)
        ld      (mus_page), a
        ld      a, (SV_HDR + 19)
        ld      (mus_cur_order), a
        ld      hl, (SV_HDR + 20)
        ld      (mus_cur_pos), hl
        ld      hl, (SV_HDR + 22)
        ld      (mus_acc), hl           ; the period is recomputed from mus_delay_raw on its own
        ld      hl, (SV_HDR + 24)
        ld      (mus_delay_raw), hl
        ld      hl, (SV_HDR + 26)
        ld      (mus_mark), hl
        ld      a, (SV_HDR + 28)
        ld      (mus_num_order), a
        ld      hl, SV_HDR + 32
        ld      de, VOICES
        ld      bc, V_SIZE * 4
        ldir                            ; the mixer, mid-note and all

        ; THE PALETTE IS REQUESTED, NOT APPLIED. apply_palette maps the text page at MMU2 - the
        ; same slot this code is running from - so calling it here would be the second way to
        ; saw off the branch. aw_blit consumes pal_req and applies it, which is the reference's
        ; own arrangement too (paletteIdRequested, video.cpp), so the next blit does it.
        ld      a, (SV_HDR + 5)
        cp      32
        jr      nc, .done_load
        ld      (pal_req), a
.done_load:
        ld      a, $5A
        ld      (sv_done), a
        ei
        ret
.bad_magic:
        ld      a, $FF
        ld      (err), a
        ret
.give_up:
        call    sv_close
        ei
        ret

; The four Layer 2 pages, read back band by band through MMU7, which is put back after.
sv_rpages:
        ld      bc, $243B
        ld      a, NR_DWIN_MMU
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      (sv_mmu7), a
        ld      a, L2_BASE_BANK * 2
        ld      (sv_band), a
        ld      b, SV_BANDS
.band:
        push    bc
        ld      a, (sv_band)
        nextreg NR_DWIN_MMU, a
        ld      hl, DWIN
        ld      bc, $2000
        call    sv_rblock
        ld      hl, sv_band
        inc     (hl)
        pop     bc
        djnz    .band
        ld      a, (sv_mmu7)
        nextreg NR_DWIN_MMU, a
        ret

sv_ropen:
        ld      a, ESX_DRIVE
        ld      ix, fname
        ld      hl, fname
        ld      b, FA_READ
        rst     $08
        db      F_OPEN
        jr      c, .failed
        ld      (handle), a
        ret
.failed:
        ld      (err), a
        ret

; HL = destination, BC = length. In 2K pieces, as the writer is.
sv_rblock:
        ld      a, (err)
        or      a
        ret     nz
        ld      (sv_src), hl
        ld      (sv_left), bc
.next:
        ld      hl, (sv_left)
        ld      a, h
        or      l
        ret     z
        ld      de, $0800
        or      a
        sbc     hl, de
        jr      nc, .full
        ld      bc, (sv_left)
        jr      .go
.full:
        ld      bc, $0800
.go:
        ld      a, (handle)
        ld      ix, (sv_src)
        ld      hl, (sv_src)
        rst     $08
        db      F_READ
        ; EVIDENCE, not another hypothesis. Two guesses from the symptom have cost a gate run
        ; each; these four bytes say whether a read happened at all, what it returned, and where
        ; it went. sv_first is set once, by the first read of the run.
        push    af
        ld      a, (sv_first)
        or      a
        jr      nz, .not_first
        ld      a, $5A
        ld      (sv_first), a
        pop     af
        push    af
        jr      c, .first_failed
        ld      (sv_got), bc            ; what it says it read
        ld      a, (ix + 0)
        ld      (sv_byte), a            ; and the first byte that landed
        jr      .not_first
.first_failed:
        ld      (sv_ferr), a
.not_first:
        pop     af
        jr      nc, .read
        ld      (err), a
        ret
.read:
        ld      a, b
        or      c
        ret     z                       ; short read: stop rather than spin
        ld      hl, (sv_src)
        add     hl, bc
        ld      (sv_src), hl
        ld      hl, (sv_left)
        or      a
        sbc     hl, bc
        ld      (sv_left), hl
        jr      .next

sv_save:
        di
        xor     a
        ld      (err), a
        ; ITS OWN NAME. fname is what the BOOT path reads to decide between the fixed load every
        ; gate uses and starting a part, so a save cannot borrow it without meaning something
        ; else the next time the machine comes up. It is only read at boot, so overwriting it
        ; here is free.
        ld      hl, sv_name
        ld      de, fname
        ld      bc, 11
        ldir
        call    sv_header
        call    sv_open
        ld      a, (err)
        or      a
        jr      nz, .done
        ; the header, then the VM's four arrays, then every band
        ld      hl, SV_HDR
        ld      bc, 256
        call    sv_block
        ld      hl, _aw_vars
        ld      bc, 512
        call    sv_block
        ld      hl, _aw_call_stack
        ld      bc, 512
        call    sv_block
        ld      hl, _aw_pc
        ld      bc, 256                 ; aw_pc and aw_pc_req are adjacent and both 128
        call    sv_block
        ld      hl, _aw_state
        ld      bc, 128                 ; aw_state and aw_state_req likewise
        call    sv_block
        call    sv_pages
.done:
        call    sv_close
        ei
        ret

; The header: everything scattered, gathered once.
sv_header:
        ld      hl, sv_magic
        ld      de, SV_HDR
        ld      bc, 4
        ldir
        call    sv_which_part
        ld      (SV_HDR + 4), a
        ld      a, (pal_now)
        ld      (SV_HDR + 5), a
        ld      a, (pal_req)
        ld      (SV_HDR + 6), a
        ld      a, (pg_ptr1)
        ld      (SV_HDR + 7), a
        ld      a, (pg_ptr2)
        ld      (SV_HDR + 8), a
        ld      a, (pg_ptr3)
        ld      (SV_HDR + 9), a
        ld      a, (_aw_sp)
        ld      (SV_HDR + 10), a
        ld      a, (_aw_goto_next)
        ld      (SV_HDR + 11), a
        ld      hl, (_aw_part_req)
        ld      (SV_HDR + 12), hl
        ; the player - every byte of it, because a save mid-note has to restore the note
        ld      a, (mus_res)
        ld      (SV_HDR + 16), a
        ld      a, (mus_playing)
        ld      (SV_HDR + 17), a
        ld      a, (mus_page)
        ld      (SV_HDR + 18), a
        ld      a, (mus_cur_order)
        ld      (SV_HDR + 19), a
        ld      hl, (mus_cur_pos)
        ld      (SV_HDR + 20), hl
        ld      hl, (mus_acc)
        ld      (SV_HDR + 22), hl
        ld      hl, (mus_delay_raw)
        ld      (SV_HDR + 24), hl
        ld      hl, (mus_mark)
        ld      (SV_HDR + 26), hl
        ld      a, (mus_num_order)
        ld      (SV_HDR + 28), a
        ; the mixer: four voice records, verbatim
        ld      hl, VOICES
        ld      de, SV_HDR + 32
        ld      bc, V_SIZE * 4
        ldir
        ; and the heap's load order
        jp      sv_order

; A = the part index, derived. code_add + 1 is the page the current bytecode landed at, and each
; row of part_table names a bytecode resource in its second byte.
sv_which_part:
        ld      a, (code_add + 1)
        ld      c, a
        ld      hl, part_table + 1
        ld      b, 0                    ; B = the row
.row:
        ld      a, (hl)                 ; this part's bytecode resource
        push    hl
        ld      h, 0
        ld      l, a
        ld      de, res_page
        add     hl, de
        ld      a, (hl)
        pop     hl
        cp      c
        jr      z, .found
        inc     b
        ld      a, b
        cp      10
        jr      nc, .unknown
        ld      de, 4
        add     hl, de
        jr      .row
.found:
        ld      a, b
        ret
.unknown:
        ld      a, $FF                  ; no row matches: recorded rather than guessed
        ret

; The resident ids in heap order, into SV_HDR + 128, and the count at SV_HDR + 15.
;
; res_page maps id to first page, so walking pages upward from RES_FIRST_PAGE and asking which id
; owns each recovers the order saveOrLoad writes - resource.cpp:358 derives it the same way, by
; walking _memPtrStart. Stepping past a resource's whole page count matters: without it the
; SECOND page of a six-page bitmap would look like another resource starting.
;
; THE COUNT LIVES IN MEMORY, not in D. It was in D, and `ld de, res_table` three instructions
; later destroyed it - which the gate caught as a list of zeros.
sv_order:
        xor     a
        ld      (sv_n), a
        ld      hl, SV_HDR + 128
        ld      a, RES_FIRST_PAGE
        ld      c, a                    ; C = the page being asked about
.page:
        ld      a, (next_page)
        cp      c
        jr      z, .done_order          ; the cursor: nothing at or past it is resident
        jr      c, .done_order
        push    hl
        ld      b, 0                    ; B = the id being tried
        ld      hl, res_page
.try:
        ld      a, (hl)
        cp      c
        jr      z, .owner
        inc     hl
        inc     b
        ld      a, b
        or      a
        jr      nz, .try
        pop     hl
        inc     c                       ; nothing owns this page: step over the gap
        jr      .page
.owner:
        pop     hl
        ld      (hl), b                 ; this id starts here
        inc     hl
        ld      a, (sv_n)
        inc     a
        ld      (sv_n), a
        cp      64
        jr      nc, .done_order         ; the header holds 64, as the reference's list does
        ; step past the whole resource, so its later pages are not read as another one
        push    hl
        ld      h, 0
        ld      l, b
        add     hl, hl
        add     hl, hl
        ld      de, res_table
        add     hl, de
        inc     hl
        inc     hl
        inc     hl
        ld      a, (hl)                 ; its page count
        pop     hl
        or      a
        jr      nz, .step
        inc     a                       ; a zero-page resource would not advance C at all
.step:
        add     a, c
        ld      c, a
        jr      .page
.done_order:
        ld      a, (sv_n)
        ld      (SV_HDR + 15), a
        ret

; The four Layer 2 pages, band by band, out of MMU7 - which is borrowed and put back because the
; mixer reads a sample through the same slot.
sv_pages:
        ld      bc, $243B
        ld      a, NR_DWIN_MMU
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      (sv_mmu7), a
        ld      a, L2_BASE_BANK * 2
        ld      (sv_band), a
        ld      b, SV_BANDS
.band:
        push    bc
        ld      a, (sv_band)
        nextreg NR_DWIN_MMU, a
        ld      hl, DWIN
        ld      bc, $2000
        call    sv_block
        ld      hl, sv_band
        inc     (hl)
        pop     bc
        djnz    .band
        ld      a, (sv_mmu7)
        nextreg NR_DWIN_MMU, a
        ret

sv_open:
        ld      a, ESX_DRIVE
        ld      ix, fname
        ld      hl, fname
        ld      b, FA_WRITE
        rst     $08
        db      F_OPEN
        ret     nc
        ld      (err), a
        ret

; HL = source, BC = length. Written in 2K pieces, because one promise about how much esxDOS takes
; at a time is one promise too many.
sv_block:
        ld      a, (err)
        or      a
        ret     nz
        ld      (sv_src), hl
        ld      (sv_left), bc
.next:
        ld      hl, (sv_left)
        ld      a, h
        or      l
        ret     z
        ld      de, $0800
        or      a
        sbc     hl, de
        jr      nc, .full
        ld      bc, (sv_left)
        jr      .go
.full:
        ld      bc, $0800
.go:
        ld      a, (handle)
        ld      ix, (sv_src)
        ld      hl, (sv_src)
        rst     $08
        db      F_WRITE
        jr      nc, .wrote
        ld      (err), a
        ret
.wrote:
        ld      a, b
        or      c
        ret     z                       ; it took nothing: stop rather than spin
        ld      hl, (sv_src)
        add     hl, bc
        ld      (sv_src), hl
        ld      hl, (sv_left)
        or      a
        sbc     hl, bc
        ld      (sv_left), hl
        jr      .next

sv_close:
        ld      a, (handle)
        rst     $08
        db      F_CLOSE
        ret

sv_magic:   db "AWS1"
sv_name:    db "AWSAVE.BIN", 0
sv_src:     dw 0
sv_left:    dw 0
sv_band:    db 0
sv_n:       db 0            ; sv_order's count, which a register could not survive
        EXPORT sv_first
sv_first:   db 0            ; $5A once the first read of a run has been recorded
        EXPORT sv_got
sv_got:     dw 0            ; what that read returned in BC
        EXPORT sv_byte
sv_byte:    db 0            ; and the first byte it put down
        EXPORT sv_ferr
sv_ferr:    db 0            ; or the esxDOS error, if it failed
        EXPORT sv_done
sv_done:    db 0            ; $5A once a load has finished; page 10, read by mapping it
        EXPORT sv_stop
sv_stop:    db 0            ; a checker sets this to have the save or load fault the VM on return
sv_mmu7:    db 0
        DISPLAY "> paged code at ", /H, PAGED_WIN, " ending ", /H, $
        ASSERT $ <= SV_HDR

        ORG PART_CODE
;-----------------------------------------------------------------------------
; aw_saveload - save_req says which: 1 to write the save, 2 to read it back. All of both
; lives in page 10, and this is the borrow that maps it in.
;
; The BODY of this lives in page 10, at $4000, because the resident 16K had four bytes left in
; it. All that is down here is the borrow: map page 10 at MMU2, call in, put back what was
; there. MMU2 is the polygon segment window and every draw re-maps it from seg_base before it
; reads, so what is put back hardly matters - but reading it first costs three instructions and
; means this is safe to call from anywhere.
;-----------------------------------------------------------------------------
aw_saveload:
        ld      bc, $243B
        ld      a, NR_PAGED_MMU
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      (paged_saved), a
        ld      a, PAGED_PAGE
        nextreg NR_PAGED_MMU, a
        call    sv_entry
        ld      a, (paged_saved)
        nextreg NR_PAGED_MMU, a
        ret

; A = a low nibble, out as the ASCII hex digit. Uppercase, because that is what mkassets.py
; writes. Up here because the resident block ran out and MMU6 is mapped at every moment - both
; callers, aw_load_res's name builder and aw_setup_part's, reach it either way.
hex_digit:
        and     $0F
        add     a, '0'
        cp      '9' + 1
        ret     c
        add     a, 'A' - '0' - 10
        ret

;-----------------------------------------------------------------------------
; I6. aw_setup_part - A = the part INDEX, 0..9. setupPart, resource.cpp:280, and the half of
; initForPart, vm.cpp, that is not the thread reset.
;
; The C has already turned op_updateMemList's id into an index and bounds-checked it, because
; that is where the id arrives; this takes the index and does the four things the reference does
; in order:
;
;   stop the player and every channel   initForPart, before setupPart touches a resource
;   invalidate everything               invalidateAll, resource.cpp:298
;   load the part's four resources      loadMarkedAsNeeded, resource.cpp:310
;   point the three windows at them     segPalettes, segBytecode, segCinematic, _segVideo2
;
; Every load goes through aw_load_res, which is the path check-res already proves byte for byte
; against the card - so this adds no new way to get a resource wrong, only a new reason to ask
; for one. The palette is the exception: apply_palette reads it out of the text page at
; PAL_BASE, so the 1,024 bytes are copied there once the resource is resident.
;-----------------------------------------------------------------------------
aw_setup_part:
        add     a, a
        add     a, a                    ; four bytes an entry - parts.cpp, via mkparts.py
        ld      e, a
        ld      d, 0
        ld      hl, part_table
        add     hl, de
        ld      (part_ptr), hl

        ; the player and all four voices, before anything moves underneath them
        xor     a
        ld      (mus_playing), a
        ld      (mus_res), a
        ld      ix, VOICES
        ld      b, 4
.quiet:
        ld      (ix + V_ACTIVE), 0
        ld      de, V_SIZE
        add     ix, de
        djnz    .quiet

        call    aw_inval_res

        ; the palette, to the text page where apply_palette looks for it
        ld      hl, (part_ptr)
        ld      a, (hl)
        call    part_load
        call    copy_palette

        ; the bytecode, and the window's base with it
        ld      hl, (part_ptr)
        inc     hl
        ld      a, (hl)
        call    part_load
        ld      (code_add + 1), a

        ; THE PC GUARD, which the fixed path sets from what the loader read. A part's bytecode
        ; length is in the resource table, and vm.c faults a thread whose pc leaves the segment -
        ; without this a part would run with the previous part's bound.
        ld      hl, (part_ptr)
        inc     hl
        ld      a, (hl)
        ld      h, 0
        ld      l, a
        add     hl, hl
        add     hl, hl                  ; four bytes an entry: type, size as a word, pages
        ld      de, res_table
        add     hl, de
        inc     hl
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ld      (CTL + $10), de

        ; the cinematic polygons
        ld      hl, (part_ptr)
        inc     hl
        inc     hl
        ld      a, (hl)
        call    part_load
        ld      (cin_base), a

        ; and the second polygon set, which five of the ten parts do not have
        ld      hl, (part_ptr)
        inc     hl
        inc     hl
        inc     hl
        ld      a, (hl)
        ld      (vid2_base), a          ; zero stands for MEMLIST_PART_NONE, parts.h:32
        or      a
        ret     z
        call    part_load
        ld      (vid2_base), a
        ret

; A = a resource id. Loads it if it is not resident and returns its first page in A.
part_load:
        ld      l, a
        ld      h, 0
        push    hl
        di                              ; esxDOS wants it off; see the boot path
        call    aw_load_res
        ei
        pop     hl
        ld      de, res_page
        add     hl, de
        ld      a, (hl)
        ret

; A = the palette resource's first page. Its 1,024 bytes go to PAL_BASE in the text page,
; through MMU2 for the source and MMU7 for the destination - MMU7 borrowed and put back,
; because the mixer reads a sample through the same slot from inside the interrupt.
copy_palette:
        nextreg NR_PAL_SRC_MMU, a
        ld      bc, $243B
        ld      a, NR_TEXT_MMU_HI
        out     (c), a
        ld      b, $25
        in      a, (c)
        push    af
        ld      a, TEXT_PAGE
        nextreg NR_TEXT_MMU_HI, a
        ld      hl, PAL_SRC_WIN
        ld      de, PAL_BASE
        ld      bc, 1024
        ldir
        pop     af
        nextreg NR_TEXT_MMU_HI, a
        ret

; probe_walk - run the event walk (probe_ticks) times with the tick period forced to one
; frame, so each call fires. The walk is what is under test, not the pacing. Up here with the
; music code because the resident block had room at the time; it does not now, and MMU6's
; freed ramp buffer does - so it lives at PART_CODE with aw_setup_part.
probe_walk:
        ld      a, (probe_ticks)
        or      a
        ret     z
        ; LOAD THE INSTRUMENTS THE MODULE NAMES. The bytecode would have asked for them through
        ; op_updateMemList long before it played any music; the probe loads the module alone, so
        ; without this every note found its sample absent, counted n_mus_nores and left the voice
        ; at its boot values - which read as "every channel has increment 256" because that is
        ; what init_voices leaves.
        ld      (pw_left), a            ; KEEP IT. The loop below runs `ld a,(hl)` fifteen times,
                                        ; so the `ld b,a` that used to follow it took its event
                                        ; count from a table byte - zero, every time, which djnz
                                        ; reads as 256. EVERY probe run walked the module to its
                                        ; end no matter what probe_ticks said, which is why all
                                        ; four voices came up active for a one-event walk whose
                                        ; only row was a stop.
        ld      hl, MUS_INSTR_AT        ; the COMPACTED table: resource byte, volume byte
        ld      b, 15
.ins:
        ld      a, (hl)
        or      a
        jr      z, .next_ins
        push    bc
        push    hl
        ld      l, a
        ld      h, 0
        call    aw_load_res
        pop     hl
        pop     bc
.next_ins:
        inc     hl
        inc     hl
        djnz    .ins
        ld      a, (pw_left)
        ld      b, a
.tick:
        push    bc
        call    music_tick
        pop     bc
        djnz    .tick
        ret
        DISPLAY "> part code at ", /H, PART_CODE, " ending ", /H, $
        ASSERT $ <= VOLTAB_QUIET

        ORG NOTE_CODE
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



        DISPLAY "> note_to_inc at ", /H, NOTE_CODE, " ending ", /H, $
        ASSERT $ <= MUS_ORDER_AT



        ORG     STACK_CODE
;-----------------------------------------------------------------------------
; STACK_CODE, $CF00-$CFFF: the bottom of what used to be stack. See STACK_FLOOR for the
; measurement that freed it. MMU6 is always paged - the stack is in it - so code here can be
; called from anywhere.
;
; load_flat WAS AT $C3DE, and that was a fault of mine: $C400 is MUS_ORDER_AT and $C480 is
; MUS_INSTR_AT, run-time tables the assembler never places, so the page's DISPLAY lines showed
; the space as free. op_playMusic copies the order table over load_flat's tail. It survived only
; because load_flat runs once, at boot, before any music - and the music clock, which runs
; every frame, did not survive it at all: check-aw caught the VM running wild on its first try.
; A list of what the assembler places is not a map of memory; this project has now learned
; that twice.
;-----------------------------------------------------------------------------
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
        call    esx_rom
        ld      a, ESX_DRIVE
        ld      ix, fname
        ld      hl, fname
        ld      b, FA_READ
        rst     $08
        db      F_OPEN
        jr      nc, .opened
        ld      (err), a
        jr      .done
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
.done:
        jp      esx_back

lf_dst:     dw 0
lf_len:     dw 0


;-----------------------------------------------------------------------------
; music_clock - the module's event timer, run from the frame boundary and driven by the TICK.
;
; The reference plays a module from a system timer: addTimer(_delay) with _delay = delay * 60 /
; 7050 milliseconds (sfxplayer.cpp:43 and :103), and eventsCallback returns the delay again, so
; events come every _delay ms whatever the rest of the game is doing. This used to count calls
; from aw_frame_sync instead - VM FRAMES - against a period of delay / 2350 FRAMES, so every
; intro frame that took four ticks made the tune four times slower. Measured in CSpect: 2.09
; events a second against the reference's 7.71, and exactly one event per six VM frames.
;
; So elapsed ticks are counted as 20 ms each into mus_acc, and every event that is due runs.
; Events are still only RUN at a frame boundary - the walk pages the module into MMU2, which a
; draw may own, so it cannot move into the interrupt - so a slow frame delays them and the next
; boundary catches up. The tempo is right; the jitter is at most one frame.
;-----------------------------------------------------------------------------
music_clock:
        ld      a, (mus_playing)
        or      a
        ret     z
        ; a new delay - a start, a retime, a restored save - means a new period
        ld      hl, (mus_delay_raw)
        ld      de, (mus_period_raw)
        or      a
        sbc     hl, de
        call    nz, mus_set_period
        ; ticks since the last call, ALL of them owed. The reference's timer runs through a slow
        ; frame, and the intro has real frames of 33 and 155 ticks: an earlier half-second cap
        ; here threw 6.2% of the intro's time away and measured the tune 4.5% slow. Only a gap
        ; over 255 ticks - five seconds, a clock that genuinely was not running - counts as one.
        ld      hl, (ticks)
        ld      de, (mus_last_tick)
        ld      (mus_last_tick), hl
        or      a
        sbc     hl, de
        ld      a, h
        or      a
        jr      z, .fresh
        ld      hl, 1
.fresh:
        add     hl, hl                  ; ticks * 20 ms
        add     hl, hl
        ld      d, h
        ld      e, l
        add     hl, hl
        add     hl, hl
        add     hl, de
        ld      de, (mus_acc)
        add     hl, de
        ld      (mus_acc), hl
        ld      b, 0                    ; up to 256 events a boundary: a 155-tick frame owes 23
.due:
        ld      hl, (mus_acc)
        ld      de, (mus_period)
        or      a
        sbc     hl, de
        ret     c
        ld      (mus_acc), hl
        push    bc
        call    music_tick
        pop     bc
        ld      a, (mus_playing)
        or      a
        ret     z                       ; the module ended on that event
        djnz    .due
        ret

; op_playMusic with a zero resource: snd_playMusic, vm.cpp:729-733.
mus_zero:
        ld      hl, (MUS_BLOCK + 1)
        ld      a, h
        or      l
        jr      z, .stop
        ld      (mus_delay_raw), hl     ; setEventsDelay: music_clock picks the new period up
        ret
.stop:
        xor     a                       ; SfxPlayer::stop removes the TIMER and nothing else -
        ld      (mus_playing), a        ; notes already sounding carry on (sfxplayer.cpp:106-113)
        ret

; A module starts: nothing owed, and the clock runs from now.
mus_clock_start:
        ld      hl, 0
        ld      (mus_acc), hl
        ld      hl, (ticks)
        ld      (mus_last_tick), hl
        ; and on into the period

; mus_period = mus_delay_raw * 60 / 7050 ms, the reference's own integer arithmetic. 60/7050 is
; 2/235 exactly, so it is a 17-bit dividend over an 8-bit divisor: raw * 2 in A:HL, then
; subtract 235 until it borrows. At most 557 turns, and only when the delay changes.
mus_set_period:
        ld      hl, (mus_delay_raw)
        ld      (mus_period_raw), hl
        xor     a
        add     hl, hl
        adc     a, a
        ld      bc, 235
        ld      de, 0
.div:
        or      a
        sbc     hl, bc
        sbc     a, 0
        jr      c, .done
        inc     de
        jr      .div
.done:
        ld      a, d
        or      e
        jr      nz, .ok
        inc     e                       ; never zero: the loop in music_clock would never end
.ok:
        ld      (mus_period), de
        ret

        EXPORT mus_period
mus_period:     dw 1
mus_period_raw: dw $FFFF
mus_last_tick:  dw 0

;-----------------------------------------------------------------------------
; DIRTY BANDS - a page copy moves only what the destination has had drawn on it since it was
; last a copy of that same source.
;
; The intro copies a whole page before 57% of its blits, and a copy is 49,152 bytes of LDIR -
; about 2.4 ticks of the machine, measured, whatever is drawn afterwards. Most of those copies
; restore a background the previous frame drew a few small shapes over. So each page remembers:
;
;   dt_origin[p]  the page it was last copied from, while it still is an exact copy of it apart
;                 from the bands in dt_dirty[p]; $FF when it is not
;   dt_dirty[p]   bit n set = band n (32 rows, one 8K page) has been drawn into since that copy
;
; and a plain copy s -> d moves only dt_dirty[d] when dt_origin[d] == s, every band otherwise.
; For that to be exact, ANY write to a page must end every mirror OF it (dt_unmirror): the source
; changing invalidates the copies taken from it. The writers are band_set (spans and points),
; draw_char6 (text), aw_fill_page, aw_copy_page itself, present_bitmap and the save's page
; restore. Simulated against the reference on the intro's 700 blits first: every page identical
; at every blit, and 50.6% of the bytes copied.
;-----------------------------------------------------------------------------

; dirty_band - A = a band about to be drawn into, on the page pg_ptr1 names. Keeps AF, BC, DE.
dirty_band:
        push    af
        push    bc
        ld      b, a
        ld      a, (pg_ptr1)
        ld      c, a
        call    dt_unmirror             ; this page is changing: nothing mirrors it any more
        ld      hl, dt_dirty
        ld      a, l
        add     a, c
        ld      l, a                    ; the table does not straddle a 256-byte boundary: ASSERTed
        inc     b
        xor     a
        scf
.bit:   rla
        djnz    .bit                    ; A = 1 << band
        or      (hl)
        ld      (hl), a
        pop     bc
        pop     af
        ret

; dt_forget - A = a page overwritten outright. It mirrors nothing, and nothing mirrors it.
; Keeps AF and BC.
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
        ld      hl, dt_origin
        ld      a, c
        cp      (hl)
        jr      nz, .one
        ld      (hl), $FF
.one:   inc     hl
        cp      (hl)
        jr      nz, .two
        ld      (hl), $FF
.two:   inc     hl
        cp      (hl)
        jr      nz, .three
        ld      (hl), $FF
.three: inc     hl
        cp      (hl)
        ret     nz
        ld      (hl), $FF
        ret

; dt_copy_mask - a plain copy of page (cp_sidx) onto page (cp_didx) is about to run. Returns B =
; the bands it must move, and records the destination as a fresh copy of the source.
dt_copy_mask:
        ld      a, (cp_didx)
        ld      c, a
        ld      a, (cp_sidx)
        ld      b, 0
        cp      c
        ret     z                       ; the same page both ends: the reference returns too
        call    dt_unmirror             ; the destination is changing
        ld      hl, dt_origin
        add     hl, bc                  ; B is 0, C the destination
        ld      a, (cp_sidx)
        cp      (hl)
        ld      (hl), a                 ; from now on it mirrors this source
        ld      de, 4
        add     hl, de                  ; dt_dirty[destination]
        ld      b, $3F                  ; all six bands, unless it already mirrored this source
        jr      nz, .all
        ld      b, (hl)
.all:
        ld      (hl), 0
        ret

; dt_reset - every page restored from somewhere else: nothing mirrors anything.
dt_reset:
        ld      a, $FF
        ld      (dt_origin), a
        ld      (dt_origin + 1), a
        ld      (dt_origin + 2), a
        ld      (dt_origin + 3), a
        ret

        EXPORT dt_origin
dt_origin:      db $FF, $FF, $FF, $FF
        EXPORT dt_dirty
dt_dirty:       db 0, 0, 0, 0
        ASSERT (dt_dirty & $FF) <= 252   ; dirty_band indexes it by adding to the low byte
cp_sidx:        db 0
cp_didx:        db 0

;-----------------------------------------------------------------------------
; pace_blit - the pause a script asks for, vm.cpp:285-297, as a deadline carried forward.
;
; The reference sleeps pause_slices * 20 ms less whatever the frame took, then shows it. A frame
; that took too long does not sleep, and on a PC that never happens. Here it does, so the
; deadline advances by the pause WHATEVER happened - the E1 arrangement check-pace proves on its
; own harness - and a late frame is made up by the light frames after it, which keeps the
; pictures in step with the music, whose clock runs on real time. The debt is capped at
; PACE_DEBT: past that - a load, say - the schedule starts again from now rather than racing.
;-----------------------------------------------------------------------------
PACE_DEBT       EQU 50                  ; a second of catching up at most
pace_blit:
        ei                              ; the wait needs the tick; see aw_frame_sync
        ld      hl, (_aw_vars + $FF * 2)        ; VM_VARIABLE_PAUSE_SLICES, low byte
        ld      h, 0
        ld      de, (pace_due)
        add     hl, de
        ld      (pace_due), hl
.wait:
        ld      hl, (pace_due)
        ld      de, (ticks)
        or      a
        sbc     hl, de                  ; the deadline, less now
        ret     z                       ; due
        jr      c, .late
        ld      a, h
        or      a
        jr      z, .wait                ; early by under 256 ticks: wait for it
        jr      .restart                ; further ahead than any pause: a stale deadline
.late:
        ld      a, h
        inc     a
        jr      nz, .restart            ; 256 or more behind
        ld      a, l
        cp      256 - PACE_DEBT
        ret     nc                      ; behind, within the debt: no wait, catch up
.restart:
        ld      (pace_due), de          ; count from now
        ret
pace_due:       dw 0

        ASSERT $ <= STACK_FLOOR
        DISPLAY "> stack code at ", /H, STACK_CODE, " ending ", /H, $

        ORG SND_FREQ
        INCLUDE "build/sndfreq.inc"
        ASSERT $ <= RD_LOG_AT

        ORG RD_LOG_AT
rd_log:     ds 8 * RD_LOG_RECS      ; the reader's leaf log; nothing in the game reads it

        ; THE FILENAMES, up here for room and not for tidiness: they are data an ldir copies
        ; out of, so they can live in any page that is mapped, and MMU6 always is. The resident
        ; block below the C had three bytes left when probe_mix went in.
NAMES_AT    EQU $CE94
        ORG NAMES_AT
pal_name:   db "PAL17.BIN", 0
poly_name:  db "RES19.BIN", 0
nm_res:     db "RES", 0
nm_pal:     db "PAL", 0
nm_bmp:     db "BMP", 0
nm_tail:    db ".BIN", 0
        ASSERT $ <= VEC_TRAMP
        DISPLAY "> pitches at ", /H, SND_FREQ, ", leaf log to ", /H, $
        ASSERT $ <= VEC_TRAMP

        ORG INTERP_AT
        ALIGN 2
        INCLUDE "build/interp.inc"
        DISPLAY "> reciprocals at ", /H, INTERP_AT, " ending ", /H, $
        ASSERT $ <= RING_ADDR

        ; part_table, WITH AN ORG AND A BOUND OF ITS OWN, which is the whole point of moving it.
        ;
        ; It used to be INCLUDEd immediately after the part code with no ORG, so it started
        ; wherever that code happened to end - $DEFC on the build that was measured. VOLTAB_QUIET
        ; is at $DF00. Four bytes of the table fitted below it and the other thirty-six did not,
        ; so part 0's row survived and every other part read the quiet volume table instead: part
        ; 1 "loaded" resource 1 and part 2 loaded 1 and 2, which are volume entries, not ids.
        ;
        ; Part 0 working is exactly what hid it. The index is scaled by four, so part 0 reads
        ; offset 0 whatever the base is, and the boot path is the only caller that passes 0.
        ;
        ; The ASSERT above it was real and passed: it bounded the part CODE, and it was written
        ; before the INCLUDE, so it never measured the table it was meant to protect. An
        ; assertion that runs before the thing it guards is not an assertion. Same shape as the
        ; CC_TOP trap, where the check saw the C's image and its variables lived above it.
        ASSERT PART_TABLE_AT >= VOICES + V_SIZE * 4
        ORG PART_TABLE_AT
        INCLUDE "build/parts.inc"
        DISPLAY "> the part table at ", /H, PART_TABLE_AT, " ending ", /H, $
        ASSERT $ <= PART_CODE

;-----------------------------------------------------------------------------
; auto_input - THE PROBE'S OWN SYNTHETIC PLAYER, on the machine.
;
; Every gameplay measurement this project has is the host probe's, and the probe only reaches
; gameplay because headless.cpp drives the engine with a fixed function of the frame number
; (its processEvents): walk right, jump, walk left, and fire on a short cycle. Without it the
; run stops at the intro's "press fire" prompt, which is how 57,386 of 60,000 frames once came
; to draw nothing.
;
; The machine needs THE SAME FUNCTION and not merely some input. I9a asks for the narrow gates
; to be re-run against a gameplay part, and a gate that compares the machine's stream against
; the reference's can only mean something if both were given identical input - so this
; reproduces the probe's arithmetic exactly:
;
;     f % 400 < 260   right        (else) < 300   up      (else) < 330   left
;     button = (f % 47) < 6
;
; f IS THE FRAME, NOT THE TICK. The reference reads input once a frame; this runs in the
; interrupt, fifty times a second, and frames are slower than that. So the two modular counters
; advance only when CTL_FRAMES_DONE changes, which keeps them in step with the reference's
; gFrameNo rather than with the refresh. Counting instead of dividing also keeps the whole
; thing to a compare and two increments in an interrupt that has a mixer to run.
;-----------------------------------------------------------------------------
auto_input:
    IFDEF DIAG_BORDER
        ; A CYCLING BORDER, from inside the interrupt. auto_input is called by the ISR every
        ; frame, so this answers one question and no other: IS THE FRAME INTERRUPT FIRING?
        ;
        ;   border cycling   the ISR runs, and a hang is somewhere the ISR is not
        ;   border frozen    the ISR is not running, and aw_frame_sync's spin on `ticks`
        ;                    can never end - which is a hang with no fault and no output
        ;
        ; It costs nothing resident and is diagnostic only: build with -DDIAG_BORDER.
        ; THE BORDER IS CTL_FAULT. The first version cycled from `ticks` to answer "is the
        ; interrupt alive", and it is - so the question moves on. The VM's fault code is a
        ; small number and the border takes a small number, so the border can simply BE it:
        ;
        ;   black    no fault; the VM is running or has finished cleanly
        ;   blue  1  FAULT_PAST_END   the pc left the segment that was loaded
        ;   red   2  FAULT_RESET      resetThread over a range outside the table
        ;   magenta 3 FAULT_BAD_OP    an opcode the reference calls error() on
        ;   green 4  FAULT_BAD_PART / FAULT_RET
        ;   cyan  5  FAULT_DIVERGE    a record the engine did not produce
        ;   yellow 6 FAULT_OVERRUN    more records than the engine produced
        ;
        ; Five bytes, which is what the block has left.
        ; BACK TO `ticks`, because frames_done could not tell two very different things apart:
        ; a frozen black border fits "the interrupt runs and the VM's loop is at frame 0" just
        ; as well as "the interrupt is dead". ticks is bumped by the ISR itself, so a cycling
        ; border means the interrupt lives and a frozen one means it does not.
        ld      a, (ticks)
        out     ($FE), a
    ENDIF
        ld      a, (autoplay)
        or      a
        ret     z

        ; has the frame moved on since the last time?
        ld      hl, (CTL + $08)         ; CTL_FRAMES_DONE
        ld      de, (auto_seen)
        or      a
        sbc     hl, de
        jr      z, .settled
        ld      hl, (CTL + $08)
        ld      (auto_seen), hl

        ld      hl, (auto_400)
        inc     hl
        ld      de, 400
        or      a
        sbc     hl, de
        jr      nz, .keep400
        ld      hl, -400                ; it reached 400: wrap to zero
.keep400:
        add     hl, de
        ld      (auto_400), hl

        ld      hl, auto_47
        inc     (hl)
        ld      a, (hl)
        cp      47
        jr      c, .settled
        ld      (hl), 0

.settled:
        ; The direction, as three ordered thresholds. ALL THREE ARE ABOVE 255 and the counter
        ; never reaches 400, so the high byte is 0 or 1 and only the low byte ever needs
        ; comparing - which turns three 16-bit subtractions into three `cp`. `ld a,n` does not
        ; touch the flags, so the value being loaded between the compare and the branch is
        ; free.
        ld      hl, (auto_400)
        ld      a, h
        or      a
        ld      a, M_RIGHT
        jr      z, .have_dir            ; under 256, so under 260
        ld      a, l
        cp      260 - 256
        ld      a, M_RIGHT
        jr      c, .have_dir
        ld      a, l
        cp      300 - 256
        ld      a, M_UP
        jr      c, .have_dir
        ld      a, l
        cp      330 - 256
        ld      a, M_LEFT
        jr      c, .have_dir
        xor     a
.have_dir:
        ld      (in_mask), a

        ld      a, (auto_47)
        cp      6
        ld      a, 0
        jr      nc, .no_fire
        inc     a
.no_fire:
        ld      (in_button), a
        ret

;-----------------------------------------------------------------------------
; l2_display - make Layer 2 visible, once, at boot.
;
; In MMU6 rather than resident because the resident block has three bytes left and this needs
; twelve; MMU6 is never remapped, so a call into it is always valid.
;
; NR_L2_CFG = 0 is 256x192 at 8bpp, which is what decision 1 chose and what every harness sets.
; $123B is WRITE-ONLY on this machine - the project learned that when it tried to read it back -
; so bit 1 is written blind and cannot be verified from the port. `make check-screen` asks the
; emulator instead.
;
; NR_L2_BANK is also set here for the page pg_ptr2 starts on, so the first frame has somewhere
; real to show before aw_blit gets round to setting it.
;-----------------------------------------------------------------------------
;-----------------------------------------------------------------------------
; show_err - say out loud that a resource failed to load, instead of halting in the dark.
;
; `.ready` tests err and, if the fixed load or the part setup failed, jumps straight to .stop -
; which sets `done`, disables interrupts and spins. On a checker that is fine, because the
; checker reads err over ZRCP. TO A PERSON IT IS INDISTINGUISHABLE FROM A CRASH: a black screen,
; no input, and the zxnDMA still streaming whatever was last in the ring, because it is
; autonomous and the `di` only stops the interrupt that was refilling it.
;
; The BORDER is the one thing that shows regardless of Layer 2, its palette, or whether anything
; was ever drawn - so it is what a first failure should speak through.
;
;     BLUE   the boot got as far as setting the display up
;     RED    a resource did not load; err is non-zero
;-----------------------------------------------------------------------------
show_err:
        ld      a, 2                    ; red
        out     ($FE), a
        jp      boot_stop

    IFDEF DIAG_BORDER
;-----------------------------------------------------------------------------
; The diagnostic block, and it has to dodge VEC_TRAMP.
;
; The gap between the leaf log ($CEB9) and the stack floor ($CF00) is 71 bytes - but the IM2
; TRAMPOLINE sits in the middle of it at $CECE, where install_im2 writes `JP isr`. The first
; version of this put diag_palette at $CEBC and ran straight through it. It worked only because
; the palette is written before install_im2 rewrites those three bytes: luck, not design. The
; two halves now sit either side of the trampoline, with assertions that say so.
;-----------------------------------------------------------------------------
        ORG     $CEBC                   ; 18 bytes, up to the trampoline
diag_enter_c:
        ld      a, 7                    ; white, the instant before the C is entered
        out     ($FE), a
        jp      CC_ORG                  ; a tail call: CC_ORG's ret returns to the boot path
        ASSERT $ <= VEC_TRAMP

        ORG     VEC_TRAMP + 3           ; 47 bytes, past it
diag_palette:
        nextreg NR_PAL_CTRL, PAL_SEL_L2
        nextreg NR_PAL_INDEX, 0
        ld      b, 16
        ld      c, 17                   ; entry 0 is NOT black either, so even a cleared page
                                        ; shows as a colour rather than as nothing
.one:
        ld      a, c
        nextreg NR_PAL_VALUE, a
        xor     a
        nextreg NR_PAL_VALUE, a
        ld      a, c
        add     a, 17
        ld      c, a
        djnz    .one
        ret
        ASSERT $ <= STACK_CODE
        DISPLAY "> the diagnostic block at ", /H, diag_enter_c, ", palette at ", /H, diag_palette
    ENDIF

l2_display:
        ld      a, 1                    ; blue: we got this far
        out     ($FE), a
        nextreg NR_TURBO, 3                         ; 28 MHz - folded in from the boot path,
                                                    ; which had three resident bytes left and
                                                    ; needed three for the call. Same order.
        nextreg NR_L2_CFG, 0                        ; 256x192, 8bpp
        nextreg NR_L2_BANK, L2_BASE_BANK + 2 * 3    ; pg_ptr2 starts at 2
        ld      bc, L2_PORT
        ld      a, L2_VISIBLE
        out     (c), a
    IFDEF DIAG_BORDER
        call    diag_palette
    ENDIF
        ret

        EXPORT autoplay
autoplay:   db 0            ; non-zero runs the probe's synthetic player
        EXPORT auto_seen
auto_seen:  dw 0            ; the frame number the counters were last advanced on
        ; EXPORTED so a gate can check the ARITHMETIC rather than the outcome. Waiting for the
        ; synthetic player to walk into something and die is a poor test: the probe's cycle is
        ; 400 frames and the machine reaches about 370 in a minute, so the signature that would
        ; prove it works never appears inside a reasonable run.
        EXPORT auto_400
auto_400:   dw 0
        EXPORT auto_47
auto_47:    db 0

        DISPLAY "> the synthetic player at ", /H, auto_input, " ending ", /H, $
        ASSERT $ <= PART_CODE

        ; THREE WRAP TESTS IN mix_block COMPARE ONLY THE HIGH BYTE, so the ring's end must be
        ; page-aligned. It is, and now it has to stay so.
        ASSERT (RING_END & $FF) == 0
        ASSERT RING_ADDR + RING_LEN <= VOLTAB
        ASSERT VOLTAB + 256 <= VOICES
        ASSERT VOICES + V_SIZE * 4 <= PART_CODE
        ASSERT VOLTAB_QUIET + 256 <= $E000
        ; the vector table and its trampoline, in the gap the expected stream leaves
        ; EVERY small block asserted, because STR_BLOCK sat inside DRAW_LOG's 200 bytes
        ; for three commits and only escaped notice because the two probe paths that use
        ; them never run together.
        ASSERT IN_BLOCK    >= RES_TABLE_AT + RES_COUNT + RES_COUNT * 4
        ASSERT DRAW_BLOCK  >= IN_BLOCK + 12
        ASSERT STR_BLOCK   >= DRAW_BLOCK + 10
        ASSERT MUS_ORDER_AT >= STR_BLOCK + 16
        ASSERT SND_BLOCK   >= MUS_BLOCK + 4
        ASSERT NOTE_CODE   >= SND_BLOCK + 4
        ASSERT SND_FREQ    >= VEC_TABLE + 257
        ASSERT SND_FREQ + 80 <= VEC_TRAMP
        ASSERT MUS_INSTR_AT >= MUS_ORDER_AT + $80
        ASSERT INTERP_AT    >= MUS_INSTR_AT + 30
        ASSERT VEC_TABLE   >= MUS_INSTR_AT + 30
        ASSERT VEC_TRAMP   >= VEC_TABLE + 257
        ASSERT STACK_CODE >= VEC_TRAMP + 3
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
        ; AGAINST CC_TOP, NOT AGAINST THIS. The C's BSS lives ABOVE the image sjasmplus
        ; measures, so `$ <= MUSIC_CODE` here passed while the music code sat inside the C's
        ; variables - the VM dispatched thirteen records and stopped, nothing drew, and no
        ; assertion fired. tools/mkexp.py emits the real top from the link map now.
        ASSERT $ <= MUSIC_CODE          ; the C's IMAGE must not reach the music code
        ASSERT CC_TOP <= MUSIC_CODE     ; and neither must its variables
        DISPLAY "> the C is ", /D, $ - CC_ORG, " bytes at ", /H, CC_ORG
        ASSERT $ < VEC_TABLE

        SAVENEX OPEN "build/aw.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
