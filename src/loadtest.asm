;-----------------------------------------------------------------------------
; Step 5: how fast does esxDOS read?
;
; The plan says to measure this BEFORE any of Phase D is built, because it is the
; one number in that phase with no evidence behind it, and because a part load
; that takes four seconds is a loading-screen design decision rather than an
; implementation detail. A part is four resources and at worst 154,971 bytes.
;
; Two traps here are already paid for on the other project and cost nothing to
; avoid:
;   * esxDOS pages ITSELF over the bottom 16K during a file call, so nothing in
;     slots 0 or 1 may be the code doing the reading, and no buffer may live
;     there either. This code is at $8000 and reads into a banked page at $C000.
;   * esxDOS takes a machine-code caller's buffer in IX, not HL - HL is the BASIC
;     caller's. wolf3d-next's fs_* set both, after CSpect wrote a filename over
;     the code that followed it.
;
; The read is into banked pages through MMU6, 8K at a time, so a 65,230-byte
; resource lands in eight pages exactly as the loader will place it.
;-----------------------------------------------------------------------------

        DEVICE ZXSPECTRUMNEXT

NR_TURBO        EQU $07
NR_MMU6         EQU $56
DST_WIN         EQU $C000
DST_PAGE        EQU 48                  ; clear of the 48K image and of Layer 2
CHUNK           EQU $2000               ; one 8K page a read

F_OPEN          EQU $9A
F_CLOSE         EQU $9B
F_READ          EQU $9D
FA_READ         EQU $01
ESX_DRIVE       EQU '*'                 ; the default drive

        ORG $8000
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3             ; 28 MHz, as the game will run

        ld      a, $5A
        ld      (ready), a

;-----------------------------------------------------------------------------
; Wait for the checker to name a file and release us, so the timing brackets the
; read and nothing else.
;-----------------------------------------------------------------------------
main:
        ; The checker clears (done) itself before it sets (go). Clearing it HERE
        ; as well meant done was 0x5A for a few T-states before the loop came
        ; round and zeroed it again, so the poll almost never saw it.
.wait:  ld      a, (go)
        or      a
        jr      z, .wait
        xor     a
        ld      (go), a

        call    load_file

        ld      a, $5A
        ld      (done), a
        jr      main

;-----------------------------------------------------------------------------
; load_file - opens (fname), reads it all into banked pages from DST_PAGE, and
; leaves the byte count in (got) and any error in (err).
;-----------------------------------------------------------------------------
load_file:
        ld      hl, 0
        ld      (got), hl
        ld      (got + 2), hl
        xor     a
        ld      (err), a

        ; --- open ---
        ld      a, ESX_DRIVE
        ld      ix, fname
        ld      hl, fname               ; both, because which one is read depends
        ld      b, FA_READ              ; on whether the caller looks like BASIC
        rst     $08
        db      F_OPEN
        jr      nc, .opened
        ld      (err), a
        ld      a, 1
        ld      (errwhere), a
        ret
.opened:
        ld      (handle), a

        ld      a, DST_PAGE
        ld      (cur_page), a

        ; --- read, one 8K page at a time ---
.next:
        ld      a, (cur_page)
        nextreg NR_MMU6, a

        ld      a, (handle)
        ld      ix, DST_WIN
        ld      hl, DST_WIN
        ld      bc, CHUNK
        rst     $08
        db      F_READ
        jr      nc, .read_ok
        ld      (err), a
        ld      a, 2
        ld      (errwhere), a
        jr      .close
.read_ok:
        ; BC = bytes actually read. Zero means end of file.
        ld      a, b
        or      c
        jr      z, .close
        ld      hl, (got)
        add     hl, bc
        ld      (got), hl
        jr      nc, .nocarry
        ld      hl, (got + 2)
        inc     hl
        ld      (got + 2), hl
.nocarry:
        ld      hl, cur_page
        inc     (hl)
        ; a short read also means end of file
        ld      a, b
        cp      CHUNK >> 8
        jr      nz, .close
        jr      .next

.close:
        ld      a, (handle)
        rst     $08
        db      F_CLOSE
        ret

;-----------------------------------------------------------------------------
        EXPORT ready
ready:      db 0
        EXPORT go
go:         db 0
        EXPORT done
done:       db 0
        EXPORT err
err:        db 0
        EXPORT errwhere
errwhere:   db 0            ; 1 = open, 2 = read
        EXPORT got
got:        dw 0, 0         ; bytes read, 32-bit
        EXPORT fname
fname:      ds 32           ; the checker pokes an ASCIIZ name here
handle:     db 0
cur_page:   db 0

        ASSERT $ < $BF00
        SAVENEX OPEN "build/loadtest.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
