/* Phase B gate: does compiled C call assembly at a fixed address and come back?
 *
 * Three things are under test at once and all three have to hold before any of
 * the virtual machine is written in C:
 *
 *   1. z88dk builds for +zxn on this machine at all.
 *   2. C can call an assembly routine whose address sjasmplus chose, through
 *      the jump table declared in jumptab.asm.
 *   3. Assembly can call back into C, and a C global is readable over ZRCP
 *      after tools/mkexp.py has turned z88dk's map into an .exp file.
 *
 * Deliberately not minimal: the point is to prove the ordinary path works
 * before trimming the C runtime down, which is Phase D's problem.
 */

#include <stdint.h>

/* Implemented in assembly at a fixed address - see jumptab.asm.
 * __z88dk_fastcall passes the single argument in HL rather than on the stack,
 * which is what the assembly side expects. */
extern void aw_poke(uint16_t value) __z88dk_fastcall;
extern uint16_t aw_sum(uint16_t value) __z88dk_fastcall;

/* The counter the checker watches to know C is running at all. */
volatile uint16_t cc_ticks;
/* What came back from assembly, so a wrong calling convention shows up as a
 * wrong number rather than as a hang. */
volatile uint16_t cc_returned;
volatile uint16_t cc_loops;

void c_entry(void)
{
    uint16_t i;
    for (;;) {
        /* Hand a known value to assembly; it pokes it where the checker can
         * see it, proving the argument arrived intact. */
        aw_poke(0x5AA5);

        /* And take one back: aw_sum adds 0x1111, so a correct round trip
         * leaves 0x2222 here. A stack-passed argument would give garbage. */
        cc_returned = aw_sum(0x1111);

        /* Some ordinary C work, so the build is not optimised into nothing. */
        for (i = 0; i < 16; ++i)
            cc_loops = (uint16_t)(cc_loops + i);

        ++cc_ticks;
    }
}

int main(void)
{
    c_entry();
    return 0;
}
