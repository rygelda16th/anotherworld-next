; How the C virtual machine learns the addresses of the assembly it calls.
;
; The same trick Gate B proved: sjasmplus puts a jump table at an address fixed by
; construction - the very bottom of its image, $8000 - and this file, assembled by
; z88dk's own z80asm alongside the C, declares those addresses as public symbols.
; No second pass, no negotiation between the two assemblers.
;
; SDCC prefixes C identifiers with an underscore. Three bytes a slot, and the
; order here IS the order in src/vmtest.asm's table - an ASSERT there checks the
; length, which is the only thing that catches a slot inserted in one file and not
; the other.

        SECTION code_user

        PUBLIC  _aw_code_window
        PUBLIC  _aw_draw_poly
        PUBLIC  _aw_select_page
        PUBLIC  _aw_fill_page
        PUBLIC  _aw_copy_page
        PUBLIC  _aw_blit
        PUBLIC  _aw_set_palette
        PUBLIC  _aw_log_buf

        defc    _aw_code_window = 0x8000
        defc    _aw_draw_poly   = 0x8003
        defc    _aw_select_page = 0x8006
        defc    _aw_fill_page   = 0x8009
        defc    _aw_copy_page   = 0x800C
        defc    _aw_blit        = 0x800F
        defc    _aw_set_palette = 0x8012
; Not a routine: the trace buffer's address. The C writes its own records, which
; is one calling convention fewer in a diagnostic that has to be trusted.
        defc    _aw_log_buf     = 0xC000
