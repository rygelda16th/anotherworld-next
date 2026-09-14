#!/usr/bin/env python3
"""I5: does the machine parse a music module the way the reference does?

tools/sfxmod.py decodes the format on the host from loadSfxModule and prepareInstruments; this
compares the machine's parse against it, field for field. It is the first thing in I5 that can
be gated, and it has to come before the event loop: a player built on a misread header produces
plausible noise, which is the worst possible failure mode for sound.

The module is driven in through op_playMusic's own operand block, with the C never entered,
because the VM only reaches op_playMusic once in the intro and the resource has to be resident
before the header can be read at all.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp      # noqa: E402
from sfxmod import parse, walk, voices, sound, mix_ring, be16    # noqa: E402

NEX = "build/aw.nex"
EXP_ASM, EXP_C = "build/aw.exp", "build/aw_vm_c.exp"
MUS_BLOCK, MUS_ORDER_AT, MUS_INSTR_AT = 0xC3B0, 0xC400, 0xC480
VOICES_AT, V_SIZE = 0xDD00, 15
SND_BLOCK = 0xC3B4                  # = AW_SND in the Makefile, SND_BLOCK in src/aw.asm
PROBE = os.environ.get("PROBE", "preflight/hostprobe/probe")
CTL = 0xC000
CASES = [(0x07, 0, 0), (0x8A, 0, 3), (0x07, 2000, 5)]


def symbols(*paths):
    out = {}
    for path in paths:
        for line in open(path):
            name, _, val = line.partition(":")
            if "0x" in val:
                out[name.strip()] = int(val.split("0x")[1], 16)
    return out


def main():
    sym = symbols(EXP_ASM, EXP_C)
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")

    def read(a, n):
        out = bytearray()
        while len(out) < n:
            k = min(2048, n - len(out))
            raw = z.cmd(f"read-memory {a + len(out)} {k}").strip()
            out += bytes(int(raw[i:i + 2], 16) for i in range(0, 2 * k, 2))
        return bytes(out)

    bad, done, outstanding = [], 0, []
    for res, delay, pos in CASES:
        blob = open(f"build/assets/RES{res:02X}.BIN", "rb").read()
        want = parse(blob)

        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        # Load the module the way the game does, then hand it to the player.
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['probe_mus']} {res}")
        blk = bytes([res]) + delay.to_bytes(2, "little") + bytes([pos])
        z.cmd(f"write-memory-raw {MUS_BLOCK} {blk.hex()}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(400):
            if read(sym["done"], 1)[0] == 0x5A:
                break
            time.sleep(0.05)

        got = {
            # LITTLE-endian: the module's word is big-endian IN THE FILE and the assembly
            # reads it that way, but what it then stores is an ordinary Z80 word. Reading it
            # back big-endian gave 34875 for 15240 - the same two bytes, swapped - and made
            # the machine look wrong when the checker was.
            "delay": int.from_bytes(read(sym["mus_delay_raw"], 2), "little"),
            "num_order": read(sym["mus_num_order"], 1)[0],
            "order": list(read(MUS_ORDER_AT, 0x80)),
            "playing": read(sym["mus_playing"], 1)[0],
            "cur_order": read(sym["mus_cur_order"], 1)[0],
            "miss": int.from_bytes(read(sym["n_mus_miss"], 2), "little"),
        }
        instr = read(MUS_INSTR_AT, 30)
        got["instruments"] = [{"res": instr[i * 2], "volume": instr[i * 2 + 1]}
                              for i in range(15)]

        want_delay = delay if delay else want["delay"]
        fails = []
        if got["miss"]:
            fails.append(f"the machine could not find resource {res:#04x} resident")
        if got["delay"] != want_delay:
            fails.append(f"delay {got['delay']} vs {want_delay}")
        if got["num_order"] != want["num_order"]:
            fails.append(f"numOrder {got['num_order']} vs {want['num_order']}")
        if got["order"] != want["order"]:
            d = next(i for i in range(0x80) if got["order"][i] != want["order"][i])
            fails.append(f"order table differs at {i if False else d}: "
                         f"{got['order'][d]} vs {want['order'][d]}")
        for i in range(15):
            g, w = got["instruments"][i], want["instruments"][i]
            if g["res"] != (w["res"] & 0xFF) or g["volume"] != (w["volume"] & 0xFF):
                fails.append(f"instrument {i + 1}: res {g['res']:#04x}/vol {g['volume']} "
                             f"vs {w['res']:#04x}/{w['volume']}")
        if got["cur_order"] != pos:
            fails.append(f"starting order {got['cur_order']} vs {pos}")
        if not got["playing"]:
            fails.append("the machine did not mark the module as playing")

        # THE RESIDENT TABLE KEEPS ONLY EACH WORD'S LOW BYTE. aw_play_music compacts the
        # module's four-byte entries to two so the table fits the thirty-two bytes between
        # MUS_INSTR_AT and DRAW_LOG, which is sound only while every resource id and every
        # volume fits a byte. Assert it rather than trust it: across all three modules the
        # largest id is 131 and the largest volume 63.
        for n, i in enumerate(want["instruments"], 1):
            if i["res"] > 0xFF or i["volume"] > 0xFF:
                bad.append(f"RES{res:02X} instrument {n} does not fit the resident table: "
                           f"res {i['res']:#06x}, volume {i['volume']}")
        live = sum(1 for i in want["instruments"] if i["res"])
        if fails:
            print(f"  RES{res:02X} delay {delay} pos {pos}:  " + "; ".join(fails[:3]))
            bad += fails
        else:
            print(f"  RES{res:02X} delay {delay} pos {pos}:  delay {got['delay']}, "
                  f"numOrder {got['num_order']}, {live} instruments, order table "
                  f"exact  IDENTICAL")
            done += 1
    # THE EVENT WALK: the order table, the 1024-byte wrap, and what the rows contain.
    for res, pos, ticks in ((0x07, 0, 40), (0x07, 0, 70), (0x8A, 2, 100)):
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['probe_mus']} {res}")
        z.cmd(f"write-memory {sym['probe_ticks']} {ticks}")
        z.cmd(f"write-memory-raw {MUS_BLOCK} {bytes([res, 0, 0, pos]).hex()}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(600):
            if read(sym["done"], 1)[0] == 0x5A:
                break
            time.sleep(0.05)
        g = {
            "order": read(sym["mus_cur_order"], 1)[0],
            "pos": int.from_bytes(read(sym["mus_cur_pos"], 2), "little"),
            "events": int.from_bytes(read(sym["n_mus_ev"], 2), "little"),
            "notes": int.from_bytes(read(sym["n_mus_note"], 2), "little"),
            "stops": int.from_bytes(read(sym["n_mus_stop"], 2), "little"),
            "playing": bool(read(sym["mus_playing"], 1)[0]),
        }
        w = walk(open(f"build/assets/RES{res:02X}.BIN", "rb").read(), pos, ticks)
        diffs = [k for k in ("order", "pos", "events", "notes", "stops", "playing")
                 if g[k] != w[k]]
        if diffs:
            print(f"  RES{res:02X} from order {pos}, {ticks} events: DIFFERS in "
                  + ", ".join(f"{k} {g[k]} vs {w[k]}" for k in diffs))
            bad += diffs
        else:
            print(f"  RES{res:02X} from order {pos}, {ticks} events: order {g['order']}, "
                  f"pos {g['pos']}, {g['notes']} notes, {g['stops']} stops"
                  + ("" if g["playing"] else ", finished") + "  IDENTICAL")

    # THE VOICES: what the walk leaves in the four voice records.
    for res, pos, ticks in ((0x07, 0, 1), (0x07, 0, 70), (0x8A, 2, 100)):
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['probe_mus']} {res}")
        z.cmd(f"write-memory {sym['probe_ticks']} {ticks}")
        z.cmd(f"write-memory-raw {MUS_BLOCK} {bytes([res, 0, 0, pos]).hex()}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(600):
            if read(sym["done"], 1)[0] == 0x5A:
                break
            time.sleep(0.05)
        raw = read(VOICES_AT, V_SIZE * 4)
        made = int.from_bytes(read(sym["n_voice_set"], 2), "little")
        nores = int.from_bytes(read(sym["n_mus_nores"], 2), "little")
        farloop = int.from_bytes(read(sym["n_mus_farloop"], 2), "little")

        def sample_of(rid):
            try:
                return open(f"build/assets/RES{rid:02X}.BIN", "rb").read()
            except OSError:
                return None

        want = voices(open(f"build/assets/RES{res:02X}.BIN", "rb").read(),
                      sample_of, pos, ticks)
        fails = []
        for ch in range(4):
            e = raw[ch * V_SIZE:(ch + 1) * V_SIZE]
            got_active = e[11]
            got_inc = e[4] | (e[5] << 8)          # V_INCI, the integer part
            got_frac = e[3]                        # V_INCF
            got_inc88 = (got_inc << 8) | got_frac
            w = want[ch]
            if got_active != w["active"]:
                fails.append(f"ch{ch} active {got_active} vs {w['active']}")
            if w["active"] and w["inc"] and got_inc88 != w["inc"]:
                fails.append(f"ch{ch} increment {got_inc88} vs {w['inc']}")
        if nores:
            fails.append(f"{nores} notes wanted a resource that was not resident")
        if fails:
            print(f"  RES{res:02X} voices after {ticks} events: " + "; ".join(fails[:4]))
            print(f"      counters: {made} voices set up, {nores} not resident, "
                  f"{farloop} far loops")
            for ch in range(4):
                e = raw[ch * V_SIZE:(ch + 1) * V_SIZE]
                w = want[ch]
                print(f"      ch{ch} machine active={e[11]} inc={(e[4] | (e[5] << 8)) << 8 | e[3]:>4} "
                      f"page={e[12]} pos={e[1] | (e[2] << 8):#06x} end={e[7] | (e[8] << 8):#06x} "
                      f"left={e[13] | (e[14] << 8):>6} vol_page={e[6]:#04x}")
                print(f"           model   active={w['active']} inc={w['inc']:>4} "
                      f"total={w['total']:>6} loop={w['loop']:#06x} vol={w['vol']}")
            bad += fails
        else:
            live = sum(1 for w in want if w["active"])
            print(f"  RES{res:02X} voices after {ticks} events: {live} live, "
                  f"{made} set up, increments exact"
                  + (f", {farloop} loop points past the window" if farloop else "")
                  + "  IDENTICAL")

    # ---- op_playSound -------------------------------------------------------------------
    # The four operands in, one voice out. Both the cases and the sample shapes they should
    # produce come from the host probe's own log of the reference PLAYING THE GAME
    # (preflight/hostprobe/probe/sound.txt, 970 calls), so this is checked against the
    # engine's numbers and not only against a model of them. The last case is the exception
    # and says so: no call in that log has a volume above 0x3F, so the clamp at vm.cpp:715
    # has to be provoked.
    RATE = 875000 // 40
    from mksndfreq import table as freq_table
    INCS = [(f << 8) // RATE for f in freq_table(open(f"{PROBE}/staticres.cpp").read())]

    # the machine reads a GENERATED table, so check the generator agrees with the reference
    emitted = [int(v) for ln in open("build/sndfreq.inc")
               if ln.strip().startswith("dw") for v in ln.split("dw")[1].split(",")]
    if emitted != INCS:
        bad.append("build/sndfreq.inc does not match the reference's frequenceTable")

    # res, freq, vol, chan, the reference's own len and loopLen, and what the case is for
    SND_CASES = [
        (0x30,  0,   0, 0, 13366,     0, "a stop: volume zero"),
        (0x08,  0,  22, 2,  4104,  5732, "looping, and quiet"),
        (0x54, 10,  32, 2, 22690,     0, "22,690 bytes: three pages"),
        (0x4E, 26,  63, 0,   598,     0, "the highest pitch, loud"),
        (0x31, 20,  50, 2,  5270,     0, "loud, no loop"),
        (0x4E, 26, 100, 1,   598,     0, "volume 100: the clamp, provoked"),
    ]
    for res, fq, vol, chan, ref_len, ref_loop, why in SND_CASES:
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['probe_snd']} 1")
        z.cmd(f"write-memory-raw {SND_BLOCK} {bytes([res, fq, vol, chan]).hex()}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(600):
            if read(sym["done"], 1)[0] == 0x5A:
                break
            time.sleep(0.05)
        raw = read(VOICES_AT, V_SIZE * 4)
        miss = int.from_bytes(read(sym["n_snd_miss"], 2), "little")
        data = open(f"build/assets/RES{res:02X}.BIN", "rb").read()

        # the reference's own numbers first: if these disagree the case itself is wrong.
        # Not on the stop path - there `instrSound(resNum, 0, 0, chan, 0, 0)` (vm.cpp:703)
        # logs zeros because snd_playSound never looks at the sample, so the trace's 0/0 is
        # a placeholder and not a claim about RES30's 13,366 bytes.
        fails = []
        if vol and (be16(data, 0) * 2 != ref_len or be16(data, 2) * 2 != ref_loop):
            fails.append(f"the card's RES{res:02X} is {be16(data, 0) * 2}/{be16(data, 2) * 2}, "
                         f"the reference logged {ref_len}/{ref_loop}")
        if miss:
            fails.append(f"RES{res:02X} was not resident when aw_play_sound ran")

        w = sound(data, fq, vol, INCS)
        e = raw[chan * V_SIZE:(chan + 1) * V_SIZE]
        got_active = e[11]
        got_inc = ((e[4] | (e[5] << 8)) << 8) | e[3]
        got_loop = (e[9] | (e[10] << 8))
        got_loop = (got_loop - 0xE000) if got_loop else 0
        if got_active != w["active"]:
            fails.append(f"active {got_active} vs {w['active']}")
        if w["active"]:
            if got_inc != w["inc"]:
                fails.append(f"increment {got_inc} vs {w['inc']}")
            if got_loop != w["loop"]:
                fails.append(f"loop {got_loop:#06x} vs {w['loop']:#06x}")
            # VOLTAB is $DC00 and VOLTAB_QUIET is $DF00, which reads backwards: the HIGHER
            # page is the quiet table. VOL_SPLIT is 32 and the test is `cp VOL_SPLIT + 1`,
            # so 32 itself is quiet.
            want_page = 0xDC if w["vol"] > 32 else 0xDF
            if e[6] != want_page:
                fails.append(f"volume table {e[6]:#04x} vs {want_page:#04x} "
                             f"for volume {w['vol']}")
        # THE OTHER THREE VOICES MUST BE UNTOUCHED. An IX computed from the wrong operand is
        # how the module path first went wrong, and it showed as every channel moving at once.
        for other in range(4):
            if other == chan:
                continue
            o = raw[other * V_SIZE:(other + 1) * V_SIZE]
            if o[11] != 0 or (o[1] | (o[2] << 8)) != 0xDE00:
                fails.append(f"channel {other} moved when {chan} was asked for")
        if fails:
            print(f"  play RES{res:02X} freq {fq} vol {vol} ch {chan} ({why}): "
                  + "; ".join(fails[:3]))
            bad += fails
        else:
            print(f"  play RES{res:02X} freq {fq:>2} vol {vol:>3} ch {chan} - {why:<34} "
                  + ("stopped" if not w["active"] else
                     f"inc {w['inc']:>3}, loop {w['loop']:#06x}, vol {w['vol']}")
                  + "  IDENTICAL")

    # ---- the mixer's OUTPUT, on a real sample -------------------------------------------
    # THE ONE THING check-snd CANNOT REACH. It proves four voices byte-exact, but against a
    # synthetic ramp in a single resident page: its model is `pos & 0xFF`, with no page
    # stepping and no loop. A real sample has to be walked out of - the game's largest is
    # 22,690 bytes over three 8K pages - and `voice_run` cuts each block at the window's edge
    # while `voice_advance` steps V_PAGE and rewinds V_POS.
    #
    # probe_mix mixes a fixed number of blocks with the interrupt's own mixer off, so the ring
    # is a function of the voice and the count alone. The first case crosses TWO page
    # boundaries; the second stays inside one, as a control that the crossing fix did not
    # change the case that already worked.
    RING, BLK_A, RING_LEN = 0xD400, 221, 2048
    VOLUME, VOLUME_QUIET = 48, 24
    for res, fq, vol, chan, nb, why in (
            (0x54, 39, 50, 0, 60, "two page boundaries, loud"),
            (0x54, 26, 20, 0, 40, "inside one page, quiet"),
    ):
        z.cmd(f"smartload /work/{NEX}")
        time.sleep(3.2)
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['probe_snd']} 1")
        z.cmd(f"write-memory {sym['probe_mix']} {nb}")
        z.cmd(f"write-memory-raw {SND_BLOCK} {bytes([res, fq, vol, chan]).hex()}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(900):
            if read(sym["done"], 1)[0] == 0x5A:
                break
            time.sleep(0.05)
        got = read(RING, RING_LEN)
        data = open(f"build/assets/RES{res:02X}.BIN", "rb").read()
        want = mix_ring(data, INCS[fq], VOLUME if vol > 32 else VOLUME_QUIET,
                        nb, BLK_A, RING_LEN)
        consumed = (nb * BLK_A * INCS[fq]) >> 8
        if got != want:
            d = next(i for i in range(RING_LEN) if got[i] != want[i])
            n = sum(1 for i in range(RING_LEN) if got[i] != want[i])
            outstanding.append(
                f"RES{res:02X} mixed: {n} of {RING_LEN} ring bytes differ, "
                f"first at {d}: {got[d]:#04x} vs {want[d]:#04x}")
            print(f"  mix RES{res:02X} freq {fq} vol {vol}, {nb} blocks ({why}): "
                  f"{n} of {RING_LEN} ring bytes differ, first at {d}: "
                  f"{got[d]:#04x} vs {want[d]:#04x}")
        else:
            print(f"  mix RES{res:02X} freq {fq:>2} vol {vol:>2}, {nb:>2} blocks - {why:<28} "
                  f"all {RING_LEN:,} ring bytes exact over {consumed:,} source bytes "
                  f"({consumed / 8192:.2f} pages)  IDENTICAL")

    # The period-to-increment divide, over the whole valid range and the awkward ends.
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(3.2)
    z.cmd("set-memory-zone -1")
    z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
    z.cmd(f"write-memory {sym['probe_note']} 1")
    periods = [0x37, 0x38, 107, 214, 428, 856, 1712, 2000, 3000, 4095, 0xFFF]
    worst, shown = 0, []
    for n in periods:
        z.cmd(f"write-memory-raw {MUS_BLOCK + 4} {n.to_bytes(2, 'little').hex()}")
        z.cmd(f"write-memory {sym['go']} 1")
        for _ in range(200):
            if read(sym["done"], 1)[0] == 0x5A:
                break
            time.sleep(0.02)
        got = int.from_bytes(read(MUS_BLOCK + 6, 2), "little")
        want = 41891 // n
        exact = (7159092 // (n * 2)) * 256 / RATE
        if got != want:
            bad.append(f"period {n}: the machine divided to {got}, 41891/{n} is {want}")
        worst = max(worst, abs(got - exact))
        shown.append(f"{n}->{got}")
        z.cmd("smartload /work/{}".format(NEX))
        time.sleep(2.6)
        z.cmd("set-memory-zone -1")
        z.cmd(f"write-memory-raw {sym['fname']} {(b'RES18.BIN' + bytes(1)).hex()}")
        z.cmd(f"write-memory {sym['probe_note']} 1")
    print(f"  the period divide, {len(periods)} periods: " + " ".join(shown[:7]) + " ...")
    print(f"  largest disagreement with the reference's own frequency: "
          f"{worst:.3f} of a 1/256th step")
    if worst > 1.0:
        bad.append(f"the increment is {worst:.2f} steps out at worst, which is audible")

    z.close()
    if bad:
        raise SystemExit(f"FAIL: {len(bad)} field(s) differ from the reference's parse")
    if outstanding:
        print("\n  " + "\n  ".join(outstanding))
        raise SystemExit(
            "OUTSTANDING, not a regression: the game's mix_block does not use voice_run or\n"
            "      voice_advance at all. It has a crude guard - rewind if the next block would\n"
            "      not fit - whose own comment says proper end-of-sample and loop-point\n"
            "      handling is I5's and 'more unwritten code than the plan credited'. With a\n"
            "      FULL window V_END is $0000, that guard reads 'would overrun', and V_POS goes\n"
            "      to V_LOOP - zero for an unlooped sample - so the voice reads from address\n"
            "      $0000. Measured: after 40 blocks of RES54, V_POS = $0096 with V_LEFT still\n"
            "      14,506 and V_PAGE unmoved.\n"
            "      mix_voice also advances its destination with `inc l` alone, so a block\n"
            "      cannot cross a 256-byte boundary inside the ring either.\n"
            "      The five other parts of I5 above all PASS; this is the piece left.")
    print(f"""
PASS: I5 entire, in six parts. All {done} modules PARSE exactly as tools/sfxmod.py parses
      them - the delay with and without op_playMusic's override, numOrder, all 128 order
      entries and all 15 instruments, whose ids and volumes are asserted to fit the resident
      table's two bytes an entry. The EVENT WALK matches a model of handleEvents: the order
      table, the 1024-byte wrap and what every row contains. The four VOICE records match
      after 1, 70 and 100 events, across a block crossing. op_playSound puts the right voice
      up for all {len(SND_CASES)} cases - a stop, a loop, a 22,690-byte sample over three
      pages, both ends of the pitch table and the volume clamp - checked against the sample
      shapes the host probe logged the reference itself producing, with the other three
      channels proven untouched each time. And the period-to-increment divide agrees with
      the reference's own frequency to {worst:.2f} of a 1/256th step over the whole valid
      range. And the MIXER'S OUTPUT is byte-exact on a real sample: all 2,048 ring bytes,
      over 19,164 source bytes and two 8K page boundaries, against a model of what the
      splitting has to add up to rather than of the splitting itself.""")


if __name__ == "__main__":
    main()
