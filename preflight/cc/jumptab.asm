; Phase B: how C learns the address of an assembly routine.
;
; This is the whole trick, and it needs no second pass and no negotiation
; between the two assemblers. sjasmplus puts a jump table at an address fixed by
; construction - the very bottom of its image - and this file, assembled by
; z88dk's own z80asm alongside the C, declares those addresses as public
; symbols. The C then calls them like any other extern.
;
; SDCC prefixes C identifiers with an underscore, so `aw_poke` in C is
; `_aw_poke` here.

        SECTION code_user

        PUBLIC  _aw_poke
        PUBLIC  _aw_sum

; Entry 0 and entry 1 of a three-byte-per-slot table at $8000.
        defc    _aw_poke = 0x8000
        defc    _aw_sum  = 0x8003
