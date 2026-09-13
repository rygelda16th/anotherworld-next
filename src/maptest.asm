;-----------------------------------------------------------------------------
; I1's killing experiment: can the integrated program's eight slots coexist?
;
; Chain 2 rests on one unproven assumption - that everything the game needs can be
; REACHABLE at once through the Z80's eight 8K slots. Capacity is not the question;
; the arithmetic in the plan puts the whole game at 502,527 bytes, half of a 1MB
; machine. The question is slot contention, and no harness has ever needed more than
; two windows at a time.
;
; So before a line of the integrated program is written: put a distinct signature in
; eight banked pages, map the proposed arrangement all at once, and read every
; signature back. Then do the thing that is known to break it - an esxDOS call, which
; needs the ROM at $0000 and bank 5 at $4000 - and read them all back again.
;
; The claim under test, region by region:
;
;   $0000-$3FFF  MMU0/1  the bytecode window, two 8K pages of a segment up to 62,683
;   $4000-$7FFF  MMU2/3  the polygon/cinematic window, a segment up to 65,230.
;                        THIS IS THE NEW CLAIM. The memory map in vmtest.asm records
;                        this region as "NOT AVAILABLE" - but it records that for the
;                        duration of a DOS CALL, because esxDOS needs bank 5's system
;                        variables at $5B00. Outside a DOS call it is sixteen
;                        kilobytes of address space the project has never used, and
;                        the second window has to go somewhere.
;   $8000-$BFFF  MMU4/5  resident code: the assembly, the C, the stack
;   $C000-$DFFF  MMU6    the Layer 2 band being drawn
;   $E000-$FFFF  MMU7    the mixer's sample window, and the loader's staging
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

NR_TURBO        EQU $07
NR_MMU0         EQU $50
NR_MMU1         EQU $51
NR_MMU2         EQU $52
NR_MMU3         EQU $53
NR_MMU6         EQU $56
NR_MMU7         EQU $57

; Clear of everything: the 48K image (pages 0-5, 10-11), Layer 2 (24-41), the
; bytecode pages vmtest uses (48-55) and sndtest's samples (62).
SIG_PAGE        EQU 64          ; 64..71, eight pages, one signature each
BANK5_LO        EQU 10          ; bank 5 = 8K pages 10 and 11
BANK5_HI        EQU 11

F_OPEN          EQU $9A
F_CLOSE         EQU $9B
FA_READ         EQU $01
ESX_DRIVE       EQU '*'

        ORG $8000
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3

        ld      a, $5A
        ld      (ready), a
.wait:  ld      a, (go)
        or      a
        jr      z, .wait

        ; ---- 1. a signature into each of the eight pages -------------------
        ; Written through MMU7 one at a time, so this proves nothing about
        ; simultaneity yet - only that the pages exist and are distinct.
        ld      b, 8
        ld      a, SIG_PAGE
