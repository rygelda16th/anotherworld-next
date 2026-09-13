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
        PUBLIC  _aw_frame_sync

        defc    _aw_code_window = 0x8000
        defc    _aw_draw_poly   = 0x8003
        defc    _aw_select_page = 0x8006
        defc    _aw_fill_page   = 0x8009
        defc    _aw_copy_page   = 0x800C
        defc    _aw_blit        = 0x800F
        defc    _aw_set_palette = 0x8012
        defc    _aw_frame_sync  = 0x8015
; aw_frame_sync is the frame boundary, and it is the one slot the harness does not
; use for its own sake: vmtest.asm returns immediately from it, while src/aw.asm
; waits for the frame interrupt's tick and tops the sound ring up. That is how the
; C keeps owning the frame loop for Gate D while the game gets its pacing and its
; sound - one hook rather than two frame loops that can disagree.
; The trace buffer at $C000 and the control block at $8100 are NOT declared here.
; They are plain address constants in the C, because an `extern uint8_t x[]` against
; a defc was read as a pointer variable living at that address rather than as the
; address itself - four different fields came back as the same value. A cast
; integer constant cannot be read two ways.

