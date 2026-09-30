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

**The hooks: 9 resident bytes, and a 49-byte block after the C.** One 3-byte `call` each in:
- the interrupt, at `.no_mix`, so at both line interrupts: the card's frame work at LINE_A, the
  UART both ways at both;
- aw_play_sound's first instruction: the effect goes to the card, then the Z80 path runs on;
- aw_play_music's first instruction: the Z80 path runs first, then the card is told.

Each call goes to a gate in a block at **$BACA** (CARD_GATES), between the C's heap header and
MUSIC_CODE. A gate returns at once while the card is off, so the Z80 path pays a call, a load and
a test. With the card on it runs the card's routine through card_call (the MMU7 borrow). cop_start
ends in the boot (`ei`, then card_call CARD_BOOT: 6 bytes of COP_CODE's 14 spare). Page 10 takes
the rest: st_music declines while the card is on, st_stop (every stop of the player and every
voice: op_updateMemList(0), a part's setup, a load) tells the card, and sv_load's end resyncs it.

**$BACA, not $BAC4: the C writes twelve bytes nobody had counted.** The zxn CRT is built with
CLIB_MALLOC_HEAP_SIZE -1, so at startup it puts a malloc heap between the BSS's end ($BABE) and the
stack and asm_heap_init writes a six-byte mutex and the first block's six-byte header there -
whether or not the C mallocs, and it does not. CC_TOP was "the highest symbol plus eight", $BAC4,
so the gates' first build had card_on and the gate's first bytes overwritten the moment the VM
started, and the interrupt ran garbage two seconds later (check-aw: ticks stopped at 129).
tools/mkexp.py's CC_TOP now counts the header ($BACA), and the C's ASSERT holds against the gates.

**The boot.** cop_start's end calls card_boot, with interrupts on (the upload's time limits count
ticks). It probes (half a second for SUP>, so a machine with no Pi loses half a second), installs
the card from GUSINST.TXT if the probe says GA42, hands off, tries the fast link (1 Mbit with
RTS/CTS; an emulator never switches, and a switch that fails is back at 115,200 inside a second),
uploads GUSALL.GUS (every sound, 227 blocks), and checks the card's CRC of its memory against the
build's. Only then is the card on: the interrupt's mixer is switched off (snd_off), the copper's
list is set to silence and uploaded whole, and the interrupt's card work starts. Any failure ends
the session (E, SUP>) and leaves the card off and the Z80 path as it is.

**Effects.** aw_play_sound with the card on keeps the reference's order of tests (a resource not
loaded returns before volume 0 stops the channel), then writes the channel's slot in a four-slot
mailbox with interrupts held off. The interrupt, the ring's only writer, puts every full slot on
that frame's F line: a note on voice (channel & 3), the sound's own resource number as the card's
sample, the reference's frequency table in Hz, volume x 4; or a stop. The Z80 path then runs as
ever, into voices nobody hears - which is what a lost card hands back to.

