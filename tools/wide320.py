#!/usr/bin/env python3
"""What would Layer 2's 320x256 mode cost? A measurement, not a port.

WHY. 256x192 scales the game's 320x200 by 205/256 across, so five columns become four and shapes a
pixel or two wide land on each other: Lester's head and arm are drawn and then painted over. The
320x256 mode (F5 in docs/where-things-stand.md) needs no scale at all - but its memory runs DOWN
the columns: a pixel's address is x * 256 + y, eight 8K pages of 32 columns each, ten of them. So
a horizontal span steps 256 bytes a pixel (`inc h` where 256x192 has `inc l`), crosses an 8K page
every 32 columns, and can no longer go to the zxnDMA, which has no stride. A page is 80K, not 48K.

THIS FILE IS THE HOST HALF. `count` replays the reference engine's traces through the same polygon
walk at both geometries - RefVideo8 (256x192, scaled, as the machine draws today) and the engine's
own 320x200 at one byte a pixel - and counts, per blit, everything whose cost differs:

    rows        spans drawn: the row walk costs the same per row in both, so only the COUNT matters
    opaque      spans, pixels, and in 256x192 the spans the DMA takes (RASTER_DMA_MIN = 96 or more)
    blend/copy  spans and pixels (0x10 and 0x11 colours: always the CPU)
    crossings   320 only: 8K pages a span crosses (32-column strips), and with two pages mapped (64)
    switches    a span in a different band (256: 32 rows) or strip (320: 32 columns) from the last
    copy/fill   bytes the DMA moves for op_copyVideoPage and op_fillVideoPage, with the machine's
                dirty-band rule (src/aw.asm dirty_band) applied per band or per strip

The machine half is preflight/wide320/: the span loops of both layouts, timed in ZEsarUX the way
check-span times today's, which gives the T-states per item. `project` multiplies the two.

    python3 tools/wide320.py count build/ref2614/trace.bin build/wide320/intro.json
    python3 tools/wide320.py count build/ref_gun3/trace.bin build/wide320/part3.json --part 2
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refvideo import RefVideo, RefVideo8, read_trace   # noqa: E402

DMA_MIN = 96            # = RASTER_DMA_MIN in src/aw.asm


def new_blit():
    return dict(rows=0, op_n=0, op_px=0, op_cpu_n=0, op_cpu_px=0, dma_n=0, dma_px=0,
                bl_n=0, bl_px=0, cp_n=0, cp_px=0, cross32=0, cross64=0, switches=0,
                points=0, polys=0, copy_bytes=0, fill_bytes=0, chars=0)


class Counting:
    """Mixin: count instead of draw. The geometry and the polygon walk are the base class's."""
    BAND = None             # 256x192: y >> 5;   320x200: x >> 5 (a strip)
    NBANDS = None
    BAND_BYTES = 8192

    def __init__(self):
        super().__init__()
        self.pages = [bytearray(1) for _ in range(4)]      # nothing is drawn
        self.b = new_blit()
        self.blits = []
        self.cur_band = None
        self.origin = [None] * 4
        self.dirty = [0] * 4

    # -- the dirty-band rule, src/aw.asm's, per band or strip --
    def _unmirror(self, p):
        for q in range(4):
            if self.origin[q] == p:
                self.origin[q] = None

    def _touch(self, bands):
        p = self.cur1
        self._unmirror(p)
        for n in bands:
            self.dirty[p] |= 1 << n

    def _band_of_span(self, a, b):
        if self.WIDE:
            return range(a >> 5, (b >> 5) + 1)
        return (self.hliney >> 5,)

    def _span(self, x1, x2, kind):
        a, b = (x1, x2) if x1 <= x2 else (x2, x1)
        n = b - a + 1
        s = self.b
        s["rows"] += 1
        first = a >> 5 if self.WIDE else self.hliney >> 5
        if first != self.cur_band:
            s["switches"] += 1
            self.cur_band = first
        if self.WIDE:
            s["cross32"] += (b >> 5) - (a >> 5)
            s["cross64"] += (b >> 6) - (a >> 6)
        if kind == "op":
            s["op_n"] += 1
            s["op_px"] += n
            if not self.WIDE and n >= DMA_MIN:
                s["dma_n"] += 1
                s["dma_px"] += n
            else:
                s["op_cpu_n"] += 1
                s["op_cpu_px"] += n
        elif kind == "bl":
            s["bl_n"] += 1
            s["bl_px"] += n
        else:
            s["cp_n"] += 1
            s["cp_px"] += n
        self._touch(self._band_of_span(a, b))

    def _span_opaque(self, x1, x2, colour):
        self._span(x1, x2, "op")

    def _span_blend(self, x1, x2, colour):
        self._span(x1, x2, "bl")

    def _span_copy(self, x1, x2, colour):
        self._span(x1, x2, "cp")

    def _point(self, colour, x, y):
        if not (0 <= x < self.W and 0 <= y < self.H):
            return
        self.b["points"] += 1
        self._touch(((x if self.WIDE else y) >> 5,))

    def fill_polygon(self, *a, **k):
        self.b["polys"] += 1
        return super().fill_polygon(*a, **k)

    def draw_char(self, ch, cx, y, colour, font):
        self.b["chars"] += 1
        if self.WIDE:
            x0, y0 = cx * 8, y
            self._touch(range(x0 >> 5, ((x0 + 7) >> 5) + 1))
        else:
            x0, y0 = cx * 6, self.sy(y)
            self._touch(range(y0 >> 5, (min(y0 + 7, self.H - 1) >> 5) + 1))

    def fill_page(self, page, colour):
        p = self._page_index(page)
        self._unmirror(p)
        self.origin[p] = None
        self.b["fill_bytes"] += self.NBANDS * self.BAND_BYTES
        self.cur_band = None

    def copy_page(self, src, dst, vscroll):
        if src == dst:
            return
        if not (src >= 0xFE or not ((src & 0xBF) & 0x80)):
            return              # the scrolled form: the machine does not implement it either
        s = self._page_index(src & 0xBF if src < 0xFE else src)
        d = self._page_index(dst)
        if s == d:
            return
        self._unmirror(d)
        mask = self.dirty[d] if self.origin[d] == s else (1 << self.NBANDS) - 1
        self.origin[d] = s
        self.dirty[d] = 0
        self.b["copy_bytes"] += bin(mask).count("1") * self.BAND_BYTES
        self.cur_band = None

    def select(self, page):
        super().select(page)
        self.cur_band = None

    def blit(self, page):
        super().blit(page)
        self.blits.append(self.b)
        self.b = new_blit()


