;-----------------------------------------------------------------------------
; COPIED from nextpi-gus src/next/gusprobe.inc by tools/mkgusdata.py (`make gus-assets`): the
; build container cannot see that repo. Do not edit here; change it there.
;-----------------------------------------------------------------------------
; gusprobe.inc - the probe line (tools/mkgusinst.py's probe_line()) for gus.inc's test
; host. It leaves the card's folder in SUP's ND, which gus_start's "$ND/nextpi-gus" needs.
; A game types its own probe line, or GUSINST.TXT's check.
; PROVENANCE: nextpi-opl src/next/noplprobe.inc at tag n5, with the card's names.
;-----------------------------------------------------------------------------

; probe_gus - SUP>, the probe line, then GP42 (blocking, up to 3 s). CF set: no prompt, or
; no card there (GA42, or no answer in a second: gus_start would then fail). probe_result:
; 0 the card is there, 1 no SUP> prompt, 2 no card (install it: gus_install)
probe_gus:
        call pi_uart
        ld de,PI_PER_S * 2
        call pi_ready
        ld a,1
        jr c,.r
        ld hl,probe_s_line
        call pi_puts
        ld hl,probe_s_gp
        ld de,PI_PER_S
        call pi_expect
        ld a,2
        jr c,.r
        xor a
.r:     ld (probe_result),a
        cp 1                            ; CF: not there (A 1 or 2)
        ccf
        ret nc
        or a
        scf
        ret z
        ret

probe_result:   DB 0

probe_s_line:   DB 'ND=;for d in /NextPi/nextpi /ram/nextpi;do [ -f $d/nextpi-gus ]&&'
                DB '[ -x $d/nextpi-gus ]&&ND=$d&&break;done;[ -n "$ND" ]&&echo GP$((6*7))||echo GA$((6*7))', 10, 0
probe_s_gp:     DB "GP42"
