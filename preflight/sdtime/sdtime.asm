;-----------------------------------------------------------------------------
; HOW LONG DOES THE CARD TAKE? (where-things-stand.md: ST_CHUNK "is a KS3 question")
;
; The game reads the card with interrupts off, as esxDOS wants, and the music stream reads ST_CHUNK
; (1,024) bytes just after a line interrupt, meant to end before the next one is due 156 raster
; lines (10 ms) later. Both emulators answer esxDOS on the host, instantly, so only the machine can
; say how long a read takes. Since hardware IM2 (irq_latch) an overrun delays a refill instead of
; losing it, but past the copper's 64 lines of headroom it is still heard.
;
; THE CLOCK is the CTC, which runs whatever the interrupts are doing: channel 0 a timer, prescaler
; 256, time constant 256; channel 1 counts channel 0's ZC/TO, which the core feeds into the next
; channel's CLK/TRG (the core's ports.txt, "CTC"). Together a 16-bit down-counter whose unit is 256
; cycles of the 28 MHz clock - 9.14 us, 7 to a raster line - and whose range is 600 ms.
;
; THE TESTS, one line each on the ULA screen: what was timed, the SLOWEST and the AVERAGE in CTC
; units (divide by 7 for raster lines), then the slowest in raster lines read from nextregs $1E/$1F -
; a cross-check, and the only number if the CTC count does not read back (CSpect 4.5.1.0's reads 0),
; but right only under one frame, 312 lines:
;
;   0                                 the clock: a 10-line CPU delay, so about 70 70 10
;   256 / 512 / 1024 / 2048 / 4096   32 reads of that many bytes, MUSIC.PCM from its start
;   1                                 8 x open and close RES0A.BIN (early in the folder)
;   2                                 8 x open and close RES8F.BIN (late)
;
; and a last line with the first esxDOS error, 0 if none. Run it from the folder the game is in.
;-----------------------------------------------------------------------------
        DEVICE ZXSPECTRUMNEXT

NR_TURBO        EQU $07
F_OPEN          EQU $9A
F_CLOSE         EQU $9B
F_READ          EQU $9D
FA_READ         EQU $01
ESX_DRIVE       EQU '*'
CTC0            EQU $183B
CTC1            EQU $193B
BUF             EQU $C000
READS           EQU 32
OPENS           EQU 8

        ORG $8000
start:
        di
        ld      sp, $BF00
        nextreg NR_TURBO, 3
        call    cls
        call    ctc_init

        ; the clock itself: a CPU delay of 17,920 T-states, 10 raster lines, should read about 70
        call    stats_clear
        call    t_begin
        ld      bc, 689                 ; 689 x 26 T (dec bc 6, ld a,b 4, or c 4, jr nz 12)
.cal:   dec     bc
        ld      a, b
        or      c
        jr      nz, .cal
        call    t_end
        ld      hl, 0
        ld      (size), hl
        call    show_row

        ; the reads
        ld      ix, fn_music
        call    open
        jr      c, .opens
        ld      hl, 256
        ld      b, 5
.size:  push    bc
        ld      (size), hl
        call    t_reads
        call    show_row
        ld      hl, (size)
        add     hl, hl
        pop     bc
        djnz    .size
        call    close
.opens:
        ld      hl, 1
        ld      (size), hl
        ld      hl, fn_early
        call    t_opens
        call    show_row
        ld      hl, 2
        ld      (size), hl
        ld      hl, fn_late
        call    t_opens
        call    show_row
        ld      hl, err
        xor     a
        ld      (s_col), a
        call    put5
        ld      a, $5A
        ld      (ready), a
        jr      $

; READS reads of (size) bytes from the open file
t_reads:
        call    stats_clear
        ld      b, READS
.one:   push    bc
        call    t_begin
        ld      a, (handle)
        ld      ix, BUF
        ld      hl, BUF
        ld      bc, (size)
        rst     $08
        db      F_READ
        call    c, set_err
        call    t_end
        pop     bc
        djnz    .one
        ret

; HL = a name: OPENS opens and closes of it
t_opens:
        ld      (oname), hl
        call    stats_clear
        ld      b, OPENS
.one:   push    bc
        call    t_begin
        ld      ix, (oname)
        call    open
        call    nc, close
        call    t_end
        pop     bc
        djnz    .one
        ret

; IX = the name. Carry and err set on a failure; (handle) otherwise.
open:
        push    ix
        pop     hl
        ld      a, ESX_DRIVE
        ld      b, FA_READ
        rst     $08
        db      F_OPEN
        jr      c, set_err
        ld      (handle), a
        ret
close:
        ld      a, (handle)
        rst     $08
        db      F_CLOSE
        ret

set_err:
        push    af
        ld      a, (err)
        or      a
        jr      nz, .kept
        pop     af
        ld      (err), a
        scf
        ret
.kept:  pop     af
        scf
        ret

;-----------------------------------------------------------------------------
ctc_init:
        ld      bc, CTC0
        call    .reset
        ld      a, %00100111            ; timer, prescaler 256, time constant follows, reset, control
        out     (c), a
        xor     a                       ; 256
        out     (c), a
        ld      bc, CTC1
        call    .reset
        ld      a, %01000111            ; counter: channel 0's ZC/TO
        out     (c), a
        xor     a
        out     (c), a
        ret
.reset: ld      a, %00000011            ; soft reset twice, no time constant (ports.txt)
        out     (c), a
        out     (c), a
        ret

; HL = the 16-bit count now: channel 1 high, channel 0 low, read until channel 1 holds still
now:
        ld      bc, CTC1
.again: in      h, (c)
        dec     b
        in      l, (c)
        inc     b
        in      a, (c)
        cp      h
        jr      nz, .again
        ret

; t_begin / t_end bracket one timed thing: the CTC's count into stats_add, and the raster lines
; between them (mod 312, so right only under a frame) into rmax. Keep nothing.
t_begin:
        call    now
        ld      (c_start), hl
        call    line_now
        ld      (l_start), hl
        ret
t_end:
        call    line_now
        ld      de, (l_start)
        or      a
        sbc     hl, de
        jr      nc, .pos
        ld      de, 312
        add     hl, de
.pos:   ld      de, (rmax)
        or      a
        push    hl
        sbc     hl, de
        pop     hl
        jr      c, .ctc
        ld      (rmax), hl
.ctc:   call    now
        ex      de, hl
        ld      hl, (c_start)
        or      a
        sbc     hl, de                  ; start - end: the counter counts down
        jp      stats_add

; HL = the raster line now
line_now:
        ld      bc, $243B
        ld      a, $1E
        out     (c), a
        inc     b
        in      h, (c)
        dec     b
        ld      a, $1F
        out     (c), a
        inc     b
        in      l, (c)
        ld      a, h
        and     1
        ld      h, a
        ret

stats_clear:
        ld      hl, 0
        ld      (rmax), hl
        ld      (smax), hl
        ld      (ssum), hl
        xor     a
        ld      (ssum + 2), a
        ld      (scount), a
        ret

; HL = one time
stats_add:
        ld      de, (smax)
        or      a
        push    hl
        sbc     hl, de
        pop     hl
        jr      c, .sum
        ld      (smax), hl
.sum:   ld      de, (ssum)
        ex      de, hl
        add     hl, de
        ld      (ssum), hl
        jr      nc, .n
        ld      hl, ssum + 2
        inc     (hl)
.n:     ld      hl, scount
        inc     (hl)
        ret

; (size), (smax), the average: one screen line
show_row:
        xor     a
        ld      (s_col), a
        ld      hl, size
        call    put5
        ld      hl, smax
        call    put5
        ; the average: ssum / scount, scount 8 or 32 - shift right 3 or 5
        ld      hl, (ssum)
        ld      a, (ssum + 2)
        ld      e, a
        ld      a, (scount)
.sh:    srl     a
        jr      z, .avg                 ; a power of two: shifted down to 1 -> done
        srl     e
        rr      h
        rr      l
        jr      .sh
.avg:   ld      (savg), hl
        ld      hl, savg
        call    put5
        ld      hl, rmax
        call    put5
        ld      hl, s_row
        inc     (hl)
        ret

;-----------------------------------------------------------------------------
cls:
        xor     a
        out     ($FE), a
        ld      hl, $4000
        ld      de, $4001
        ld      bc, $17FF
        ld      (hl), a
        ldir
        ld      hl, $5800
        ld      de, $5801
        ld      bc, $02FF
        ld      (hl), $47
        ldir
        ret

; the word at (HL) as five decimal digits, after a space
put5:
        ld      e, (hl)
        inc     hl
        ld      d, (hl)
        ex      de, hl
        ld      a, (s_col)
        inc     a
        ld      (s_col), a
        ld      de, 10000
        call    .digit
        ld      de, 1000
        call    .digit
        ld      de, 100
        call    .digit
        ld      de, 10
        call    .digit
        ld      a, l
        jp      putd
.digit: xor     a
.sub:   or      a
        sbc     hl, de
        jr      c, .done
        inc     a
        jr      .sub
.done:  add     hl, de
        push    hl
        call    putd
        pop     hl
        ret

putd:
        add     a, a
        add     a, a
        add     a, a
        ld      e, a
        ld      d, 0
        ld      hl, digits
        add     hl, de
        ld      a, (s_row)
        and     $18
        or      $40
        ld      d, a
        ld      a, (s_row)
        and     7
        rrca
        rrca
        rrca
        ld      e, a
        ld      a, (s_col)
        or      e
        ld      e, a
        ld      b, 8
.line:  ld      a, (hl)
        ld      (de), a
        inc     hl
        inc     d
        djnz    .line
        ld      hl, s_col
        inc     (hl)
        ret

digits:
        db      $3C, $66, $6E, $76, $66, $66, $3C, 0
        db      $18, $38, $18, $18, $18, $18, $7E, 0
        db      $3C, $66, $06, $0C, $30, $60, $7E, 0
        db      $3C, $66, $06, $1C, $06, $66, $3C, 0
        db      $0C, $1C, $3C, $6C, $7E, $0C, $0C, 0
        db      $7E, $60, $7C, $06, $06, $66, $3C, 0
        db      $3C, $60, $7C, $66, $66, $66, $3C, 0
        db      $7E, $06, $0C, $18, $30, $30, $30, 0
        db      $3C, $66, $66, $3C, $66, $66, $3C, 0
        db      $3C, $66, $66, $3E, $06, $0C, $38, 0

fn_music:   db "MUSIC.PCM", 0
fn_early:   db "RES0A.BIN", 0
fn_late:    db "RES8F.BIN", 0

        EXPORT ready
ready:      db 0
        EXPORT err
err:        dw 0
        EXPORT results
results:
size:       dw 0
smax:       dw 0
savg:       dw 0
ssum:       ds 3
rmax:       dw 0
c_start:    dw 0
l_start:    dw 0
scount:     db 0
handle:     db 0
oname:      dw 0
s_row:      db 0
s_col:      db 0

        SAVENEX OPEN "build/sdtime.nex", start, $BF00
        SAVENEX CORE 3, 0, 0
        SAVENEX CFG  0, 0, 0, 1
        SAVENEX AUTO
        SAVENEX CLOSE
