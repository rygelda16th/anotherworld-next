# Another World's sound on the Pi's GUS-like card (plan-pi-gus.md)

The card is ~/src/nextpi-gus (GPL-2.0-or-later): a program on the Next's Pi Zero that keeps the
game's samples in its memory and plays voice commands the Next sends over the Pi UART. Its
plan is nextpi-gus's docs/plan.md, approved by David on 2026-09-30; these are its steps A0-A5,
copied here as that plan says. Its protocol is nextpi-gus's docs/protocol.md (GUS1), and the
Next's side of it is nextpi-gus's src/next/gus.inc, which this port includes.

**Why.** Today the Z80 mixes four voices at 15,600 Hz through the copper (about 16% of the
machine), and the intro's music is a 1.86 MB stream read from the SD card with interrupts off,
which the KS3 has not yet tested. With the card on, the game sends notes and nothing mixes on
the Next: the mixer's share comes back, the stream is not read, and the music gets the
reference's interpolation back. **The Z80 path stays exactly as it is**, and is what runs with
no Pi, with no card program, in every ZEsarUX gate, and when the card is lost mid-game.

## The steps

| # | Step | Needs | Gate | David's checkpoint | Tag |
|---|---|---|---|---|---|
| A0 | This plan; the memory map below; a CSpect hook that logs the machine's own sound calls | nextpi-gus G5 | the hook's log for the intro in CSpect (the Z80 path) equals the reference engine's effects, in order | read this file | gus-a0 |
| A1 | The card's upload files in `make assets` | A0 | nextpi-gus's card decodes every file to its sound byte for byte; pinned | none | gus-a1 |
| A2 | Boot: find the Pi and the card, install it if missing, upload, check, fall back | A1 | every existing gate still passes with no Pi (ZEsarUX); in CSpect with the fake Pi, the upload's %M matches | none; report | gus-a2 |
| A3 | Effects and music on the card together | A2 | the CSpect run: the card's events are what the machine asked for, in order, on time; the markers keep their times; the intro still runs at 100% or more; a card lost mid-intro hands over to the Z80 path with no crash | none | gus-a3 |
| A4 | David plays it in CSpect | A3 | `make play-gus` | the intro and part 2 with the card; compare with the Z80 path; judge the effects' latency | gus-a4 |
| A5 | The KS3 | nextpi-gus H1, A4 | the upload time, the CPU freed, the latency | play on the hardware; choose the upload mode and the default route | gus-a5 |

## The design (settled from the code, 2026-09-30)

**Where the card's code lives: page 11, run at MMU7.** The resident block has 16 bytes free, the
upper block 5, and MMU6's gaps a few each. Page 11 (bank 5's upper half) is empty: nothing is
ORGed there, and MMU3's use of it (aw_setup_part's palette window) maps another page into the slot
rather than touching its contents. gus.inc and piuart.inc are 3.7 KB, the port's glue about 2 KB,
the ring 512 bytes and the CRC table 256, so it fits in 8 KB. It runs at $E000: the caller borrows
MMU7, maps page 11, and puts back what it found, exactly as the interrupt already borrows MMU7
for a voice's sample page. (While the card is on, the mixer does not run, so the two never nest.)

**The hooks: 12 resident bytes, and a 53-byte block after the C.** One 3-byte `call` each in:
- the interrupt, on the frame's line (LINE_A): the card's work for this frame;
- aw_play_sound: the effect goes to the card instead;
- aw_play_music: the module goes to the card's player instead;
- snd_frame: the frame boundary's card work (the 0xF4 marker) instead of music_clock.

Each call goes to a gate in a block at $BAC4, between the C's variables (CC_TOP) and MUSIC_CODE,
which the C's ASSERTs move down to. A gate returns at once while the card is off, so the Z80
path costs 17 T-states more a call and nothing else. With the card on, it drops the hooked
routine's own return and runs the card's routine through card_call (the MMU7 borrow). Page 10,
which has room, takes the rest: st_music declines while the card is on, st_stop (reached from
op_updateMemList(0) and aw_setup_part) sends the card a cut and all-off, and sv_load resyncs it.

**The boot.** cop_start's end calls card_boot, with interrupts on (the upload's time limits count
ticks). It probes (half a second for SUP>, so a machine with no Pi loses half a second), installs
the card from GUSINST.TXT if the probe says GA42, hands off, uploads GUSALL.GUS (every sound, 227
blocks), and checks the card's CRC of its memory against the build's. Only then is the card on:
the copper list's values are set to silence and the interrupt's mixer is switched off (snd_off).
Any failure leaves the card off and the Z80 path as it is.