class Count256(Counting, RefVideo8):
    WIDE = False
    NBANDS = 6


class Count320(Counting, RefVideo):
    """The engine's own 320x200, unscaled, at one byte a pixel: 320x256's memory, 200 rows used."""
    WIDE = True
    NBANDS = 10                 # 80K: ten 8K strips of 32 columns
    W, H = 320, 200

    def _draw_polygon(self, colour, ptx, pty, bbw, bbh, points):
        self.fill_polygon(colour, ptx, pty, bbw, bbh, points)


def run(cls, path, part):
    v = cls()
    seen = 0
    for kind, a in read_trace(path):
        if part is not None and seen < part:
            if kind == "part":
                seen += 1
            continue
        if kind == "poly":
            v.cur1 = a["page"]
            v._draw_polygon(a["colour"], a["px"], a["py"], a["bbw"], a["bbh"], a["points"])
        elif kind == "fill":
            v.fill_page(a["page"], a["colour"])
        elif kind == "copy":
            v.copy_page(a["src"], a["dst"], a["vscroll"])
        elif kind == "select":
            v.select(a["page"])
        elif kind == "char":
            v.cur1 = a["page"]
            v.draw_char(a["ch"], a["cx"], a["y"], a["colour"], None)
        elif kind == "blit":
            v.blit(a["page"])
    return v.blits


def count(trace, out, part):
    narrow = run(Count256, trace, part)
    wide = run(Count320, trace, part)
    assert len(narrow) == len(wide), "the two replays saw a different number of blits"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump({"trace": trace, "part": part, "n256": narrow, "n320": wide}, open(out, "w"))
    tot = lambda bs, k: sum(b[k] for b in bs)
    print(f"{trace}: {len(narrow)} blits")
    for k in ("rows", "op_px", "dma_px", "op_cpu_px", "bl_px", "cp_px", "cross32", "cross64",
              "switches", "copy_bytes", "fill_bytes"):
        a, b = tot(narrow, k), tot(wide, k)
        print(f"  {k:<11}{a:>14,}{b:>14,}" + (f"   x{b / a:.2f}" if a else ""))


