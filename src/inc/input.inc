; The input path: reading real hardware, and the mapping the reference performs on it.
;
; make check-pace proves the MAPPING over all 32 combinations, in inp_updatePlayer's
; own order - including the two oddities that make it worth sharing rather than
; rewriting: LEFT assigns rather than or-s, so left-and-right together reads as left,
; and UP is tested twice, writing variable $E5 before the test and again inside it.
;
; read_keys is the half that did not exist anywhere in this project until I1a. petest
; is HANDED its mask as a poked byte; nothing read a keyboard.
;
; THE INCLUDER MUST DEFINE nothing. The variables are here, and whichever program
; wants them EXPORTs them.

; The Spectrum keyboard, read at port $FE with the row selected by the high byte, a
; clear bit meaning pressed. Kempston is port $1F, a SET bit meaning pressed, which is
; why the two are accumulated with opposite senses.
;
;   O = left    P = right    Q = up    A = down    Space = fire
;
; and the Kempston joystick in parallel, so a joystick needs no second code path and
; H1 has only the physical wiring left to do.
ROW_QWERT       EQU $FB                 ; Q W E R T      Q is bit 0
ROW_ASDFG       EQU $FD                 ; A S D F G      A is bit 0
ROW_POIUY       EQU $DF                 ; P O I U Y      P is bit 0, O is bit 1
ROW_SPACE       EQU $7F                 ; Space Sym M N B    Space is bit 0
KEMPSTON_PORT   EQU $1F
K_RIGHT         EQU 0
K_LEFT          EQU 1
K_DOWN          EQU 2
K_UP            EQU 3
K_FIRE          EQU 4

; The mask do_input consumes: bit 0 left, bit 1 right, bit 2 up, bit 3 down.
M_LEFT          EQU 1
M_RIGHT         EQU 2
M_UP            EQU 4
M_DOWN          EQU 8

read_keys:
        ld      c, 0                    ; C accumulates the mask
        ld      e, 0                    ; E accumulates the button

        ld      a, ROW_POIUY
        in      a, ($FE)
        bit     1, a                    ; O
        jr      nz, .no_left
        set     0, c
.no_left:
        bit     0, a                    ; P
        jr      nz, .no_right
        set     1, c
.no_right:
        ld      a, ROW_QWERT
        in      a, ($FE)
        bit     0, a                    ; Q
        jr      nz, .no_up
        set     2, c
.no_up:
        ld      a, ROW_ASDFG
        in      a, ($FE)
        bit     0, a                    ; A
        jr      nz, .no_down
        set     3, c
.no_down:
        ld      a, ROW_SPACE
        in      a, ($FE)
        bit     0, a                    ; Space
        jr      nz, .no_fire
        ld      e, 1
.no_fire:
        ; and the joystick, whose bits are the other way up: SET means pressed
        in      a, (KEMPSTON_PORT)
        bit     K_LEFT, a
        jr      z, .j1
        set     0, c
.j1:    bit     K_RIGHT, a
        jr      z, .j2
        set     1, c
.j2:    bit     K_UP, a
        jr      z, .j3
        set     2, c
.j3:    bit     K_DOWN, a
        jr      z, .j4
        set     3, c
.j4:    bit     K_FIRE, a
        jr      z, .j5
        ld      e, 1
.j5:
        ld      a, c
        ld      (in_mask), a
        ld      a, e
        ld      (in_button), a
        ret

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
        ret


in_mask:    db 0
in_button:  db 0
v_lr:       dw 0
v_ud:       dw 0
v_mask:     db 0
var_E5:     dw 0
var_FA:     dw 0
var_FB:     dw 0
var_FC:     dw 0
var_FD:     dw 0
var_FE:     dw 0