**Effects.** aw_play_sound with the card on keeps the reference's order of tests (a resource not
resident returns before volume 0 stops the channel), then writes the channel's slot in a
four-slot mailbox: clear its flag, write the note, set the flag. The interrupt, the ring's only
writer, puts every full slot on that frame's F line: a note on voice (channel & 3), the sound's
own resource number as the card's sample, the reference's frequency table in Hz, volume x 4.

**Music.** aw_play_music with the card on does what the resident routine does - the same mus_*
variables and the same order and instrument tables in MMU6, so sv_save, sv_load and a fallback
all see a consistent player - and then tells the card's player. The player runs **in the
interrupt**: it maps the module's two pages at MMU2 and MMU3 (saved and put back by reading the
NextRegs), and each frame:
- moves the play cursor over the rows now due, keeping mus_cur_order and mus_cur_pos current and
  latching a 0xFFFD row's value with its time;
- sends the rows due up to 300 ms ahead as A lines, stamped with their exact time (a row every
  `delay x 60 / 7050` ms): a note (7159092 / (period x 2) Hz, the instrument's volume with effects
  5 and 6, x 4), a stop for 0xFFFE, the volume for a row naming an instrument with no note, and
  all-off where the order list ends.

A retime or stop (resNum 0) sends a cut reaching back to the op's time, and the rows from the
pending one on are sent again on the new timing (the pending row keeps its time, as
sfxplayer.cpp's re-armed timer does). A new module cuts the old one's queued rows, and writes
four zero bytes over each instrument's first samples in the card's memory (W lines), as
prepareInstruments does to the resources themselves.

**The 0xF4 marker** is published at the frame boundary from the latch, never from the
interrupt: the C reads the variable as two bytes, and its threads must all see one value in a
frame. That is when the Z80 player publishes it today, so the scripts see the same timing.

**What the card changes in the game's timing:** the sound is heard D (20 ms) plus the Pi's
output buffer (about 45-70 ms) after the Next sends it, where the Z80 path's is 10-20 ms. David
judges it at A4 and A5.

**A card lost mid-game** (the watchdog: no `%` line for 1.5 s, or SUP>): the interrupt turns the
card off and the mixer back on. The effects go on at once on the Z80 path, and so does the music,
because the player's state was the Z80 player's all along. The intro's streamed music does not
restart (st_music declined it); its tune resumes at the module player's position instead.

**Saves.** sv_save is unchanged. sv_load with the card on sends all-off and a cut, and restarts
the card's player from the loaded mus_* state; the voices it restores are the Z80 mixer's, and
the card does not replay notes that were sounding. A loop that was sounding at the save starts
again with the next row or effect that names it.

**The upload modes.** The plan builds two, and the KS3 picks: every sound at boot (built at A2,
the default, and what CSpect uses), or each sound as the game loads it. The second needs a hook in
aw_load_res (3 more resident bytes, which exist) and a W-free path for the loader's own MMU7; it
is built only if the KS3 shows the fast link will not run (nextpi-gus's docs/ks3-checklist.md).

## A0's finding (2026-09-30)

The hook (tools/cspect/awsnd.cs) logs every call the C makes to aw_play_sound and aw_play_music,
from outside, with the machine's tick. On the Z80 path, over 100 s of the intro in CSpect
(`make check-sndcalls`): the three music calls are the engine's; of the 48 effects, the first 35
are the engine's exactly, then **the machine plays sound 52 three times (ticks 3309-3392, about
66 s) where the engine played none**, and the rest line up again. The random seed is not it (the
check pokes the reference run's, 867, and nothing changes). The machine is about 3 s behind the
engine there - CSpect runs at about 93% of the hardware - and the intro's scripts pace some of
their loops against the music, so a loop runs a different number of times. It is the Z80 path's
own behaviour, reported to the Another World session; the card's gates hold the card to what the
MACHINE asks for (this hook), not to the engine.

## The memory map, additions only

| Where | What | Size |
|---|---|---|
| resident | four `call` hooks | 12 bytes of the 16 free |
| $BAC4-$BAFF | card_on, card_call and the gates | 53 of 60 bytes; CC_TOP asserted below them |
| page 10 | st_music's decline, st_stop's cut, sv_load's resync | a few dozen bytes of the ~5 KB free |
| page 11 | gus.inc, piuart.inc, the glue, the player, the ring, the CRC table, the tables | under 8 KB, asserted |

## Coordination

This repo belongs to the "Another World" session, which said on 2026-09-30 that it is not editing
it and will say before it starts. The card's side is nextpi-gus's.