# ---- the machine half: preflight/wide320/wide.asm, timed in ZEsarUX ---------------------------
L2P0 = 24
MODES = {0: "NULL", 1: "256 opaque (CPU)", 2: "256 blend", 3: "256 opaque (DMA)",
         4: "320 opaque", 5: "320 blend", 6: "320/64 opaque"}


def lsq(rows):
    """Least squares for y = sum(c_i * x_i): rows of (xs, y). Gaussian elimination, no numpy."""
    k = len(rows[0][0])
    a = [[sum(r[0][i] * r[0][j] for r in rows) for j in range(k)] for i in range(k)]
    b = [sum(r[0][i] * r[1] for r in rows) for i in range(k)]
    for i in range(k):
        p = max(range(i, k), key=lambda r: abs(a[r][i]))
        a[i], a[p] = a[p], a[i]
        b[i], b[p] = b[p], b[i]
        for r in range(k):
            if r != i and a[i][i]:
                f = a[r][i] / a[i][i]
                a[r] = [x - f * y for x, y in zip(a[r], a[i])]
                b[r] -= f * b[i]
    return [b[i] / a[i][i] for i in range(k)]


def machine(out):
    import statistics
    import time
    from zrcp import Zrcp
    sym = {}
    for line in open("build/wide320.exp"):
        name, _, val = line.partition(":")
        if "0x" in val:
            sym[name.strip()] = int(val.split("0x")[1], 16)
    z = Zrcp()
    print(f"emulator: {z.cmd('get-version')}")
    z.cmd("smartload /work/build/wide320.nex")
    time.sleep(3)
    z.cmd("set-memory-zone -1")
    rd = lambda a, n: bytes.fromhex(z.cmd(f"read-memory {a} {n}").strip())
    w16 = lambda a, v: z.cmd(f"write-memory-raw {a} {v.to_bytes(2, 'little').hex()}")
    if rd(sym["ready"], 1)[0] != 0x5A:
        raise SystemExit("FAIL: the harness never started")
    passes = lambda: int.from_bytes(rd(sym["passes"], 2), "little")

    def setup(mode, x, n):
        z.cmd(f"write-memory {sym['mode']} {mode}")
        w16(sym["bench_x"], x)
        w16(sym["bench_len"], n)
        b = passes()
        while passes() - b < 2:          # a whole pass with the new values
            time.sleep(0.01)

    def pixel(x, y, wide):
        """The byte a pixel lands in, read from physical RAM: ZEsarUX's zone 0 holds 8K page p at
        (p + 32) * 8192. Reading through MMU7 with the harness held came back wrong."""
        page, off = (L2P0 + (x >> 5), ((x & 31) << 8) + y) if wide else (L2P0 + (y >> 5), ((y & 31) << 8) + x)
        z.cmd("set-memory-zone 0")
        v = rd((page + 32) * 8192 + off, 1)[0]
        z.cmd("set-memory-zone -1")
        return v

    # CORRECTNESS FIRST: every mode paints exactly its span, its own colour, at y = 5
    bad = []
    for mode, x, n in ((1, 30, 100), (3, 20, 200), (2, 30, 100), (4, 21, 150), (6, 50, 200), (5, 21, 150)):
        wide = mode >= 4
        setup(mode, x, n)
        z.cmd(f"write-memory {sym['mode']} 0")    # NULL: nothing moves while it is read
        time.sleep(0.1)
        for px in (x, x + 1, x + n // 2, x + n - 1, x - 1, x + n):
            v = pixel(px, 5, wide)
            inside = x <= px < x + n
            if mode in (2, 5):
                ok = (v & 8) == 8 if inside else True
            else:
                ok = (v == 0x20 + mode) if inside else v != 0x20 + mode
            if not ok:
                bad.append(f"mode {mode} ({MODES[mode]}) x={px}: {v:#04x}")
    if bad:
        raise SystemExit("FAIL: a span lands in the wrong place\n  " + "\n  ".join(bad))
    print("every mode paints its own span and nothing beside it")

    def cost(mode, x, n, k=6):
        setup(mode, x, n)
        out = []
        for _ in range(3):
            b = passes()
            while passes() == b:
                time.sleep(0.002)
            z.cmd("reset-tstates-partial")
            b0 = passes()
            while passes() - b0 < k:
                time.sleep(0.005)
            t = int(z.cmd("get-tstates-partial").strip())
            out.append(t / ((passes() - b0) * 192))
        return statistics.median(out)

    null = cost(0, 0, 8, k=20)
    print(f"the harness loop alone: {null:.1f} T a span (subtracted)")
    pts = {m: [] for m in MODES if m}
    for n in (2, 8, 16, 32, 64, 128, 200, 256):
        for m in (1, 2):
            pts[m].append(((1, n, 0), cost(m, 0, n) - null))
    for n in (96, 128, 200, 256):
        pts[3].append(((1, n, 0), cost(3, 0, n) - null))
    for x in (0, 16, 40):
        for n in (2, 8, 16, 32, 64, 128, 256, 320 - x):
            for m, w in ((4, 32), (5, 32), (6, 64)):
                cross = ((x + n - 1) // w) - (x // w)
                pts[m].append(((1, n, cross), cost(m, x, n) - null))
    fits = {}
    for m, rows in pts.items():
        if m in (1, 2, 3):
            a, b = lsq([((xs[0], xs[1]), y) for xs, y in rows])
            fits[m] = dict(entry=a, per_px=b, per_cross=0.0)
        else:
            a, b, c = lsq(rows)
            fits[m] = dict(entry=a, per_px=b, per_cross=c)
        worst = max(abs(y - (fits[m]["entry"] + fits[m]["per_px"] * xs[1] + fits[m]["per_cross"] * xs[2]))
                    for xs, y in rows)
        print(f"  {MODES[m]:<18} {fits[m]['entry']:7.1f} T a span + {fits[m]['per_px']:5.2f} T a pixel"
              f" + {fits[m]['per_cross']:6.1f} T a crossing   (worst point off the fit by {worst:.0f} T)")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"null": null, "fits": {str(k): v for k, v in fits.items()},
               "points": {str(k): v for k, v in pts.items()}}, open(out, "w"), indent=1)
    print(f"wrote {out}")


