#!/usr/bin/env python3
"""checkgus.py - plan-pi-gus.md's A1 gate (make check-gus): the Pi card's files for this game.

nextpi-gus's card on the Mac (NEXTPI_GUS/build/mac/ngus) is given H, then build/assets/GUSALL.GUS as
the boot will send it, then E, and dumps its memory. Then:

  1. every one of the 97 sounds is in the card's memory at the address build/gusdata.inc gives,
     byte for byte THIS repo's own resource (build/assets/RES<id>.BIN, after its 8-byte header,
     its length and its loop), and its table entry says so (the loop from the header's length);
  2. the card's CRC-32 of that memory is gusdata.inc's (what the boot's %M must match);
  3. each RES<id>.GUS alone fills its own sound, and nothing else;
  4. GUSALL.GUS's lines are all valid (no bad line) and it is every block once, 0 to n-1;
  5. the copies in src/inc/gus/ are nextpi-gus's files, and gusdata.inc's pins are the files'.
FAIL: lines and exit 1 on a failure; RESULT: ALL PASS otherwise.
"""
import os
import re
import struct
import subprocess
import sys
import zlib

GUS = os.environ.get("NEXTPI_GUS", os.path.expanduser("~/src/nextpi-gus"))
sys.path.insert(0, os.path.join(GUS, "tools"))
import gus_proto as g   # noqa: E402

FAILS = []


def check(ok, what, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {what}" + (f"  [{detail}]" if detail else ""), flush=True)
    if not ok:
        FAILS.append(what)
        print(f"FAIL: {what}" + (f" ({detail})" if detail else ""), flush=True)
    return ok


def card(body, tag):
    path = f"build/gus-{tag}.gus"
    open(path, "w").write(g.Encoder().hello(mem_kb=1024) + body + g.line("E", 1, ""))
    r = subprocess.run([os.path.join(GUS, "build/mac/ngus"), "--wav", "/dev/null", "--in", path,
                        "--dump-mem", f"build/gus-{tag}.mem", "--bad-log", f"build/gus-{tag}.bad"],
                       capture_output=True, text=True)
    return r.returncode, r.stderr, open(f"build/gus-{tag}.mem", "rb").read()


def main():
    inc = open("build/gusdata.inc").read()
    val = lambda n: int(re.search(rf"^{n}\s+EQU \$?([0-9A-Fa-f]+)", inc, re.M).group(1),
                           16 if re.search(rf"^{n}\s+EQU \$", inc, re.M) else 10)
    blocks = val("GUS_BLOCKS")
    length = val("GUS_LEN_LO") | (val("GUS_LEN_HI") << 16)
    crc = val("GUS_CRC_LO") | (val("GUS_CRC_HI") << 16)
    table = bytes(int(x, 16) for x in re.findall(r"\$([0-9A-F]{2})", inc.split("MACRO GUS_ADDR_TABLE")[1]))
    addr = {i: table[3 * i] | (table[3 * i + 1] << 8) | (table[3 * i + 2] << 16) for i in range(146)}
    body = open("build/assets/GUSALL.GUS").read()
    rc, err, mem = card(body, "all")
    print(f"1. GUSALL.GUS through the card ({len(body):,} characters)")
    sounds, bad = 0, []
    for i in range(146):
        f = f"build/assets/RES{i:02X}.BIN"
        if not addr[i]:
            continue
        r = open(f, "rb").read()
        ln, lp = struct.unpack_from(">HH", r, 0)
        n = (ln + lp) * 2
        data = r[8:8 + n]
        ent = mem[16 * i:16 * i + 16]
        start, length_s, ls, ll = struct.unpack("<IIII", ent)
        ok = start == addr[i] and mem[start:start + len(data)] == data and length_s == len(data) \
            and ll == (lp * 2) and (ls == ln * 2 if lp else True)
        sounds += 1
        if not ok:
            bad.append(i)
    check(rc == 0 and sounds == 97 and not bad,
          f"all {sounds} sounds are in the card's memory at gusdata.inc's addresses, byte for byte this repo's "
          "RES<id>.BIN, each with its table entry (length, loop)", f"bad {bad[:5]}; {err.strip()[-80:]}")
    check(zlib.crc32(mem[:length]) & 0xFFFFFFFF == crc and not any(mem[length:]),
          f"the card's CRC-32 of its {length:,} bytes is gusdata.inc's ({crc:08X}), and nothing is written past them")
    check("0 bad" in err and os.path.getsize("build/gus-all.bad") == 0, "no bad line in GUSALL.GUS", err.strip()[-80:])
    nums = [g.unitem(l, 3) for l in body.splitlines() if l[1] == "U"]
    check(nums == list(range(blocks)), f"GUSALL.GUS is every block once, 0 to {blocks - 1}")
    print("\n2. one sound at a time")
    ok_all, n = True, 0
    for i in (0x5A, 0x05, 0x69):
        f = f"build/assets/RES{i:02X}.GUS"
        if not os.path.exists(f):
            continue
        rc, err, m1 = card(open(f).read(), f"res{i:02X}")
        r = open(f"build/assets/RES{i:02X}.BIN", "rb").read()
        ln, lp = struct.unpack_from(">HH", r, 0)
        data = r[8:8 + (ln + lp) * 2]
        a = addr[i]
        ok_all &= m1[a:a + len(data)] == data and not any(m1[:a]) and not any(m1[a + len(data):])
        n += 1
    check(n == 3 and ok_all, "RES5A.GUS, RES05.GUS and RES69.GUS alone: each fills its own sound and nothing else")
    print("\n3. the copies and the pins")
    same = all(open(f"src/inc/gus/{f}").read().split("\n", 3)[3] == open(os.path.join(GUS, "src/next", f)).read()
               for f in ("gus.inc", "piuart.inc"))
    check(same, "src/inc/gus/gus.inc and piuart.inc are nextpi-gus's, bar their three-line header")
    pins = re.findall(r"(\S+) (\d+ \d+)", inc.split("\n")[1] + " " + inc.split("\n")[2])
    now = {"GUSALL.GUS": "build/assets/GUSALL.GUS", "GUSINST.TXT": "build/assets/GUSINST.TXT",
           "gus.inc": "src/inc/gus/gus.inc", "piuart.inc": "src/inc/gus/piuart.inc"}
    ok = True
    for name, ck in pins:
        name = name.rstrip(";")
        r = subprocess.run(["cksum", now[name]], capture_output=True, text=True)
        ok &= " ".join(r.stdout.split()[:2]) == ck
    check(ok and len(pins) == 4, f"gusdata.inc's four pins are the files' cksums", f"{pins}")
    print()
    if FAILS:
        print(f"RESULT: {len(FAILS)} FAILED")
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