**Music: the Z80 player keeps the time, a sender in the interrupt plays it.** The Z80 player runs
at the frame boundary exactly as without the card - music_clock, music_tick, the 0xF4 marker the
scripts wait on, the positions a save keeps - with the mixer off. So the game's timing, the
markers included, is the Z80 path's by construction, and nothing had to be latched. The card's
notes come from a sender in the interrupt that walks the same module on the same clock (a row
every `delay x 60 / 7050` ms from the Z80 clock's own start), up to L = 300 ms ahead, as A lines
stamped with each row's exact time - so a row is heard on time however long the VM frame that owns
it runs. It keeps its own copy of the order and instrument tables (the Z80 path rewrites them for
the next module) and borrows MMU2/MMU3 for the pattern, reading and putting back what it found. It
follows the reference, sfxplayer.cpp, where the Z80 path does not: a row naming an instrument sets
the channel's volume, the order list's end stops every channel, a note is 7159092 / (period x 2)
Hz (a 24-by-16 division in the interrupt, about 2,000 T-states). What the machine's calls tell it:
- a module start: the old module's rows after the start cut; W lines zero each loaded
  instrument's first four samples in the card's memory (prepareInstruments); rows from there;
- a retime: the reference's re-armed timer - the pending row keeps its time, the rows after it are
  cut and sent again on the new period (the sender remembers its last eight rows to rewind among);
- a stop (op_playMusic 0, 0): the rows after it cut; the notes sounding carry on;
- st_stop (op_updateMemList(0), a part's setup, a load): the same, and every voice off, and any
  effect still in the mailbox dropped (`player->stop(); mixer->stopAll()`, vm.cpp:371-374);
- sv_load's end: the sender restarts from the loaded player's position.

**What the card changes in the game's timing:** the sound is heard D (20 ms) plus the Pi's
output buffer (about 45-70 ms) after the Next sends it, where the Z80 path's is 10-20 ms. David
judges it at A4 and A5.

**A card lost mid-game** (the watchdog: no `%` line for 1.5 s, or SUP>): the interrupt turns the
card off and the mixer back on. The effects and the music go on at once on the Z80 path, from the
Z80 voices, which op_playSound and the Z80 player kept current all along. The intro's streamed
music does not start (st_music declined it); its tune carries on in the module player instead.

**Saves.** sv_save is unchanged. sv_load stops the card (its aw_setup_part reaches st_stop) and,
at its end, restarts the sender from the loaded player's state; the voices it restores are the Z80
mixer's, and the card does not replay notes that were sounding.

**The upload modes.** The plan builds two, and the KS3 picks: every sound at boot (built at A2,
the default, and what CSpect uses), or each sound as the game loads it. The second needs a hook in
aw_load_res (3 more resident bytes, which exist) and a W-free path for the loader's own MMU7; it
is built only if the KS3 shows the fast link will not run (nextpi-gus's docs/ks3-checklist.md).

## Status

| Step | State | Evidence |
|---|---|---|
| A0 | done, tag gus-a0 | `make check-sndcalls`: the intro's calls are the engine's, bar three sound-52 calls (below) |
| A1 | done, tag gus-a1 | `make check-gus`: every sound in the card's memory byte for byte; five pins; the pitches in Hz |
| A2 | done, tag gus-a2 | all 18 ZEsarUX gates pass with no Pi (the probe costs half a second); `make check-card ONLY=1,2,3`: in CSpect the boot finds the fake Pi's card, uploads 227 blocks (861 frames at 115,200, no block named), %M = 139E5101 as the machine read it and as the card wrote it, the card's work every frame after and the card counting ~50 good lines a second and no bad one while the intro runs; a Pi without the card gets it from GUSINST.TXT (the ARM build, byte for byte) and the same boot follows; with no Pi, CS_NOPI and the Z80 path |
| A3 | done, tag gus-a3 | `make check-card` (all five sessions): over the whole intro in CSpect, the 225 effects on the F lines are the machine's 225 aw_play_sound calls, each on the next frame's line; the music the card keeps is the reference player's for the machine's own op_playMusic calls - 977 events, 487 notes, row for row at the same times, after 5 cuts; W zeroes the 6 instruments' first samples; every voice off after each st_stop (2); the markers keep their times (the machine's effects are the engine's, as at A0); 13,433 lines, none bad, the card counting no bad line or gap; the intro at 100.2% of the original (speed.py). The card killed mid-intro: SUP> seen at once (err 4), the Z80 mixer takes over, the intro runs on with its effects. All 18 ZEsarUX gates pass with no Pi |
| A4 | ready: David's | `make play-gus`, and `make play-gus CARD=0` to compare (below) |
| A5 | ready: David's, on the KS3 | below; after nextpi-gus's H1 |

## A4 and A5: David's checkpoints

**A4, in CSpect.** `make play-gus` builds the BYPASS_PROTECTION image (the intro, then part 2),
starts nextpi-gus's fake NextPi with the card playing on the Mac's speakers, and opens CSpect.
The boot uploads every sound first: about 17 s of a blank screen with a blue border, then the
border goes black and ENTER starts the intro. `make play-gus CARD=0` is the same image with no Pi:
the Z80 path, CSpect's own sound. Listen to both: the intro's music (the card mixes the module
live, the Z80 path streams MUSIC.PCM), the effects, and how late the effects feel (the card's are
D plus the Mac's output buffer after the frame that asked). Keys as ever: O P Q A, Space, ENTER.

**A5, on the KS3** (after nextpi-gus's H1, which installs and hears the card with its own test
.nex and tries the fast link):
1. On the Deck (the Mac mounts SD cards read-only): the game's folder as CSpect has it
   (~/src/cspect/sd/aw: AW.NEX and the resources), with build/aw.nex (or build/aw-play.nex) as
   AW.NEX and build/assets/GUSALL.GUS and GUSINST.TXT beside it.
2. Boot the game with the Pi fitted. THE BORDER SAYS WHAT THE CARD DID: blue from the Pi's
   answer while the card is found, installed (the first time: GUSINST.TXT, about 11 s at
   115,200) and uploaded - time it: that is the upload; black once the card is on; magenta if it
   failed after the Pi answered, or was lost mid-game (the Z80 path is playing then). No Pi: the
   border never changes and the game starts half a second later than before.
3. Play the intro and part 2 with the card, then without (take GUSALL.GUS away: the upload fails,
   magenta, the Z80 path). Judge the effects' latency, and part 2's frame rate with the mixer's
   16% given back.
4. Decide: the upload mode (every sound at boot is what is built; per-load only if the fast link
   will not run and the boot's upload is too long), and the default route (the card whenever it
   is there, or not).

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

**A3 closed half of it: those three calls play nothing.** Sound 52 is not loaded when the machine
asks for it (the hook now logs each call's res_page), so op_playSound returns before it touches a
channel - on the Z80 path and on the card alike, as the reference would (vm.cpp:698). What remains
is that the scripts run the loop more times than the engine's did; nobody hears it.

## The memory map, additions only

| Where | What | Size |
|---|---|---|
| resident | three `call` hooks | 9 bytes of the 16 free |
| COP_CODE | cop_start's end: the boot | 6 of the 14 bytes free |
| $BACA-$BAFA | card_on, card_call and the gates | 49 of 54 bytes; CC_TOP (with the heap header) asserted below them |
| page 10 | st_music's decline, st_stop's call, sv_load's | a few dozen bytes of the ~5 KB free |
| page 11 | gus.inc, piuart.inc, gusprobe.inc, the glue, the sender, the ring, the CRC table, the tables | under 8 KB, asserted |

## Coordination

This repo belongs to the "Another World" session, which said on 2026-09-30 that it is not editing
it and will say before it starts. The card's side is nextpi-gus's.
