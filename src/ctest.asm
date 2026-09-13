;-----------------------------------------------------------------------------
; Gate B: sjasmplus is the master, z88dk supplies the C.
;
; This is the binding the blueprint's decision 6 chose, in its smallest working
; form. The point worth noticing is that NEITHER side has to look up a symbol in
; the other's output:
;
;   * The C calls assembly through a jump table at $8000. That address is fixed
;     by construction - it is the very bottom of this image - so preflight/cc/
;     jumptab.asm can simply `defc` it.
;   * This file calls the C at CC_ORG, which is where the C runtime's entry point
;     lands because CRT_ORG_CODE was set to exactly that.
;
; So the build is one pass of each tool, in order: zcc, then sjasmplus. The .exp
; that tools/mkexp.py produces is for the CHECKER's benefit, not the build's.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

CC_ORG          EQU $A000       ; must match CC_ORG in the Makefile
NR_TURBO        EQU $07
NR_L2_CFG       EQU $70
NR_L2_BANK      EQU $12
L2_PORT         EQU $123B
L2_VISIBLE      EQU %00000010

        ORG $8000
;-----------------------------------------------------------------------------
; The jump table. Three bytes an entry, at a fixed address, and the ONLY thing
; the C side needs to know about this image. Entries are append-only: inserting
; one would move every entry after it and silently repoint the C.
;-----------------------------------------------------------------------------
jump_table:
        jp      aw_poke                 ; $8000  void aw_poke(uint16_t)
        jp      aw_sum                  ; $8003  uint16_t aw_sum(uint16_t)
        ASSERT $ - jump_table == 6

;-----------------------------------------------------------------------------
; Boot: set the machine up, then hand over to the C.
;-----------------------------------------------------------------------------
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3             ; 28 MHz
        nextreg NR_L2_CFG, 0            ; 256x192, 8bpp
        nextreg NR_L2_BANK, 12
        ld      bc, L2_PORT
        ld      a, L2_VISIBLE
        out     (c), a

        ld      a, $A5
        ld      (asm_ran), a            ; this file reached the handover

        call    CC_ORG                  ; the C runtime's entry point
        ; The C loops for ever, so arriving here at all is a fault worth seeing.
        ld      a, $EE
        ld      (asm_ran), a
.hang:  jr      .hang

;-----------------------------------------------------------------------------
; aw_poke - HL = a value from C. Stores it where the checker can read it.
; __z88dk_fastcall means the single argument arrives in HL, not on the stack.
;-----------------------------------------------------------------------------
aw_poke:
        ld      (poked), hl
        ld      a, (poke_count)
        inc     a
        ld      (poke_count), a
        ret

;-----------------------------------------------------------------------------
; aw_sum - HL = a value from C; returns HL + $1111, also in HL.
; A wrong calling convention shows up as a wrong number rather than a hang,
; which is the whole reason for returning something derived from the argument.
;-----------------------------------------------------------------------------
aw_sum:
        ld      de, $1111
        add     hl, de
        ret

        EXPORT asm_ran
asm_ran:        db 0
        EXPORT poked
poked:          dw 0
        EXPORT poke_count
poke_count:     db 0

;-----------------------------------------------------------------------------
; And the compiled C, dropped in at the address it was compiled for.
;-----------------------------------------------------------------------------
        ASSERT $ < CC_ORG               ; the assembly must not reach into it
        ORG CC_ORG
c_image:
        INCBIN "build/ctest_CODE.bin"
c_image_end:

        DISPLAY "assembly ends at ", /A, $8000 + (start - $8000)
        DISPLAY "C image is ", /D, c_image_end - c_image, " bytes at ", /A, CC_ORG

        SAVENEX OPEN "build/ctest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1         ; 1792K, the 2MB profile
        SAVENEX AUTO
        SAVENEX CLOSE
