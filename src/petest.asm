;-----------------------------------------------------------------------------
; E1 and E2: frame pacing, and the input mapping.
;
; Both in assembly and both driven from memory this file owns, so the checker only
; ever pokes and reads addresses fixed by construction. That is deliberate after
; Gate D: the virtual machine's trace had to cross from C into the checker and that
; channel cost more than the VM did.
;
; PACING. `op_blitFramebuffer` is allowed vmVariables[0xFF] * 20 ms and the
; subtraction in the reference (vm.cpp:283-287) is the part that matters: the pause
; is a DEADLINE, not a delay. A frame that took 60 ms of an 80 ms budget waits 20.
; A port that waits the full 80 runs at two thirds speed and looks correct doing it.
; Here the clock is the 50 Hz frame interrupt, so the arithmetic is in refreshes.
;
; INPUT. inp_updatePlayer (vm.cpp:586-638) maps a direction mask and one button
; into six variables, and it has two quirks that only reading the source gives you:
; left and right BOTH assign, so pressing both gives left; and 0xE5 is assigned and
; then overwritten if up is held, which is not the same as what 0xFB gets. The mask
; is poked rather than read from the keyboard, because what is under test is the
; mapping - the key matrix is a separate and much duller question.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

NR_TURBO        EQU $07

DIR_LEFT        EQU 1
DIR_RIGHT       EQU 2
DIR_UP          EQU 4
DIR_DOWN        EQU 8

; IM 2, with the vector table and its trampoline high in RAM. IM 1 would put the
; handler at $0038 in ROM, which cannot coexist with paging RAM over the bottom 16K
; - which the virtual machine does for its bytecode window - so the port needs IM 2
; anyway.
;
; The table must be 257 bytes, not 256: the Z80 reads the vector from I<<8|databus
; AND the byte after it, so a databus of $FF reads the last table byte and the one
; past the end. Filling 256 and stopping leaves that second byte to chance.
;
; And it must not be in the code. The first version put it at $8100 and filled 256
; bytes over this program's own instructions, which presented as the machine simply
; never finishing.
VEC_FILL        EQU $BD                 ; every table entry, so the vector is $BDBD
VEC_TABLE       EQU $BC00
VEC_TRAMP       EQU (VEC_FILL << 8) | VEC_FILL

        ORG $8000
        jp      start

isr:
        push    af
        push    hl
        ld      hl, (ticks)
        inc     hl
        ld      (ticks), hl
        pop     hl
        pop     af
        ei
        reti

start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3

        ld      a, VEC_TABLE >> 8
        ld      i, a
        ld      hl, VEC_TABLE
        ld      de, VEC_TABLE + 1
        ld      bc, 256                 ; 256 copies after the first: 257 bytes
        ld      (hl), VEC_FILL
        ldir
        ld      hl, VEC_TRAMP
        ld      (hl), $C3               ; JP isr
        inc     hl
        ld      (hl), isr & $FF
        inc     hl
        ld      (hl), isr >> 8
        im      2
        ei

        ld      a, $5A
        ld      (ready), a

main:
        ld      a, (go)
        or      a
        jr      z, main
        xor     a
        ld      (go), a

        ld      a, (what)
        dec     a
        jp      z, do_input
        dec     a
        jp      z, do_pace
        jr      .done
.done:
        ld      a, $5A
        ld      (done), a
        jr      main

;-----------------------------------------------------------------------------
; do_input - map (in_mask, in_button) into the six variables, exactly as
; inp_updatePlayer does, in its order.
;-----------------------------------------------------------------------------
do_input:
        ld      hl, 0
        ld      (v_lr), hl              ; lr = 0
        ld      (v_ud), hl              ; ud = 0
        ld      a, 0
        ld      (v_mask), a             ; m = 0

        ld      a, (in_mask)
        ld      c, a

        bit     1, c                    ; DIR_RIGHT
        jr      z, .no_right
        ld      hl, 1
        ld      (v_lr), hl
        ld      a, (v_mask)
        or      1
        ld      (v_mask), a
.no_right:
        bit     0, c                    ; DIR_LEFT - assigns too, so both gives left
        jr      z, .no_left
        ld      hl, -1
        ld      (v_lr), hl
        ld      a, (v_mask)
        or      2
        ld      (v_mask), a
.no_left:
        bit     3, c                    ; DIR_DOWN
        jr      z, .no_down
        ld      hl, 1
        ld      (v_ud), hl
        ld      a, (v_mask)
        or      4
        ld      (v_mask), a
