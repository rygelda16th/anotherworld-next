; The VM's host routines, shared by the harness and the game.
;
; Extracted from src/vmtest.asm, every line of which Gate D exercises: the bytecode
; window that make check-boot slides over a 9,871-byte segment 763 records deep, the
; loader that step 5 proved byte-exact over seven files up to 65,230 bytes, and the
; page clear that made Gate D repeatable.
;
; THE INCLUDER MUST DEFINE:
;   CODE_PAGE   the first 8K page of the bytecode window's eight
;   CODE_WIN    where the window appears, $0000 in both programs so far
;   DST_WIN     the loader's staging window, and the slot NR_MMU7 maps
;
; It must also EXPORT whichever of err, got and fname its checker reads.
;
; The esxDOS constants and the loader's variables are HERE rather than in each
; program, because they are the loader's and splitting them was what made the
; first build of src/aw.asm fail on six undefined labels.

F_OPEN          EQU $9A
F_CLOSE         EQU $9B
F_READ          EQU $9D
FA_READ         EQU $01
ESX_DRIVE       EQU '*'

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
;-----------------------------------------------------------------------------
; clear_code - every page the bytecode window can reach, set to (code_fill).
;
; This is here because Gate D would not REPEAT: the same .nex, the same seed, the
; same frame count, and 0, 64, 122 and 354 trace records on four runs. smartload
; does not clear the machine's RAM, so whatever the previous run left behind was
; still there - and the bytecode window can reach eight 8K pages while the segment
; under test fills barely two of them. Everything past the segment's last byte was
; last run's rubbish, and it differed every time.
;
; The fill byte is a variable rather than a constant so the experiment can be run
; the other way round: if the VM's behaviour changes when the fill changes, then it
; is READING past the end of the segment, which is a fault in the VM and not in the
; memory it was handed.
;-----------------------------------------------------------------------------
clear_code:
        ld      a, CODE_PAGE
        ld      b, 8                    ; the whole 64K the window can address
.page:
        nextreg NR_MMU7, a
        push    af
        push    bc
        ld      hl, DST_WIN
        ld      de, DST_WIN + 1
        ld      bc, $2000 - 1
        ld      a, (code_fill)
        ld      (hl), a
        ldir
        pop     bc
        pop     af
        inc     a
        djnz    .page
        nextreg NR_MMU7, 1
        ret

        EXPORT code_fill
code_fill:      db 0
        EXPORT stage_stop
stage_stop:     db 0

;-----------------------------------------------------------------------------
; load_code - reads (fname) into banked pages from CODE_PAGE.
;-----------------------------------------------------------------------------
load_code:
        xor     a
        ld      (err), a
        ld      hl, 0
        ld      (got), hl
        call    clear_code

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


; The loader's own state. EXPORTed by whichever program's checker reads it.
fname:      ds 34                       ; poked by the checker, or set by the game
handle:     db 0
cur_page:   db 0
err:        db 0
got:        dw 0
