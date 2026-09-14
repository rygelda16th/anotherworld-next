"""One draw, through the reader harness, to split logic from slot contention.

The game stalls forever on a draw that the reference reader renders as 14 polygons nested 3
deep. The segment on the machine matches the card byte for byte, so the reader is wrong - but
the game maps the segment at $4000 through MMU2 and MMU3, and MMU2 is shared with the paged
code, the palette and the font. polytest runs the SAME reader at $0000 through MMU0 and MMU1.

  runs away here too  -> the reader's logic is wrong, and it can be bisected here
  correct here        -> the logic is fine and the game's slot arrangement is the fault
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from refvideo import RefVideo8                              # noqa: E402
from checkreadmachine import symbols, NEX, EXP, SEG_BASE, SEG_STAGE, NR_MMU0, CHUNK  # noqa

SEG = "build/assets/RES1C.BIN"
OFF, COL, ZOOM, X, Y = 0x1c82, 0xFF, 64, 160, 22


def main():
    sym = symbols(EXP)
    seg = open(SEG, "rb").read()

    ref = RefVideo8()
    ref.cur1 = 1
    ref.read_and_draw_polygon(seg, OFF, COL, ZOOM, X, Y)
    print(f"  the reference: {ref.n_polys} polygons, "
          f"{getattr(ref, 'n_reader_bad', 0)} malformed, "
          f"deepest nesting {getattr(ref, 'n_reader_depth', 0)}")

    z = Zrcp()
    z.cmd(f"smartload /work/{NEX}")
    time.sleep(4)
    z.cmd("set-memory-zone -1")
    for p in range((len(seg) + 8191) // 8192):
        z.cmd(f"tbblue-set-register {NR_MMU0} {SEG_BASE + p}")
        block = seg[p * 8192:(p + 1) * 8192]
        for o in range(0, len(block), CHUNK):
            z.cmd(f"write-memory-raw {SEG_STAGE + o} {block[o:o+CHUNK].hex()}")

    blob = (OFF.to_bytes(2, "little") + bytes([COL]) + ZOOM.to_bytes(2, "little")
            + X.to_bytes(2, "little") + Y.to_bytes(2, "little"))
    z.cmd(f"write-memory-raw {sym['rd_list']} {blob.hex()}")
    z.cmd(f"write-memory {sym['seg_base']} {SEG_BASE}")
    z.cmd(f"write-memory {sym['read_mode']} 1")
    z.cmd(f"write-memory-raw {sym['rd_count']} {(1).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory-raw {sym['rd_plimit']} {(0xFFFF).to_bytes(2, 'little').hex()}")
    z.cmd(f"write-memory {sym['go']} 1")

    done = False
    for _ in range(40):
        if z.cmd(f"read-memory {sym['done']} 1").strip().upper() == "5A":
            done = True
            break
        time.sleep(0.25)

    def w(n):
        return int.from_bytes(bytes.fromhex(z.cmd(f"read-memory {sym[n]} 2").strip()), "little")

    print(f"  the machine: finished={done}  polygons={w('rd_pcount')}  "
          f"malformed={w('rd_bad')}  too-deep={w('rd_deep')}")
    if not done:
        print("  IT RAN AWAY HERE TOO - the reader's logic is wrong, independently of the "
              "game's slots")
    elif w("rd_pcount") == ref.n_polys and not w("rd_bad") and not w("rd_deep"):
        print("  the reader is RIGHT here - so the fault is the game's slot arrangement, "
              "not the walk")
    z.close()


if __name__ == "__main__":
    main()
