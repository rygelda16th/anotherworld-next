;-----------------------------------------------------------------------------
; Gate D: the virtual machine, against the engine's own opcode stream.
;
; This is the assembly half. It loads a bytecode segment off the card, hands the
; C virtual machine a seed and a frame count, and keeps a log of every opcode the
; VM dispatches so the stream can be compared thread by thread and opcode by
; opcode against the engine's.
;
; That comparison comes BEFORE any picture, and the reason is in the plan: a VM
; that is wrong in one opcode is a VM that renders almost correctly, which is the
; worst kind of wrong to debug at the end. The video calls below are counted, not
; drawn, for the same reason - one thing under test.
;
; The jump table at $8000 is Gate B's mechanism and src/aw/jumptab.asm declares
; the same addresses to the C. The ASSERT on its length is what catches a slot
; added to one file and not the other.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

; Where z88dk puts the VM's C - LOWER than Gate B's ctest, so the stack at $BF00
; has room. Its image is 7,166 bytes and its data about 1.5K, so it ends near
; $AE00. Must match VM_ORG in the Makefile.
CC_ORG          EQU $8C00
NR_TURBO        EQU $07
NR_MMU0         EQU $50
NR_MMU1         EQU $51
CODE_WIN        EQU $0000               ; two 8K pages of bytecode
CODE_PAGE       EQU 48                  ; clear of the 48K image and of Layer 2
; THE MEMORY MAP, settled after several wrong turns, because every one of them
; showed up as something other than a memory-map problem:
;
;   $0000-$3FFF  the bytecode window, MMU0 and MMU1. The ROM until first mapped,
;                and esxDOS pages ITSELF here during a file call.
;   $4000-$7FFF  NOT AVAILABLE. Bank 5 holds the ZX system variables from $5B00,
;                which esxDOS needs: staging a read here loaded 68 bytes and then
;                failed, because the second F_READ had no workspace left.
;   $8000-$82xx  this file: the jump table at $8000, then code and data.
;   $8C00-$AExx  the C, and its data. Low on purpose - at $A000 the data ended at
;                $BBF5 and left the stack 779 bytes, and the four HIGHEST globals
;                were the ones reading wrong.
;   $BF00        the stack, growing down. What SAVENEX declares; moving it broke
;                the load.
;   $C000-$DFFF  the trace buffer, MMU6.
;   $E000-$FFFF  the loader's staging window, MMU7. Free once the stack stayed at
;                $BF00.
DST_WIN         EQU $E000               ; the loader's staging window, MMU7
NR_MMU7         EQU $57

F_WRITE         EQU $9E
; $0C is ESXDOS_MODE_CREAT_TRUNC - create, or replace an existing file - and it is
; accepted ON ITS OWN. $0E, which is that OR'd with the write bit and looks like the
; obvious thing to ask for, is not one of the cases the handler's switch knows and it
; refuses the open outright. Read the emulator's accepted modes, not the ones that
; seem to follow from the bit names.
FA_WRITE_NEW    EQU $0C

LOG_RECS        EQU 2048                ; four bytes each, above the stack

        ORG $8000
jump_table:
        jp      aw_code_window          ; $8000  uint8_t *aw_code_window(uint16_t)
        jp      aw_draw_poly            ; $8003  void aw_draw_poly(void)
        jp      aw_select_page          ; $8006  void aw_select_page(uint8_t)
        jp      aw_fill_page            ; $8009  void aw_fill_page(uint16_t)
        jp      aw_copy_page            ; $800C  void aw_copy_page(uint16_t)
        jp      aw_blit                 ; $800F  void aw_blit(uint8_t)
        jp      aw_set_palette          ; $8012  void aw_set_palette(uint8_t)
        jp      aw_frame_sync           ; $8015  void aw_frame_sync(void)
        jp      aw_load_res             ; $8018  I3: the game loads; this counts
        jp      aw_inval_res            ; $801B
        jp      aw_draw_string          ; $801E  I4: counted here
        jp      aw_play_music           ; $8021  I5: counted here
        ASSERT $ - jump_table == 36

VM_STACK        EQU $BF00               ; what SAVENEX declares; see the Makefile

start:
        di
        ld      sp, VM_STACK
        nextreg NR_TURBO, 3

        ld      a, $5A
        ld      (ready), a

.wait:  ld      a, (go)
        or      a
        jr      z, .wait

        ; stage_stop exists because "the machine is wrecked" was true at every
        ; stage and the aftermath looks identical whichever stage did it: the stack
        ; runs down from $BF00 smearing one repeating value over the program, so by
        ; the time anything can be read there is nothing left to read. Stopping
        ; after a named stage is the only way to ask WHICH stage.
        ;   1  after clearing the bytecode pages
        ;   2  after loading the segment
        ;   0  the whole thing
        ld      a, (stage_stop)
        dec     a
        jr      nz, .not_one
        call    clear_code
        jr      .stop