def idle(out, part=None, seed=None, blits=2613):
    """One silent CSpect run with tools/cspect/awidle.cs sampling, at every interrupt, whether the
    game was waiting. speed.py runs CSpect; this only adds AwIdle's variables. With `part` (an
    index, as the probe takes it) the run starts in that part with the synthetic player on and the
    reference run's seed, as check-draw does."""
    import shutil
    import subprocess
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "cspect"))
    import speed
    wide = bool(os.environ.get("AW_WIDE"))           # the 320x256 build itself (W4)
    nex, exp, lstf = (("build/aw320.nex", "build/aw320.exp", "build/aw320.lst") if wide
                      else ("build/aw.nex", "build/aw.exp", "build/aw.lst"))
    if os.environ.get("AW_NEX"):                    # a copy, while a gate rebuilds the originals
        nex, exp, lstf = os.environ["AW_NEX"], os.environ["AW_EXP"], os.environ["AW_LST"]
    sym = speed.symbols(exp)
    lst = open(lstf).read().split("\n")

    def at(label):
        for line in lst:
            f = line.split()
            if len(f) >= 3 and (label + ":") in f[2:5] and not line.lstrip().startswith(";"):
                return int(f[1], 16)
        raise SystemExit(f"{label} is not in build/aw.lst")
    rngs = [(at("pace_blit"), at("pace_due")),          # the wait
            (at("snd_idle"), at("snd_idle") + 0x1F),     # what the wait calls
            (at("paged_call"), at("paged_call") + 0x16),
            (0x5100, 0x53A0)]                            # page 10's stream reader, called by it
    dll = os.path.join(speed.CSPECT, "AwIdle.dll")
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cspect", "awidle.cs")
    if not os.path.exists(dll) or os.path.getmtime(dll) < os.path.getmtime(src):
        subprocess.check_call(["mcs", "-target:library", "-r:" + os.path.join(speed.CSPECT, "Plugin.dll"),
                               "-out:" + dll, src])
    log = "/tmp/awidle.txt"
    env = dict(AWIDLE_LOG=log, AWIDLE_BLIT=f"{sym['n_blit']:X}", AWIDLE_TICKS=f"{sym['ticks']:X}",
               AWIDLE_RANGES=",".join(f"{a:X}-{b:X}" for a, b in rngs))
    if part is not None:
        ctl = 0xC000
        env["AWPROBE_POKE"] = (f"{sym['start_part']:X}={part + 1:X},{sym['autoplay']:X}=1,"
                               f"{ctl:X}={seed & 255:X},{ctl + 1:X}={seed >> 8:X}")
    pace = speed.run(nex, exp, blits, 900, env)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    shutil.copy(log, out)
    shutil.copy(pace, out + ".pace")
    print(f"wrote {out} and {out}.pace")