.no_down:
        ; vars[0xE5] = ud, BEFORE the up test, and then overwritten by it
        ld      hl, (v_ud)
        ld      (var_E5), hl

        bit     2, c                    ; DIR_UP, tested twice in the original
        jr      z, .no_up
        ld      hl, -1
        ld      (var_E5), hl
        ld      hl, -1
        ld      (v_ud), hl
        ld      a, (v_mask)
        or      8
        ld      (v_mask), a
.no_up:
        ld      hl, (v_ud)
        ld      (var_FB), hl
        ld      hl, (v_lr)
        ld      (var_FC), hl
        ld      a, (v_mask)
        ld      l, a
        ld      h, 0
        ld      (var_FD), hl

        ld      hl, 0
        ld      (var_FA), hl
        ld      a, (in_button)
        or      a
        jr      z, .no_fire
        ld      hl, 1
        ld      (var_FA), hl
        ld      a, (v_mask)
        or      $80
        ld      (v_mask), a
.no_fire:
        ld      a, (v_mask)
        ld      l, a
        ld      h, 0
        ld      (var_FE), hl
        jp      main.done

;-----------------------------------------------------------------------------
; do_pace - run (pace_n) frames, each asking for (pace_slices) refreshes, and
; record the tick at every frame edge so the checker can measure the intervals.
;
; The deadline is carried forward, not restarted: that is what makes a frame which
; overran lose time rather than push everything after it back.
;-----------------------------------------------------------------------------
do_pace:
        ld      hl, (ticks)
        ld      (deadline), hl
        ld      hl, pace_log
        ld      (pace_at), hl
        ld      a, (pace_n)
        ld      b, a
.frame:
        push    bc

        ; simulate the frame's own work: (pace_work) refreshes of it
        ld      a, (pace_work)
        or      a
        jr      z, .no_work
        ld      c, a
        ld      hl, (ticks)
        ld      de, 0
        ld      e, c
        add     hl, de
.spin:  ld      de, (ticks)
        ld      a, d
        cp      h
        jr      c, .spin
        jr      nz, .worked
        ld      a, e
        cp      l
        jr      c, .spin
.worked:
.no_work:
        ; the deadline advances by the requested pause whatever happened
        ld      hl, (deadline)
        ld      a, (pace_slices)
        ld      e, a
        ld      d, 0
        add     hl, de
        ld      (deadline), hl

        ; wait for it, unless it has already passed - which is how an overrunning
        ; frame loses time instead of drifting
.wait:  ld      hl, (ticks)
        ld      de, (deadline)
        or      a
        sbc     hl, de
        jr      nc, .due                ; ticks >= deadline
        jr      .wait
.due:
        ld      hl, (ticks)
        ld      de, (pace_at)
        ex      de, hl
        ld      (hl), e
        inc     hl
        ld      (hl), d
        inc     hl
        ld      (pace_at), hl

        pop     bc
        dec     b
        jp      nz, .frame
        jp      main.done

;-----------------------------------------------------------------------------
        EXPORT ready
ready:      db 0
        EXPORT go
go:         db 0
        EXPORT done
done:       db 0
        EXPORT what
what:       db 0            ; 1 = the input mapping, 2 = pacing
        EXPORT ticks
ticks:      dw 0

        EXPORT in_mask
in_mask:    db 0
        EXPORT in_button
in_button:  db 0
v_lr:       dw 0
v_ud:       dw 0
v_mask:     db 0
        EXPORT var_E5
var_E5:     dw 0
        EXPORT var_FA
var_FA:     dw 0
        EXPORT var_FB
var_FB:     dw 0
        EXPORT var_FC
var_FC:     dw 0
        EXPORT var_FD
var_FD:     dw 0
        EXPORT var_FE
var_FE:     dw 0

        EXPORT pace_n
pace_n:     db 0            ; how many frames
        EXPORT pace_slices
pace_slices: db 0           ; the pause each asks for, in refreshes
        EXPORT pace_work
pace_work:  db 0            ; refreshes of work each frame does before pacing
deadline:   dw 0
pace_at:    dw 0
        EXPORT pace_log
pace_log:   ds 2 * 64       ; the tick at each frame edge

        ; Everything above must stay clear of the vector table and its trampoline.
        ASSERT $ < VEC_TABLE
        SAVENEX OPEN "build/petest.nex", $8000, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
