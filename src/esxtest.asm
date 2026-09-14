;-----------------------------------------------------------------------------
; The esxDOS window invariant.
;
; RST $08 is a jump to $0008, and esxDOS only answers there because the divMMC pages
; itself in when the processor FETCHES from that address - which it can only do while
; the bottom 16K is ROM. vmhost.inc's code_add maps the bytecode segment over exactly
; that range on every bytecode fetch, so a load issued after the VM has fetched an
; opcode does not reach esxDOS at all: the RST lands in bytecode.
;
; src/maptest.asm has known this since gate I1 - "the ROM back over the bottom 16K,
; and bank 5 back at $4000, which is what the DOS needs" - and the loader never did
; it. The game ran anyway under ZEsarUX, whose esxDOS answers the RST by address
; whatever the paging says, and died on the first mid-game load under CSpect, whose
; esxDOS plugin checks that MMU0 reads back as ROM. Real hardware follows CSpect.
;
; So this gate does not test the LOAD - ZEsarUX would pass that either way, which is
; precisely how the fault survived twelve gates. It tests the invariant directly:
; what MMU0 and MMU1 actually read while a DOS call is in progress, and whether they
; come back afterwards. That is a claim about registers, and registers are the same
; in both emulators.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

CC_ORG          EQU $9C08               ; unused here; vmhost.inc's neighbours expect it
NR_TURBO        EQU $07
NR_MMU0         EQU $50
NR_MMU1         EQU $51
NR_MMU7         EQU $57
CODE_WIN        EQU $0000
CODE_PAGE       EQU 48
DST_WIN         EQU $E000
SIG_LO          EQU 73                  ; the pages the probe caught in MMU0/MMU1 when
SIG_HI          EQU 74                  ; the machine ran off into the bytecode

; F_OPEN, FA_READ and ESX_DRIVE all come from vmhost.inc

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

        ; THE VM'S STATE: the bytecode segment over the bottom 16K, which is what
        ; code_add leaves behind after every single opcode fetch.
        nextreg NR_MMU0, SIG_LO
        nextreg NR_MMU1, SIG_HI
        call    rd_mmu
        ld      (m_before), hl

        ; What a DOS call would see.
        call    esx_rom
        call    rd_mmu
        ld      (m_during), hl

        ; And what the VM gets back.
        call    esx_back
        call    rd_mmu
        ld      (m_after), hl

        ; END TO END, with the window paged in on the way in: the checker names the
        ; file, load_code does the rest, and (got) says whether esxDOS was ever
        ; reached. Under ZEsarUX this passes with or without the fix - it is here so
        ; that the invariant and the load are proven on the same run, not because it
        ; is the part that bites.
        nextreg NR_MMU0, SIG_LO
        nextreg NR_MMU1, SIG_HI
        call    load_code
        call    rd_mmu
        ld      (m_load), hl

        ld      a, $5A
        ld      (done), a
.hold:  jr      .hold

;-----------------------------------------------------------------------------
; rd_mmu - MMU0 in L, MMU1 in H. Reading a NextReg back needs it selected on
; $243B and read from $253B; port $123B is write-only on this machine, so nothing
; is assumed readable without checking that it is.
;-----------------------------------------------------------------------------
rd_mmu:
        ld      bc, $243B
        ld      a, NR_MMU0
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      l, a
        ld      b, $24
        ld      a, NR_MMU1
        out     (c), a
        ld      b, $25
        in      a, (c)
        ld      h, a
        ret

        EXPORT ready
ready:      db 0
        EXPORT go
go:         db 0
        EXPORT done
done:       db 0
        EXPORT m_before
m_before:   dw 0
        EXPORT m_during
m_during:   dw 0
        EXPORT m_after
m_after:    dw 0
        EXPORT m_load
m_load:     dw 0

        INCLUDE "src/inc/vmhost.inc"

        ; The loader's own state lives in vmhost.inc; these say which of it the
        ; checker reads.
        EXPORT fname
        EXPORT err
        EXPORT got

        DISPLAY "> esxtest ends at ", /H, $
        ASSERT $ < $BF00

        SAVENEX OPEN "build/esxtest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