def isr(out, part=None, seed=None, seconds=90, samples=1500):
    """The sound interrupt's share of the machine, in ZEsarUX, where it can be timed: the emulator is
    stopped at random moments and asked whether interrupts are off. The interrupt runs with them off
    from its first instruction to its EI; the main code's own DIs (a NextReg read, a card read) are
    a few instructions, and the card reads are counted apart by their addresses (page 10)."""
    import random
    import time
    from zrcp import Zrcp
    sym = {}
    for path in ("build/aw.exp", "build/aw_vm_c.exp"):
        for line in open(path):
            name, _, val = line.partition(":")
            if "0x" in val:
                sym[name.strip()] = int(val.split("0x")[1], 16)
    z = Zrcp()
    z.cmd("smartload /work/build/aw.nex")
    time.sleep(3.5)
    z.cmd("set-memory-zone -1")
    if part is not None:
        z.cmd(f"write-memory {sym['start_part']} {part + 1}")
        if part != 1:                           # the intro (index 1) takes no input
            z.cmd(f"write-memory {sym['autoplay']} 1")
        # the control block, as check-draw writes it: the seed, a frame cap and an opcode budget. All
        # zero, as smartload leaves it in ZEsarUX, and the VM runs no frames at all.
        hdr = (seed & 0xFFFF).to_bytes(2, "little") + (60000).to_bytes(2, "little") + (60000).to_bytes(2, "little")
        z.cmd(f"write-memory-raw {0xC000} {hdr.hex()}")
    z.cmd(f"write-memory {sym['go']} 1")
    time.sleep(20)
    if int.from_bytes(bytes.fromhex(z.cmd(f"read-memory {sym['n_blit']} 2").strip()), "little") < 20:
        raise SystemExit("FAIL: the game is not drawing - nothing to sample")                              # past the boot, the part's loads and the card's probe
    n = off = paged = 0
    rnd = random.Random(1)
    t_end = time.time() + seconds
    while n < samples and time.time() < t_end:
        time.sleep(rnd.uniform(0.0, 2 * seconds / samples))
        z.cmd("enter-cpu-step")
        r = z.cmd("get-registers")
        z.cmd("exit-cpu-step")
        f = dict(t.split("=", 1) for t in r.split() if "=" in t)
        pc = int(f["PC"], 16)
        iff = "IFF1" in r or "IFF12" in r
        n += 1
        if not iff:
            if 0x4000 <= pc < 0x6000:
                paged += 1
            else:
                off += 1
    share = off / n
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump({"part": part, "samples": n, "isr": off, "paged_di": paged, "share": share}, open(out, "w"))
    print(f"{'the intro' if part is None else f'part index {part}'}: the interrupt ran at {off} of {n} "
          f"samples, {100 * share:.1f}% of the machine (+-{100 * (share * (1 - share) / n) ** 0.5:.1f}); "
          f"the card reads at {paged}")


# ---- the projection ------------------------------------------------------------------------------
FRAME_T = 560_000           # T-states in a 50 Hz tick at 28 MHz
DMA_T = 4.0                 # T a byte the zxnDMA costs as CSpect emulates it; ZEsarUX charges nothing
ROW_T = 250                 # the row walk's own cost a row (edge steps ~148 T, clip and band ~100)
PACE_DEBT = 100             # = PACE_DEBT in src/aw.asm