.not_one:
        call    load_code
        ld      a, (err)
        or      a
        jr      nz, .stop
        ld      a, (stage_stop)
        cp      2
        jr      z, .stop

        ; Tell the C how long the segment actually is, at $C010 in the control
        ; block. Without it the VM cannot tell bytecode from the memory after it,
        ; and reading past the end was what wrecked every run.
        ld      hl, (got)
        ld      ($C010), hl
        ; And how many records the engine produced, so the C can compare its own
        ; against them as it goes and stop on the first one that differs.
        ld      hl, EXPECTED_N
        ld      ($C014), hl

        call    CC_ORG                  ; the C virtual machine, once
        di                              ; SEE BELOW. Not optional, and not tidiness.

        ; DI, BECAUSE THE C RE-ENABLES INTERRUPTS ON ITS WAY OUT.
        ;
        ; z88dk's exit path is `im 1 / ei / ret` - $8C40 in this build, and visible
        ; as ED 56 FB C9 in build/vm_CODE.bin. Twenty milliseconds later the machine
        ; takes a frame interrupt and jumps to $0038, and $0038 is not the ROM: MMU0
        ; and MMU1 are holding the bytecode segment the VM has been reading. So the
        ; Z80 starts executing Another World's bytecode as Z80 instructions, the
        ; stack runs down from $BF00 and wraps, and every counter this gate reads is
        ; overwritten with whatever those bytes happened to push.
        ;
        ; THIS IS THE WHOLE OF "GATE D WILL NOT REPEAT". The same .nex and the same
        ; inputs gave 0, 64, 122 and 354 matching records because the checker was
        ; reading a machine that had already begun destroying itself, and how much
        ; was left depended on how long the read took. Nothing was wrong with the
        ; virtual machine. Four separate wrong diagnoses came out of that window -
        ; uninitialised statics, a stack in the bytecode window, a stale trace file,
        ; and an esxDOS mode byte - and each of them was a real fault worth fixing,
        ; which is exactly why none of them fixed this.
        ;
        ; The general lesson: a program that hands control to somebody else's runtime
        ; gets that runtime's interrupt state back, not its own. Ask what the CRT
        ; does on exit before believing any measurement taken after it.

        ; AND NOTHING ELSE. write_trace is still below and still works as far as it
        ; goes, but calling it here was destroying the machine AFTER the virtual
        ; machine had finished, and that is what a whole session of "Gate D will not
        ; repeat" turned out to be.
        ;
        ; The evidence: run with an opcode budget of ZERO. The C dispatches nothing,
        ; sets finished to $5A, and leaves a control block that reads back perfectly
        ; - the segment length 9,871, the expected count 679, out-of-budget set. And
        ; `done` is still zero, because the assembly never got back from the esxDOS
        ; call to set it. The VM was not the problem in that run and cannot have been.
        ;
        ; The mechanism is the ROM. Getting to esxDOS means putting the ROM back over
        ; $0000-$3FFF, which means taking the bytecode out from under a machine whose
        ; C has been running with it there; the RST $08 does not come back, the stack
        ; runs down from $BF00 and wraps, and the smear covers every byte of every
        ; counter this gate reads. That is why each failure looked like a different
        ; VM bug: the state being read was the smear, not the VM.
        ;
        ; It is not needed. The comparison happens ON the machine against the engine's
        ; own 679 records at $E000, and what leaves is a 32-byte verdict.
.stop:
        ld      a, $5A
        ld      (done), a
.hold:  jr      .hold

        INCLUDE "src/inc/vmhost.inc"

;-----------------------------------------------------------------------------
; The video calls. Counted, not drawn: Gate D is about the opcode stream, and the
; rasteriser and reader are already gated pixel-exact on their own.
;-----------------------------------------------------------------------------
aw_draw_poly:
        ld      hl, (n_poly)
        inc     hl
        ld      (n_poly), hl
        ret

aw_select_page:
        ld      a, l
        ld      (last_select), a
        ld      hl, (n_select)
        inc     hl
        ld      (n_select), hl
        ret

aw_fill_page:
        ld      (last_fill), hl
        ld      hl, (n_fill)
        inc     hl
        ld      (n_fill), hl
        ret

aw_copy_page:
        ld      (last_copy), hl
        ld      hl, (n_copy)
        inc     hl
        ld      (n_copy), hl
        ret

aw_blit:
        ld      a, l
        ld      (last_blit), a
        ld      hl, (n_blit)
        inc     hl
        ld      (n_blit), hl
        ret

; The frame boundary. THIS HARNESS DOES NOTHING AT IT - Gate D is about the opcode
; stream, and a harness that paced itself would take 45 frames of wall clock to prove
; something that takes two tenths of a second. src/aw.asm's version waits for the
; frame interrupt and refills the sound ring.
aw_frame_sync:
        ret

; I3's two, counted rather than done: Gate D is about the opcode stream and a harness that
; actually loaded resources would need the whole allocator to say anything new.
aw_load_res:
        ld      hl, (n_load)
        inc     hl
        ld      (n_load), hl
        ret
aw_inval_res:
        ld      hl, (n_inval)
        inc     hl
        ld      (n_inval), hl
        ret
