# awprobe - a CSpect plugin that watches the Z80 from outside it

Every gate in this project runs under ZEsarUX in the container. This is the other
emulator, on the desktop, and it exists because a fault turned up there that twelve
gates could not see: ZEsarUX answers `RST $08` by address whatever the paging says,
CSpect and real hardware do not. See `tools/checkesx.py`.

The plugin needs no diagnostic code in the image at all - no markers, no spare
resident bytes, no `RST $18` (which is itself unusable from inside the VM, because
CSpect's DebugOut only answers while MMU0 reads back as ROM, and the VM keeps the
bytecode segment mapped there). It reports:

* PC, SP, IFF1, IM and I sampled once a frame, as a histogram - a hung machine spends
  every sample in a handful of addresses, a running one spreads across thousands
* a trap on execution of anything in `$0000-$3FFF`, which is the bytecode window and
  which the processor should never execute; this is what caught the fault, on its
  first instruction, with `$876F` still on the stack
* the game's own counters, read out of memory: ticks, polygons, blits, loads, err
* the visible Layer 2 page as a PPM, decoded through the machine's real palette, so a
  run can be LOOKED at here rather than described over someone's shoulder

## Build and run

    mcs -target:library -r:<CSpect>/Plugin.dll -out:<CSpect>/AWProbe.dll awprobe.cs
    AWPROBE_LOG=/tmp/awprobe.txt mono CSpect.exe -w2 -sound -mouse -basickeys \
        -zxnext -mmc=<sd>/ <sd>/AW.NEX

`-sound` MUTES CSpect 3: the flag is inverted, and passing it bypasses the OpenAL
setup entirely. `AWPROBE_MAX` caps the number of one-second reports before the plugin
quits the emulator, so an unattended run cleans up after itself.