.fill:
        nextreg NR_MMU7, a
        push    af
        push    bc
        ; the signature is the page number in every byte of the page, so a
        ; half-mapped window shows up as a boundary rather than as a wrong byte
        ld      hl, $E000
        ld      de, $E001
        ld      bc, $2000 - 1
        ld      (hl), a
        ldir
        pop     bc
        pop     af
        inc     a
        djnz    .fill

        ; ---- 2. is $4000-$7FFF ours at all? -------------------------------
        ; Before trusting it as a window, prove it is plain RAM we can write and
        ; read with our own page in it. Bank 5 lives there by default and holds the
        ; system variables, so this maps a signature page over it first.
        nextreg NR_MMU2, SIG_PAGE + 2
        nextreg NR_MMU3, SIG_PAGE + 3
        ld      a, $A5
        ld      ($4000), a
        ld      ($5B00), a              ; where the system variables would be
        ld      a, $5A
        ld      ($7FFF), a
        ld      a, ($4000)
        ld      (r_4000w), a
        ld      a, ($5B00)
        ld      (r_5b00w), a
        ld      a, ($7FFF)
        ld      (r_7fffw), a

        ; PUT THE SIGNATURES BACK. The write probe above deliberately overwrites
        ; three bytes of two signature pages, and two of them - $4000 and $7FFF -
        ; are bytes step 3 samples. Leaving them written made the first run of this
        ; test report the arrangement as broken at exactly the two addresses the test
        ; itself had altered: $4000 read 165, which is $A5, and $7FFF read 90, which
        ; is $5A. The paging was right and the test was wrong, which is the third time
        ; in this project that the harness has accused the machine.
        ld      a, SIG_PAGE + 2         ; MMU2 covers $4000-$5FFF
        ld      ($4000), a
        ld      ($5B00), a
        ld      a, SIG_PAGE + 3         ; MMU3 covers $6000-$7FFF
        ld      ($7FFF), a

        ; ---- 3. the whole arrangement at once ------------------------------
        call    map_all
        call    sample                  ; into r_before

        ; ---- 4. now break it on purpose: an esxDOS call --------------------
        ; The ROM back over the bottom 16K, and bank 5 back at $4000, which is what
        ; the DOS needs. If the windows cannot be restored afterwards, the plan's
        ; slot map is wrong and this is where it says so.
        nextreg NR_MMU0, $FF
        nextreg NR_MMU1, $FF
        nextreg NR_MMU2, BANK5_LO
        nextreg NR_MMU3, BANK5_HI

        ld      a, ESX_DRIVE
        ld      ix, fname
        ld      hl, fname
        ld      b, FA_READ
        rst     $08
        db      F_OPEN
        jr      c, .openfail
        ld      (handle), a
        ld      a, 1
        ld      (r_dos), a
        ld      a, (handle)
        rst     $08
        db      F_CLOSE
        jr      .restore
.openfail:
        ld      (r_doserr), a
.restore:
        ; ---- 5. and back, and read every signature again -------------------
        call    map_all
        call    sample2                 ; into r_after

        ld      a, $5A
        ld      (done), a
.hold:  jr      .hold

;-----------------------------------------------------------------------------
; map_all - the proposed arrangement, every slot at once.
; MMU4/5 are left alone: they hold this code.
;-----------------------------------------------------------------------------
map_all:
        nextreg NR_MMU0, SIG_PAGE + 0
        nextreg NR_MMU1, SIG_PAGE + 1
        nextreg NR_MMU2, SIG_PAGE + 2
        nextreg NR_MMU3, SIG_PAGE + 3
        nextreg NR_MMU6, SIG_PAGE + 6
        nextreg NR_MMU7, SIG_PAGE + 7
        ret

;-----------------------------------------------------------------------------
; sample - one byte from the bottom and the top of every mapped window, so a
; window that is half right is distinguishable from one that is wrong.
;-----------------------------------------------------------------------------
sample:
        ld      hl, r_before
        jr      sample_into
sample2:
        ld      hl, r_after
sample_into:
        ld      a, ($0000)
        ld      (hl), a
        inc     hl
        ld      a, ($1FFF)
        ld      (hl), a
        inc     hl
        ld      a, ($2000)
        ld      (hl), a
        inc     hl
        ld      a, ($3FFF)
        ld      (hl), a
        inc     hl
        ld      a, ($4000)
        ld      (hl), a
        inc     hl
        ld      a, ($5FFF)
        ld      (hl), a
        inc     hl
        ld      a, ($6000)
        ld      (hl), a
        inc     hl
        ld      a, ($7FFF)
        ld      (hl), a
        inc     hl
        ld      a, ($C000)
        ld      (hl), a
        inc     hl
        ld      a, ($DFFF)
        ld      (hl), a
        inc     hl
        ld      a, ($E000)
        ld      (hl), a
        inc     hl
        ld      a, ($FFFF)
        ld      (hl), a
        ret

fname:          db "RES18.BIN", 0
handle:         db 0

        EXPORT ready
ready:          db 0
        EXPORT go
go:             db 0
        EXPORT done
done:           db 0
        EXPORT r_4000w
r_4000w:        db 0
        EXPORT r_5b00w
r_5b00w:        db 0
        EXPORT r_7fffw
r_7fffw:        db 0
        EXPORT r_dos
r_dos:          db 0
        EXPORT r_doserr
r_doserr:       db 0
        EXPORT r_before
r_before:       ds 12
        EXPORT r_after
r_after:        ds 12

        ASSERT $ < $BF00
        SAVENEX OPEN "build/maptest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