def price(b, f, wide, win=32):
    """T-states of the drawing that DIFFERS between the layouts, for one blit's counts."""
    t = (b["copy_bytes"] + b["fill_bytes"]) * DMA_T + b["rows"] * ROW_T
    if not wide:
        o, bl, d = f["1"], f["2"], f["3"]
        return (t + b["op_cpu_n"] * o["entry"] + b["op_cpu_px"] * o["per_px"]
                + b["dma_n"] * d["entry"] + b["dma_px"] * DMA_T
                + b["bl_n"] * bl["entry"] + b["bl_px"] * bl["per_px"])
    o, bl = (f["6"], f["5"]) if win == 64 else (f["4"], f["5"])
    cross = b["cross64"] if win == 64 else b["cross32"]
    return (t + b["op_n"] * o["entry"] + b["op_px"] * o["per_px"] + cross * o["per_cross"]
            + b["bl_n"] * bl["entry"] + b["bl_px"] * bl["per_px"])


def pace(busy, pauses, first, last):
    """pace_blit, simulated: each blit's work, then its deadline, a debt of PACE_DEBT ticks at most."""
    t = due = 0.0
    for r in range(first, last + 1):
        t += busy.get(r, 0.0)
        due += pauses[r]
        if t < due:
            t = due
        elif t - due > PACE_DEBT:
            due = t
    return t


def project(counts, coeff, idle_log, frames):
    d = json.load(open(counts))
    f = json.load(open(coeff))["fits"]
    pauses = [int(l.split()[6]) for l in open(frames) if not l.startswith("#")]
    ref_first = next(i for i, b in enumerate(d["n256"]) if b["polys"])
    # the machine's busy ticks per blit: samples between two blits less the idle ones, two a tick
    rows = [tuple(map(int, l.split())) for l in open(idle_log) if not l.startswith("#")]
    pace_rows = [l.split() for l in open(idle_log + ".pace") if not l.startswith("#")]
    polys = {}
    for p in pace_rows:
        polys.setdefault(int(p[0]), int(p[3]))
    base = polys[min(polys)]
    mach_first = min(b for b in polys if polys[b] > base + 1)
    off = mach_first - ref_first
    busy = {}
    for (b0, _, s0, i0), (b1, _, s1, i1) in zip(rows, rows[1:]):
        busy[b1 - off] = ((s1 - s0) - (i1 - i0)) / 2.0
    first, last = 5, min(len(d["n256"]), len(pauses)) - 1
    ref = sum(pauses[first + 1:last + 1])
    now = pace(busy, pauses, first, last)
    print(f"aligned: reference blit {ref_first} is the machine's {mach_first}")
    print(f"the original, blits {first}-{last}: {ref * 0.02:.1f} s")
    print(f"today's machine, simulated from its own busy time: {now * 0.02:.1f} s "
          f"({100 * ref / now:.1f}% of the original)  - speed.py measured 100.2%")
    for label, wide, win in (("320x256, 32-column window", True, 32), ("320x256, 64-column window", True, 64)):
        extra = {r: (price(d["n320"][r], f, True, win) - price(d["n256"][r], f, False)) / FRAME_T
                 for r in range(len(d["n256"]))}
        b2 = {r: busy.get(r, 0.0) + extra.get(r, 0.0) for r in range(first, last + 1)}
        t = pace(b2, pauses, first, last)
        print(f"{label}: {sum(extra.values()) * 0.02:+.1f} s of drawing; the intro takes {t * 0.02:.1f} s "
              f"({100 * ref / t:.1f}% of the original)")
        worst = sorted(((extra[r], r) for r in extra), reverse=True)[:5]
        print("   heaviest blits: " + ", ".join(f"{r} +{x:.1f} ticks (busy {busy.get(r, 0):.0f})" for x, r in worst))


