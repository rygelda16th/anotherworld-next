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

F_OPEN          EQU $9A
F_CLOSE         EQU $9B
F_READ          EQU $9D
F_WRITE         EQU $9E
FA_WRITE_NEW    EQU $0E                 ; write, create, truncate
FA_READ         EQU $01
ESX_DRIVE       EQU '*'

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
        ASSERT $ - jump_table == 21

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

        call    load_code
        ld      a, (err)
        or      a
        jr      nz, .stop

        call    CC_ORG                  ; the C virtual machine, once
        call    write_trace             ; and the whole block out to a file
.stop:
        ld      a, $5A
        ld      (done), a
.hold:  jr      .hold

;-----------------------------------------------------------------------------
; aw_code_window - HL = a bytecode offset. Maps the two 8K pages covering it and
; returns HL as an address inside CODE_WIN.
;
; Same shape as the polygon reader's window, and for the same reason: a thread's
; program counter is a flat 16-bit offset and the largest bytecode segment in the
; game is 62,683 bytes, so it cannot be mapped linearly into a 64K space that also
; holds this code.
;-----------------------------------------------------------------------------
aw_code_window:
        ld      a, h
        rlca
        rlca
        rlca
        and     7                       ; H >> 5 = off >> 13
        add     a, CODE_PAGE
        nextreg NR_MMU0, a
        inc     a
        nextreg NR_MMU1, a
        ld      a, h
        and     $1F
        add     a, CODE_WIN >> 8
        ld      h, a
        ret

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
;-----------------------------------------------------------------------------
; load_code - reads (fname) into banked pages from CODE_PAGE.
;-----------------------------------------------------------------------------
load_code:
        xor     a
        ld      (err), a
        ld      hl, 0
        ld      (got), hl

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
        ld      a, CODE_PAGE
        ld      (cur_page), a
.next:
        ; esxDOS pages ITSELF over the bottom 16K during a file call, so the
        ; destination cannot be CODE_WIN. Read into a window at $C000 and the
        ; page lands where the VM will look for it.
        ld      a, (cur_page)
        nextreg NR_MMU7, a
        ld      a, (handle)
        ld      ix, DST_WIN
        ld      hl, DST_WIN
        ld      bc, $2000
        rst     $08
        db      F_READ
        jr      nc, .ok
        ld      (err), a
        jr      .close
.ok:
        ld      a, b
        or      c
        jr      z, .close
        ld      hl, (got)
        add     hl, bc
        ld      (got), hl
        ld      hl, cur_page
        inc     (hl)
        ld      a, b
        cp      $20
        jr      nz, .close
        jr      .next
.close:
        ld      a, (handle)
        rst     $08
        db      F_CLOSE
        ; Put $E000 back, so nothing downstream reads a bytecode page there.
        nextreg NR_MMU7, 1
        ret

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
err:            db 0
        EXPORT got
got:            dw 0
        EXPORT fname
fname:          ds 32
handle:         db 0
cur_page:       db 0
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
last_select:    db 0
last_fill:      dw 0
last_copy:      dw 0
last_blit:      db 0
last_pal:       db 0

        ASSERT $ < CC_ORG
        ORG     $C000
        ; log_buf fills MMU6 exactly, $C000-$DFFF, and the stack lives above it in
        ; MMU7. Nothing pages either during the run.
; One 8K block: sixteen bytes of header, then four-byte records. The C writes all
; of it and write_trace sends the lot to a file.
        EXPORT log_buf
log_buf:        ds 16 + 2040 * 4

        ; log_buf sits ABOVE the stack, at $C000-$DFFF, which is fine: the stack
        ; grows DOWN from $BF00. The bound here is the top of memory, not the stack.
        ASSERT $ < $FF00
        ORG     CC_ORG
        INCBIN  "build/vm_CODE.bin"
        DISPLAY "> VM C image is ", /D, $ - CC_ORG, " bytes at ", /H, CC_ORG

        SAVENEX OPEN "build/vmtest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