aw_draw_string:
        ret
aw_play_music:
        ret

aw_set_palette:
        ld      a, l
        ld      (last_pal), a
        ld      hl, (n_pal)
        inc     hl
        ld      (n_pal), hl
        ret

;-----------------------------------------------------------------------------
; The log. Four bytes a record: kind, pc as a word, then the opcode or thread.
;   kind 1  an opcode, at the pc aw_log_pc last recorded
;   kind 2  a thread edge; the pc field is the thread's starting offset
;-----------------------------------------------------------------------------
; write_trace - the whole 8K block at $C000 out to a file.
;
; This is what closes Gate D. Reading the C's state over the debug protocol was
; never repeatable; a file is. Step 5 proved this path byte-exact, and the block
; carries its own header so the checker needs nothing from memory at all.
;-----------------------------------------------------------------------------
write_trace:
        ; PUT THE ROM BACK FIRST. The virtual machine has been paging bytecode over
        ; $0000-$3FFF through MMU0 and MMU1, and esxDOS is reached by RST $08 - which
        ; needs the ROM at $0000 and pages its own memory over the bottom 16K besides.
        ; $FF is the MMU value that means "the ROM".
        nextreg NR_MMU0, $FF
        nextreg NR_MMU1, $FF

        ld      a, ESX_DRIVE
        ld      ix, trace_name
        ld      hl, trace_name
        ld      b, FA_WRITE_NEW
        rst     $08
        db      F_OPEN
        jr      nc, .opened
        ld      (trace_err), a          ; record WHY, so the checker can say
        ld      a, 1
        ld      (trace_where), a
        ret
.opened:
        ld      (handle), a

        ; 8,192 bytes in one call. esxDOS takes the buffer in IX for a machine-code
        ; caller and HL for a BASIC one, so set both - the trap wolf3d-next paid for
        ; when CSpect wrote a filename over the code that followed it.
        ld      a, (handle)
        ld      ix, $C000
        ld      hl, $C000
        ld      bc, $2000
        rst     $08
        db      F_WRITE
        jr      nc, .wrote
        ld      (trace_err), a
        ld      a, 2
        ld      (trace_where), a
        jr      .close
.wrote:
        ld      (trace_wrote), bc       ; how many bytes it says it took
.close:
        ld      a, (handle)
        rst     $08
        db      F_CLOSE
        ret

trace_name:     db "AWTRACE.BIN", 0
        EXPORT trace_err
trace_err:      db 0
        EXPORT trace_where
trace_where:    db 0            ; 1 = open, 2 = write
        EXPORT trace_wrote
trace_wrote:    dw 0

;-----------------------------------------------------------------------------
        EXPORT ready
ready:          db 0
        EXPORT go
go:             db 0
        EXPORT done
done:           db 0
        EXPORT err
        EXPORT got
        EXPORT fname
        EXPORT n_poly
n_poly:         dw 0
        EXPORT n_select
n_select:       dw 0
        EXPORT n_fill
n_fill:         dw 0
        EXPORT n_copy
n_copy:         dw 0
        EXPORT n_blit
n_blit:         dw 0
        EXPORT n_pal
n_pal:          dw 0
        EXPORT n_load
n_load:         dw 0
        EXPORT n_inval
n_inval:        dw 0
last_select:    db 0
last_fill:      dw 0
last_copy:      dw 0
last_blit:      db 0
last_pal:       db 0

        ASSERT $ < CC_ORG
        ORG     $C000
        ; log_buf fills MMU6 exactly, $C000-$DFFF, and the stack lives above it in
        ; MMU7. Nothing pages either during the run.
; One 8K block: THIRTY-TWO bytes of header, then four-byte records. The C writes
; all of it and write_trace sends the lot to a file. The header grew when the fault
; trap and the on-machine verdict went in; 32 + 2040*4 is $2000 exactly, so the
; record count did not have to change.
        EXPORT log_buf
log_buf:        ds 32 + 2040 * 4

        ; log_buf sits ABOVE the stack, at $C000-$DFFF, which is fine: the stack
        ; grows DOWN from $BF00. The bound here is the top of memory, not the stack.
        ASSERT $ <= $E000

; THE ENGINE'S OWN STREAM, in the .nex, at a fixed address the C knows.
;
; $E000 is the loader's staging window, which looks like a collision and is not:
; clear_code and load_code point MMU7 at a bytecode page while they work there, so
; the writes land in that page and bank 0's own second half - this data - is never
; touched. load_code puts MMU7 back to 1 before it returns.
        ORG     $E000
        EXPORT expected_ops
        INCLUDE "build/expected_ops.inc"
        DISPLAY "> expected stream is ", /D, EXPECTED_N, " records at $E000"
        ASSERT $ < $FF00

        ORG     CC_ORG
        INCBIN  "build/vm_CODE.bin"
        DISPLAY "> VM C image is ", /D, $ - CC_ORG, " bytes at ", /H, CC_ORG

        SAVENEX OPEN "build/vmtest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