def opt(name, default=None):
    return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def project_part(counts, coeff, idle_log, frames, isr_json):
    """The same for a gameplay part: the probe ran the intro's first frames, then jumped, so the
    part's blits are the frames.txt rows after part 1's. The machine started in the part itself."""
    d = json.load(open(counts))
    f = json.load(open(coeff))["fits"]
    share = json.load(open(isr_json))["share"]
    rows = [l.split() for l in open(frames) if not l.startswith("#")]
    pauses = [int(r[6]) for r in rows if r[0] != "1"]
    assert len(pauses) == len(d["n256"]), "frames.txt and the counts disagree on the part's blits"
    ref_first = next(i for i, b in enumerate(d["n256"]) if b["polys"])
    log = [tuple(map(int, l.split())) for l in open(idle_log) if not l.startswith("#")]
    pace_rows = [l.split() for l in open(idle_log + ".pace") if not l.startswith("#")]
    polys = {}
    for p in pace_rows:
        polys.setdefault(int(p[0]), int(p[3]))
    mach_first = min(b for b in polys if polys[b] > polys[min(polys)])
    off = mach_first - ref_first
    busy = {}
    for (b0, _, s0, i0), (b1, _, s1, i1) in zip(log, log[1:]):
        busy[b1 - off] = ((s1 - s0) - (i1 - i0)) / 2.0
    first = ref_first + 1
    last = min(len(pauses) - 1, max(busy))
    ref = sum(pauses[first + 1:last + 1])
    now = pace(busy, pauses, first, last)
    print(f"aligned: the part's blit {ref_first} is the machine's {mach_first}; blits {first}-{last}")
    print(f"the original: {ref * 0.02:.1f} s.  today's machine, simulated: {now * 0.02:.1f} s "
          f"({100 * ref / now:.1f}% of the original)")
    out = {"ref_s": ref * 0.02, "now_s": now * 0.02}
    for win in (32, 64):
        extra = {r: (price(d["n320"][r], f, True, win) - price(d["n256"][r], f, False)) / FRAME_T / (1 - share)
                 for r in range(len(d["n256"]))}
        b2 = {r: busy.get(r, 0.0) + extra.get(r, 0.0) for r in range(first, last + 1)}
        t = pace(b2, pauses, first, last)
        print(f"320x256, {win}-column window: {sum(extra[r] for r in range(first, last + 1)) * 0.02:+.1f} s of "
              f"drawing (the interrupt's {100 * share:.1f}% counted); {t * 0.02:.1f} s "
              f"({100 * ref / t:.1f}% of the original)")
        out[f"w{win}_s"] = t * 0.02
    return out


def measured_part(frames, *idle_logs):
    """A gameplay part's MEASURED speed, from CSpect runs' pace logs (tools/wide320.py idle --part):
    the original's pauses over the part's blits against the machine's ticks over the same blits,
    aligned on the first picture as project_part does. One line a log, so builds compare."""
    rows = [l.split() for l in open(frames) if not l.startswith("#")]
    pauses = [int(r[6]) for r in rows if r[0] != "1"]
    ref_first = next(i for i, r in enumerate(r for r in rows if r[0] != "1") if int(r[2]) > 0)
    for log in idle_logs:
        pace_rows = [l.split() for l in open(log + ".pace") if not l.startswith("#")]
        ticks, polys = {}, {}
        for p in pace_rows:
            ticks.setdefault(int(p[0]), int(p[1]))
            polys.setdefault(int(p[0]), int(p[3]))
        mach_first = min(b for b in polys if polys[b] > polys[min(polys)])
        off = mach_first - ref_first
        last = min(len(pauses) - 1, max(ticks) - off - 1)
        first = ref_first + 1
        ref = sum(pauses[first + 1:last + 1])
        def at(b):                      # the log skips a blit when two land in one frame
            while b not in ticks:
                b += 1
            return ticks[b]
        got = at(last + off) - at(first + off)
        print(f"{log}: blits {first}-{last}: the original {ref * 0.02:.1f} s, the machine {got * 0.02:.1f} s, "
              f"{100 * ref / got:.1f}% of the original")


def main():
    if len(sys.argv) >= 4 and sys.argv[1] == "measured-part":
        measured_part(sys.argv[2], *sys.argv[3:])
        return
    if len(sys.argv) >= 7 and sys.argv[1] == "project-part":
        project_part(*sys.argv[2:7])
        return
    if len(sys.argv) >= 3 and sys.argv[1] == "isr":
        isr(sys.argv[2], opt("--part"), opt("--seed"))
    elif len(sys.argv) >= 6 and sys.argv[1] == "project":
        project(*sys.argv[2:6])
    elif len(sys.argv) >= 3 and sys.argv[1] == "idle":
        idle(sys.argv[2], opt("--part"), opt("--seed"), opt("--blits", 2613))
    elif len(sys.argv) >= 3 and sys.argv[1] == "machine":
        machine(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "count":
        part = int(sys.argv[sys.argv.index("--part") + 1]) if "--part" in sys.argv else None
        count(sys.argv[2], sys.argv[3], part)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
