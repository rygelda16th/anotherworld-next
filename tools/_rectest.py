"""Exercise tools/record.py without a person at the keyboard.

The recorder is meant to watch a human play, so nothing about a normal run tests it. This
starts the game with the synthetic player, then hands over to record.main() for a bounded
window - which checks the part detection, the polygon-per-frame arithmetic and the comparison
against preflight's per-part table all actually work before anyone relies on them.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zrcp import Zrcp                                       # noqa: E402
from checksave import symbols, NEX, EXP                          # noqa: E402

z = Zrcp()
sym = symbols(EXP)
z.cmd(f"smartload /work/{NEX}")
time.sleep(3.2)
z.cmd("set-memory-zone -1")
z.cmd(f"write-memory {sym['start_part']} 3")        # part 2, where there is drawing to weigh
z.cmd(f"write-memory {sym['autoplay']} 1")
z.cmd(f"write-memory {sym['go']} 1")
z.close()
time.sleep(2.0)

os.environ.setdefault("AW_RECORD_S", "24")
import record                                              # noqa: E402
record.main()
