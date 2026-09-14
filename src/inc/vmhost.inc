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
F_WRITE         EQU $9E
; $0C, not $0E: write + create + truncate. esxDOS takes $0E as something else and the open
; fails, which is a lesson this project has already paid for once.
FA_WRITE        EQU $0C
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
        ; A PATCHED IMMEDIATE, not a load. This runs on every bytecode fetch, so the ten extra
        ; T-states of reading the base out of memory would cost about 4% of a frame - and I6
        ; needs it to change, because a part's bytecode arrives through aw_load_res at whatever
        ; page the heap cursor had reached, not at the fixed CODE_PAGE the gates load into.
        ; aw_setup_part writes code_add + 1; the same trick the mixer uses for its increments.
        EXPORT code_add
code_add:
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
        ld      a, (ld_page)
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
; load_code - reads (fname) into eight banked pages from (ld_page).
;
; The destination is a VARIABLE because the game loads two segments, not one: a part is
; four resources (parts.cpp:14-28) and the bytecode and the cinematic data go into
; different pages behind different windows. The harness only ever loads bytecode, so
; ld_page starts at CODE_PAGE and it never notices.
;-----------------------------------------------------------------------------
;-----------------------------------------------------------------------------
; THE ESXDOS ENTRY POINT AND THE BYTECODE WINDOW WANT THE SAME 16K.
;
; RST $08 is a jump to $0008, and esxDOS only answers there because the divMMC pages
; itself in when the processor FETCHES from that address - which it can only do while
; the bottom 16K is ROM. vmhost.inc's code_add maps the bytecode segment over exactly
; that range (CODE_WIN is $0000) on every bytecode fetch, so the first load after the
; VM has fetched an opcode does not reach esxDOS at all: the RST lands in bytecode and
; the machine runs off into data, unwinding the stack as it goes.
;
; Measured, not reasoned. A CSpect plugin (tools/cspect/awprobe.cs) trapping execution of the
; low window caught it on the first instruction: PC $0008, MMU0=73, MMU1=74, and $876F
; on the stack - load_code's own RST, returning to a file that had never been opened.
; Nothing was wrong with the name, the handle or the card. The same fault is why the
; RST $18 trace only ever printed one character: DebugOut also wants MMU0 to be ROM.
;
; They live in vmhost.inc, next to the loader, so that every program that includes it
; gets them. Putting them in aw.asm alone assembled `call $0000` into the harnesses
; without a word of complaint - sjasmplus resolved the missing label to zero.
;-----------------------------------------------------------------------------
esx_rom:
        ; Reading a NextReg back needs it selected on $243B and read from $253B; the
        ; project already learned that $123B is write-only here, so nothing is assumed
        ; readable without checking it is. Both halves are saved: aw_blit's copy-mode
        ; fill borrows MMU0 alone, so MMU1 is not always MMU0 + 1.
        ld      bc, $243B
        ld      a, NR_MMU0
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      (esx_mmu0), a
        ld      b, $24
        ld      a, NR_MMU1
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      (esx_mmu1), a
        nextreg NR_MMU0, $FF            ; $FF is "whatever this slot maps by default",
        nextreg NR_MMU1, $FF            ; which for the bottom 16K is the ROM
        ret

esx_back:
        ld      a, (esx_mmu0)
        nextreg NR_MMU0, a
        ld      a, (esx_mmu1)
        nextreg NR_MMU1, a
        ret

esx_mmu0:   db 0
esx_mmu1:   db 0


load_code:
        xor     a
        ld      (err), a
        ld      hl, 0
        ld      (got), hl
        call    clear_code
        ; THE ROM HAS TO BE BACK OVER THE BOTTOM 16K FOR THE WHOLE CALL. See esx_rom.
        call    esx_rom

        ld      a, ESX_DRIVE
        ld      ix, fname
        ld      hl, fname
        ld      b, FA_READ
        rst     $08
        db      F_OPEN
        jr      nc, .opened
        ld      (err), a
        jr      .undo
.opened:
        ld      (handle), a
        ld      a, (ld_page)
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
.undo:
        jp      esx_back                ; and the bytecode window back over the ROM


; The loader's own state. EXPORTed by whichever program's checker reads it.
ld_page:    db CODE_PAGE                ; where the next load goes
fname:      ds 34                       ; poked by the checker, or set by the game
handle:     db 0
cur_page:   db 0
err:        db 0
got:        dw 0
