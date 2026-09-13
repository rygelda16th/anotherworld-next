/* The Another World virtual machine, in plain C.
 *
 * A transcription of VirtualMachine from the GPL lineage (awbi/src/vm.cpp), with
 * every operand length and every initial variable taken from there and cited in
 * docs/where-things-stand.md. Measurement says C is the right language for this:
 * the worst frame the game produces dispatches 509 opcodes, which at the measured
 * 400 T a dispatch is 9% of the pause the scripts ask for.
 *
 * WHAT IS DELIBERATELY NOT HERE
 *   The rasteriser and the polygon reader. Those are Z80N and already gated
 *   pixel-exact; this calls them through the jump table at $8000 that Gate B
 *   proved. Nothing in C touches a framebuffer.
 *
 * THE BYTECODE WINDOW
 *   A thread's program counter is a flat 16-bit offset and the largest bytecode
 *   segment in the game is 62,683 bytes, so it cannot be mapped linearly into a
 *   64K space that also holds this code. Two 8K pages are mapped at a time, so a
 *   16K span is addressable and the window only moves when the pc leaves it. The
 *   check is two comparisons on a fetch, not a call.
 */

#include <stdint.h>

/* ---- the assembly side, through the jump table Gate B proved -------------- */
extern uint8_t *aw_code_window(uint16_t off) __z88dk_fastcall;
extern void aw_draw_poly(void) __z88dk_fastcall;      /* reads aw_draw_* below */
extern void aw_select_page(uint8_t page) __z88dk_fastcall;
extern void aw_fill_page(uint16_t packed) __z88dk_fastcall;   /* page | col<<8 */
extern void aw_copy_page(uint16_t packed) __z88dk_fastcall;   /* src | dst<<8 */
extern void aw_blit(uint8_t page) __z88dk_fastcall;
extern void aw_set_palette(uint8_t id) __z88dk_fastcall;
/* The frame boundary. In the harness it returns at once; in the game it waits for
 * the frame interrupt's tick and refills the sound ring - so the C keeps owning the
 * frame loop that Gate D checks, and the game still gets its pacing and its sound,
 * without two frame loops that can disagree. */
extern void aw_frame_sync(void);
/* I3. The harness's are `ret`s; the game's load a resource and forget them all. */
extern void aw_load_res(uint16_t id) __z88dk_fastcall;
extern void aw_inval_res(void);
/* The two shared regions are named by PLAIN ADDRESS CONSTANTS, not by extern
 * symbols declared with defc. That is the third arrangement tried and the first
 * that is unambiguous.
 *
 * The trace log went through the jump table first, as one packed argument and then
 * as three entries, and mislabelled its first record both times. Then both regions
 * were declared `extern uint8_t x[]` against a `defc`, and the control block read
 * back four different addresses as the same value - which is what happens if the
 * compiler takes the symbol as a pointer VARIABLE living at that address rather
 * than as the address itself.
 *
 * A cast integer constant cannot be read either way. It also needs no jumptab
 * entry, no map lookup and no agreement between two assemblers - and the addresses
 * are fixed by construction in src/vmtest.asm, which is the same guarantee the
 * jump table at $8000 rests on.
 *
 * volatile, because the checker writes these while the machine is stopped and the
 * compiler must not cache them across the frame loop.
 */
/* THE CONTROL VALUES LIVE IN THE SAME BLOCK, and the whole block goes out through
 * a FILE rather than being read out of memory.
 *
 * That is the change that closes Gate D. Every previous arrangement had the checker
 * read the C's state over the debug protocol, and the results were not repeatable -
 * the same inputs gave 0, 64, 122 and 354 matching records on different runs. One
 * cause was found (smartload does not clear RAM, so statics do not start at zero)
 * and fixed, and it was not sufficient.
 *
 * So the channel goes. The C writes everything into one 8K block at $C000 - which
 * it has demonstrably always been able to write, since records appeared there
 * correctly - and the assembly writes that block to a file through esxDOS after
 * main returns. Step 5 proved that path byte-exact. A file either holds the records
 * or it does not; there is nothing left to be flaky.
 *
 * The header is sixteen bytes: the checker pokes the first six, the C writes the
 * rest, and the records start after it.
 */
/* WHERE THE CONTROL BLOCK AND THE EXPECTED STREAM LIVE is a build choice, because
 * the harness and the game cannot both have them at the same address.
 *
 * The harness has $C000-$DFFF and $E000-$FFFF spare and uses one for each. The game
 * has neither: $E000 is the slot it time-shares between the Layer 2 band, a sample
 * page and the loader's staging, and $C000 holds the one thing that must be mapped
 * every cycle of every frame - the sound ring, because the zxnDMA reads through the
 * CPU's own memory decode and a ring in a sliding window is a ring that vanishes.
 *
 * So the game packs the control block, a smaller record buffer, the expected stream,
 * the ring, the volume table and the voice records into that single permanently
 * mapped 8K page, and passes the addresses in. AW_CTL and AW_EXP are the only two
 * numbers that differ. */
#ifndef AW_CTL
#define AW_CTL          0xC000
#endif
#ifndef AW_EXP
#define AW_EXP          0xE000
#endif
#ifndef AW_LOG_RECS
#define AW_LOG_RECS     2040
#endif
/* Where the assembly publishes the six variables inp_updatePlayer sets. Zero in the
 * harness, which has no input and must not have its opcode stream perturbed by one. */
#ifndef AW_IN
#define AW_IN           0
#endif
/* Where the assembly reads aw_draw_poly's six parameters. Zero in the harness, whose
 * aw_draw_poly is a counter and reads nothing. */
#ifndef AW_DRAW
#define AW_DRAW         0
#endif

#define CTL_SEED        (*(volatile uint16_t *)(AW_CTL + 0x00))
#define CTL_FRAMES      (*(volatile uint16_t *)(AW_CTL + 0x02))
#define CTL_BUDGET      (*(volatile uint16_t *)(AW_CTL + 0x04))
#define CTL_RECORDS     (*(volatile uint16_t *)(AW_CTL + 0x06))
#define CTL_FRAMES_DONE (*(volatile uint16_t *)(AW_CTL + 0x08))
#define CTL_FINISHED    (*(volatile uint8_t *)(AW_CTL + 0x0A))
#define CTL_OUT_OF_BUDGET (*(volatile uint8_t *)(AW_CTL + 0x0B))
#define CTL_BAD_OP      (*(volatile uint8_t *)(AW_CTL + 0x0C))
/* A FAULT, with the program counter that caused it and one word of context.
 *
 * These exist because every wrong run looked the same and none of them could be
 * read. The VM would leave the rails somewhere, execute the bytes past the end of
 * the segment as opcodes, and one of those would be a resetThread whose first
 * thread was 200 and whose last was 10 - which the reference computes as a POSITIVE
 * count of 66 threads (vm.cpp:96-99 takes the difference as int8_t) and which then
 * writes sixty-six words past a sixty-four word array, over the opcode table. The
 * next dispatch jumped to whatever the bytecode had put there, the stack ran down
 * from $BF00 smearing one repeating value over the whole program, and what was left
 * to read was a machine with no state in it at all. Stopping AT the fault, with the
 * pc, is the difference between a diagnosis and four hours of symptoms. */
#define CTL_FAULT       (*(volatile uint8_t *)(AW_CTL + 0x0D))
#define CTL_FAULT_PC    (*(volatile uint16_t *)(AW_CTL + 0x0E))
#define CTL_CODE_LEN    (*(volatile uint16_t *)(AW_CTL + 0x10))
#define CTL_FAULT_A     (*(volatile uint16_t *)(AW_CTL + 0x12))
#define CTL_EXP_N       (*(volatile uint16_t *)(AW_CTL + 0x14))
#define CTL_DIV_AT      (*(volatile uint16_t *)(AW_CTL + 0x16))
#define CTL_GOT_REC     ((volatile uint8_t *)(AW_CTL + 0x18))
#define CTL_WANT_REC    ((volatile uint8_t *)(AW_CTL + 0x1C))
#define AW_RECORDS      ((volatile uint8_t *)(AW_CTL + 0x20))

/* THE ENGINE'S OWN STREAM, shipped in the .nex at $E000.
 *
 * The comparison moved onto the machine because getting the trace off it was the
 * whole difficulty. Every wrong run ended the same way - the VM leaves the rails,
 * executes what is after the rails as opcodes, and the stack runs down from $BF00
 * and then wraps, so the smear reaches the trace block and there is nothing left to
 * read. The record that MATTERS is the first one that differs, and it is produced
 * before any of that. So check each record as it is written and stop dead on the
 * first mismatch: the machine halts while its state still means something, and the
 * verdict is twelve bytes rather than eight kilobytes. */
#define EXP_OPS         ((const uint8_t *)AW_EXP)

#define FAULT_PAST_END  1       /* the pc left the segment that was loaded */
#define FAULT_RESET     2       /* resetThread over a range outside the table */
#define FAULT_BAD_OP    3       /* an opcode the reference calls error() on */
#define FAULT_RET       4       /* ret with nothing on the call stack */
#define FAULT_DIVERGE   5       /* a record the engine did not produce */
#define FAULT_OVERRUN   6       /* more records than the engine produced */

static void fault(uint8_t code, uint16_t pc, uint16_t a)
{
    if (CTL_FAULT)              /* the FIRST one is the one that explains it */
        return;
    CTL_FAULT = code;
    CTL_FAULT_PC = pc;
    CTL_FAULT_A = a;
}

/* Parameters for aw_draw_poly, because a fastcall takes one argument.
 *
 * In the game these are not variables but a FIXED BLOCK the assembly reads directly, in
 * the same style as the control block and the input words. The alternative - bridging
 * the C's symbol addresses into sjasmplus - is the arrangement this project already
 * found does not survive: an `extern uint8_t x[]` against a `defc` was read as a
 * pointer variable living at that address rather than as the address itself, and four
 * fields came back as the same value. A cast integer constant cannot be read two ways. */
#if AW_DRAW
#define aw_draw_off     (*(volatile uint16_t *)(AW_DRAW + 0))
#define aw_draw_zoom    (*(volatile uint16_t *)(AW_DRAW + 2))
#define aw_draw_x       (*(volatile int16_t  *)(AW_DRAW + 4))
#define aw_draw_y       (*(volatile int16_t  *)(AW_DRAW + 6))
#define aw_draw_colour  (*(volatile uint8_t  *)(AW_DRAW + 8))
#define aw_draw_video2  (*(volatile uint8_t  *)(AW_DRAW + 9))
#else
uint16_t aw_draw_off;
uint16_t aw_draw_zoom;
int16_t aw_draw_x;
int16_t aw_draw_y;
uint8_t aw_draw_colour;
uint8_t aw_draw_video2;
#endif

/* ---- VM state ------------------------------------------------------------- */
#define NUM_THREADS 64
#define NO_SETVEC   0xFFFF
#define INACTIVE    0xFFFF

int16_t aw_vars[256];

/* threadsData[2][64] and vmIsChannelActive[2][64] - the doubling is the whole
 * point: a thread may retarget or pause any thread including itself, and nothing
 * takes effect until the frame boundary. */
uint16_t aw_pc[NUM_THREADS];
uint16_t aw_pc_req[NUM_THREADS];
uint8_t aw_state[NUM_THREADS];
uint8_t aw_state_req[NUM_THREADS];

/* ONE shared scratch stack whose pointer resets for every thread, so a call
 * cannot survive a pauseThread. The reference declares it 64 deep (vm.h:81),
 * serialises 256 (vm.cpp:712) and bounds-checks at 255 (vm.cpp:96-99) - it can
 * overrun its own array. 256 here. */
uint16_t aw_call_stack[256];
uint8_t aw_sp;

uint8_t aw_goto_next;
uint16_t aw_blits;
uint16_t aw_part_req;

/* ---- the bytecode window ------------------------------------------------- */
static uint8_t *wp;             /* where the pc is, inside the window */
static uint16_t w_lo, w_hi;     /* the offsets the window currently covers */
uint16_t aw_pc_now;             /* the current thread's pc, as an offset */

/* ALWAYS remaps, rather than adjusting the pointer by the difference when the
 * target is already inside the window. The clever version was wrong somewhere -
 * the stream diverged on a byte whose program counter was right, which is exactly
 * what a pointer that does not match aw_pc_now looks like - and a seek happens a
 * handful of times a thread, not once a fetch, so there is nothing to buy. */
static void seek(uint16_t off)
{
    wp = aw_code_window(off);
    w_lo = off & 0xE000;            /* the 8K page the window starts at */
    w_hi = w_lo + 0x4000;           /* two pages are mapped, so 16K is reachable */
    aw_pc_now = off;
}

static uint8_t fetch_byte(void)
{
    uint8_t v;
    if (CTL_CODE_LEN && aw_pc_now >= CTL_CODE_LEN)
        fault(FAULT_PAST_END, aw_pc_now, CTL_CODE_LEN);
    if (aw_pc_now >= w_hi || aw_pc_now < w_lo) {
        wp = aw_code_window(aw_pc_now);
        w_lo = aw_pc_now & 0xE000;
        w_hi = w_lo + 0x4000;
    }
    v = *wp++;
    ++aw_pc_now;
    return v;
}

/* Big-endian, as Ptr::fetchWord is (intern.h). */
static uint16_t fetch_word(void)
{
    uint8_t hi = fetch_byte();
    return (uint16_t)((hi << 8) | fetch_byte());
}

/* ---- the trace log ------------------------------------------------------- */
#define LOG_RECS AW_LOG_RECS    /* the harness has 8K for these; the game has less */
uint16_t aw_log_count;

/* Four bytes a record: kind, the program counter as a word, then the opcode or
 * the thread. Kind 1 is an opcode, kind 2 a thread edge. */
static void aw_logrec(uint8_t kind, uint16_t pc, uint8_t v)
{
    volatile uint8_t *p;
    const uint8_t *q;
    uint8_t rec[4];

    rec[0] = kind;
    rec[1] = (uint8_t)pc;
    rec[2] = (uint8_t)(pc >> 8);
    rec[3] = v;

    if (CTL_EXP_N) {
        if (aw_log_count >= CTL_EXP_N) {
            /* Not a pass and not a crash: the engine stopped here and we did not.
             * Worth its own code, because "more than the engine" and "different
             * from the engine" have different causes. */
            fault(FAULT_OVERRUN, pc, aw_log_count);
            return;
        }
        q = EXP_OPS + ((uint16_t)aw_log_count << 2);
        if (rec[0] != q[0] || rec[1] != q[1] || rec[2] != q[2] || rec[3] != q[3]) {
            CTL_DIV_AT = aw_log_count;
            CTL_GOT_REC[0] = rec[0];  CTL_GOT_REC[1] = rec[1];
            CTL_GOT_REC[2] = rec[2];  CTL_GOT_REC[3] = rec[3];
            CTL_WANT_REC[0] = q[0];   CTL_WANT_REC[1] = q[1];
            CTL_WANT_REC[2] = q[2];   CTL_WANT_REC[3] = q[3];
            fault(FAULT_DIVERGE, pc, aw_log_count);
            return;
        }
    }

    /* THE COUNTER ADVANCES WHETHER OR NOT THE RECORD IS STORED, because it is the
     * comparison's index and not just a buffer position.
     *
     * It used to return here when the buffer was full, leaving aw_log_count stuck -
     * so every record after that was compared against the SAME expected record, and
     * the first one that differed was reported as a divergence. The harness has 2,040
     * record slots against a 763-record stream so it could never see this; the game
     * has 256, and it diverged at exactly record 256 with a pauseThread where the
     * engine had a fillVideoPage. A buffer that is smaller than the thing being
     * checked is a different program. */
    if (aw_log_count < LOG_RECS) {
        p = AW_RECORDS + (aw_log_count << 2);
        p[0] = rec[0];
        p[1] = rec[1];
        p[2] = rec[2];
        p[3] = rec[3];
    }
    ++aw_log_count;
    CTL_RECORDS = aw_log_count;
}

/* ---- the opcodes --------------------------------------------------------- */

static void op_movConst(void)   { uint8_t v = fetch_byte(); aw_vars[v] = (int16_t)fetch_word(); }
static void op_mov(void)        { uint8_t d = fetch_byte(); aw_vars[d] = aw_vars[fetch_byte()]; }
static void op_add(void)        { uint8_t d = fetch_byte(); aw_vars[d] += aw_vars[fetch_byte()]; }
static void op_addConst(void)   { uint8_t v = fetch_byte(); aw_vars[v] += (int16_t)fetch_word(); }

static void op_call(void)
{
    uint16_t off = fetch_word();
    aw_call_stack[aw_sp] = aw_pc_now;   /* the RETURN offset, after the operand */
    ++aw_sp;
    seek(off);
}

static void op_ret(void)
{
    if (aw_sp == 0) {
        fault(FAULT_RET, aw_pc_now, 0);
        return;
    }
    --aw_sp;
    seek(aw_call_stack[aw_sp]);
}
static void op_pauseThread(void){ aw_goto_next = 1; }
static void op_jmp(void)        { seek(fetch_word()); }

static void op_setSetVect(void)
{
    uint8_t t = fetch_byte();
    aw_pc_req[t & (NUM_THREADS - 1)] = fetch_word();
}

/* Pre-decrements the variable, then jumps if it is not zero. */
static void op_jnz(void)
{
    uint8_t i = fetch_byte();
    --aw_vars[i];
    if (aw_vars[i] != 0)
        op_jmp();
    else
        fetch_word();
}

static void op_condJmp(void)
{
    uint8_t op = fetch_byte();
    uint8_t var = fetch_byte();
    int16_t b = aw_vars[var];
    int16_t a;
    uint8_t met = 0;

    if (op & 0x80)      a = aw_vars[fetch_byte()];
    else if (op & 0x40) a = (int16_t)fetch_word();
    else                a = (int16_t)fetch_byte();

    /* SIGNED throughout - both operands are int16_t. */
    switch (op & 7) {
    case 0: met = (b == a); break;
    case 1: met = (b != a); break;
    case 2: met = (b >  a); break;
    case 3: met = (b >= a); break;
    case 4: met = (b <  a); break;
    case 5: met = (b <= a); break;
    default: break;                 /* 6 and 7 warn and fall through */
    }
    if (met)
        op_jmp();
    else
        fetch_word();
}

/* The HIGH byte only. */
static void op_setPalette(void) { aw_set_palette((uint8_t)(fetch_word() >> 8)); }

static void op_resetThread(void)
{
    uint8_t first = fetch_byte();
    uint8_t last = fetch_byte() & (NUM_THREADS - 1);
    uint8_t action;
    int8_t n = (int8_t)(last - first);
    if (n < 0) {                    /* the engine warns and does nothing */
        fetch_byte();
        return;
    }
    ++n;
    action = fetch_byte();
    /* The reference does not check this and does not need to: its bytecode is
     * always the bytecode. Ours is whatever the pc is pointing at, and a first of
     * 200 with a last masked to 10 gives a POSITIVE n of 67 - sixty-seven words
     * written past a sixty-four word array. That is the write that destroyed the
     * opcode table on every bad run. */
    if ((uint16_t)first + (uint16_t)n > NUM_THREADS) {
        fault(FAULT_RESET, aw_pc_now, (uint16_t)(first | ((uint16_t)n << 8)));
        return;
    }
    if (action == 2) {
        while (n--)
            aw_pc_req[first++] = 0xFFFE;    /* checkThreadRequests makes these
                                               inactive */
    } else if (action < 2) {
        while (n--)
            aw_state_req[first++] = action;
    }
    /* action >= 3 does nothing at all, silently */
}

static void op_selectVideoPage(void) { aw_select_page(fetch_byte()); }

static void op_fillVideoPage(void)
{
    uint8_t page = fetch_byte();
    aw_fill_page((uint16_t)page | ((uint16_t)fetch_byte() << 8));
}

static void op_copyVideoPage(void)
{
    uint8_t src = fetch_byte();
    aw_copy_page((uint16_t)src | ((uint16_t)fetch_byte() << 8));
}

/* Does NOT yield. Only pauseThread and killThread set gotoNextThread in the
 * reference (vm.cpp:115 and :301) - a thread carries on after presenting a frame,
 * and a version of this that yielded would diverge from the engine's opcode
 * stream at the first blit. */
static void op_blitFramebuffer(void)
{
    uint8_t page = fetch_byte();
    aw_vars[0xF7] = 0;
    aw_blit(page);
    ++aw_blits;
}

static void op_killThread(void)
{
    aw_pc_now = INACTIVE;           /* segBytecode + 0xFFFF */
    aw_goto_next = 1;
}

static void op_drawString(void)
{
    fetch_word();                   /* string id */
    fetch_byte();                   /* x, a character cell */
    fetch_byte();                   /* y, a pixel row */
    fetch_byte();                   /* colour */
}

static void op_sub(void)  { uint8_t i = fetch_byte(); aw_vars[i] -= aw_vars[fetch_byte()]; }
static void op_and(void)  { uint8_t v = fetch_byte(); aw_vars[v] = (int16_t)((uint16_t)aw_vars[v] & fetch_word()); }
static void op_or(void)   { uint8_t v = fetch_byte(); aw_vars[v] = (int16_t)((uint16_t)aw_vars[v] | fetch_word()); }
static void op_shl(void)  { uint8_t v = fetch_byte(); aw_vars[v] = (int16_t)((uint16_t)aw_vars[v] << fetch_word()); }
static void op_shr(void)  { uint8_t v = fetch_byte(); aw_vars[v] = (int16_t)((uint16_t)aw_vars[v] >> fetch_word()); }

static void op_playSound(void)
{
    fetch_word();                   /* resource */
    fetch_byte();                   /* frequency index */
    fetch_byte();                   /* volume */
    fetch_byte();                   /* channel */
}

/* loadPartsOrMemoryEntry, resource.cpp:258, through op_updateMemList, vm.cpp:366.
 *
 * Three branches and the reference's order: zero stops the sound and invalidates, an id
 * above the memory list is a PART request, anything else loads. 150 rather than the real
 * count of 146 because part ids start at $3E80 and nothing lies between - the reference
 * compares against _numMemList, which it reads from the file, and this is the one place
 * the port keeps a constant where the engine keeps data.
 *
 * The player and mixer stops that belong on the zero branch are I5's: there is nothing
 * playing yet to stop. */
static void op_updateMemList(void)
{
    uint16_t res = fetch_word();
    if (res == 0) {
        aw_inval_res();
    } else if (res > 150) {
        aw_part_req = res;
    } else {
        aw_load_res(res);
    }
}

static void op_playMusic(void)
{
    fetch_word();                   /* resource */
    fetch_word();                   /* delay */
    fetch_byte();                   /* position */
}

typedef void (*op_fn)(void);
static const op_fn op_table[27] = {
    op_movConst, op_mov, op_add, op_addConst,
    op_call, op_ret, op_pauseThread, op_jmp,
    op_setSetVect, op_jnz, op_condJmp, op_setPalette,
    op_resetThread, op_selectVideoPage, op_fillVideoPage, op_copyVideoPage,
    op_blitFramebuffer, op_killThread, op_drawString, op_sub,
    op_and, op_or, op_shl, op_shr,
    op_playSound, op_updateMemList, op_playMusic
};

/* ---- the two polygon forms ------------------------------------------------ */
/* Each ends in a `continue` in the reference, so the opcode table is never
 * reached for them (vm.cpp:485-580). */

static void poly_bit7(uint8_t opcode)
{
    int16_t x, y, h;
    aw_draw_off = (uint16_t)(((uint16_t)opcode << 8) | fetch_byte()) * 2;
    aw_draw_video2 = 0;
    /* UNSIGNED, and this was wrong for the whole of Phase D without anything noticing.
     *
     * vm.cpp's bit-7 form is `int16_t x = _scriptPtr.fetchByte();` - fetchByte returns
     * uint8_t, so assigning it to int16_t ZERO-extends. An (int8_t) cast sign-extends
     * instead, and every coordinate at or above 128 came out 256 too small: the engine's
     * x=192 was our x=-64, its 247 our -9, its y=143 our -113.
     *
     * Nothing caught it until I2's page comparison. Gate D proves the opcode STREAM -
     * thread, pc, opcode - and says nothing about the operands the C derives from it.
     * check-readmachine proves the reader against a draw list a checker POKED, so it
     * never saw the C compute one. The bug lived exactly in the seam between two passing
     * gates, which is the argument for comparing the picture and not the stream. */
    x = (int16_t)fetch_byte();
    y = (int16_t)fetch_byte();
    /* A DIAGONAL slide, not two clamps: h goes into x as well. */
    h = y - 199;
    if (h > 0) {
        y = 199;
        x += h;
    }
    aw_draw_colour = 0xFF;
    aw_draw_zoom = 0x40;
    aw_draw_x = x;
    aw_draw_y = y;
    aw_draw_poly();
}

static void poly_bit6(uint8_t opcode)
{
    int16_t x, y;
    uint16_t zoom;
    aw_draw_off = fetch_word() * 2;
    x = (int16_t)fetch_byte();
    aw_draw_video2 = 0;

    if (!(opcode & 0x20)) {
        if (!(opcode & 0x10))
            x = (int16_t)(((uint16_t)x << 8) | fetch_byte());
        else
            x = aw_vars[x];
    } else if (opcode & 0x10) {
        x += 0x100;
    }

    y = (int16_t)fetch_byte();
    if (!(opcode & 8)) {
        if (!(opcode & 4))
            y = (int16_t)(((uint16_t)y << 8) | fetch_byte());
        else
            y = aw_vars[y];
    }

    zoom = fetch_byte();
    if (!(opcode & 2)) {
        if (!(opcode & 1)) {
            /* rewinds by one and takes the default zoom */
            --aw_pc_now;
            --wp;
            zoom = 0x40;
        } else {
            zoom = (uint16_t)aw_vars[zoom];
        }
    } else if (opcode & 1) {
        /* the ONLY path that reads the player-and-enemy segment */
        aw_draw_video2 = 1;
        --aw_pc_now;
        --wp;
        zoom = 0x40;
    }

    aw_draw_colour = 0xFF;
    aw_draw_zoom = zoom;
    aw_draw_x = x;
    aw_draw_y = y;
    aw_draw_poly();
}

/* ---- the scheduler ------------------------------------------------------- */

void aw_init_vars(uint16_t seed) __z88dk_fastcall
{
    uint16_t i;
    for (i = 0; i < 256; ++i)
        aw_vars[i] = 0;
    aw_vars[0x54] = 0x81;
    aw_vars[0x3C] = (int16_t)seed;
    /* Set by the original game code and executable, not by the bytecode, and the
     * reference sets them under BYPASS_PROTECTION - which is how we start, at
     * part 2. A port that omits them starts a part that cannot work. */
    aw_vars[0xBC] = 0x10;
    aw_vars[0xC6] = 0x80;
    aw_vars[0xF2] = 4000;
    aw_vars[0xDC] = 33;
}

void aw_init_part(void) __z88dk_fastcall
{
    uint16_t i;
    aw_vars[0xE4] = 0x14;
    for (i = 0; i < NUM_THREADS; ++i) {
        aw_pc[i] = INACTIVE;            /* memset(threadsData, 0xFF, ...) */
        aw_pc_req[i] = NO_SETVEC;
        aw_state[i] = 0;
        aw_state_req[i] = 0;
    }
    aw_pc[0] = 0;
    aw_part_req = 0;
    CTL_BAD_OP = 0;
}

/* checkThreadRequests, vm.cpp:401-431. Three things, in order. */
void aw_check_requests(void) __z88dk_fastcall
{
    uint16_t i, n;
    for (i = 0; i < NUM_THREADS; ++i) {
        aw_state[i] = aw_state_req[i];
        n = aw_pc_req[i];
        if (n != NO_SETVEC) {
            aw_pc[i] = (n == 0xFFFE) ? INACTIVE : n;
            aw_pc_req[i] = NO_SETVEC;
        }
    }
}

/* An OPCODE BUDGET, so the harness always terminates. While op_updateMemList is a
 * stub the intro's script waits for a resource that never arrives and a thread
 * loops without ever reaching pauseThread - and a checker cannot read a spinning
 * machine reliably, because the MMU is moving underneath it. A tracing harness
 * wants a bound on its own account. */

static void execute_thread(void)
{
    uint8_t opcode;
    uint16_t pc_before;
    while (!aw_goto_next) {
        if (CTL_BUDGET == 0) {
            aw_goto_next = 1;
            CTL_OUT_OF_BUDGET = 1;
            return;
        }
        --CTL_BUDGET;
        pc_before = aw_pc_now;
        opcode = fetch_byte();
        aw_logrec(1, pc_before, opcode);
        if (opcode & 0x80)
            poly_bit7(opcode);
        else if (opcode & 0x40)
            poly_bit6(opcode);
        else if (opcode > 0x1A) {
            CTL_BAD_OP = opcode;        /* the engine calls error() here */
            fault(FAULT_BAD_OP, pc_before, opcode);
        } else
            op_table[opcode]();
        if (CTL_FAULT) {
            aw_goto_next = 1;
            return;
        }
    }
}

/* inp_updatePlayer's result, read from where the assembly published it.
 *
 * The ORDER matters and is the reference's: engine.cpp runs checkThreadRequests, then
 * inp_updatePlayer, then hostFrame. A port that read the keys after the frame would be
 * one frame late on every input and would feel it rather than show it. */
static void aw_apply_input(void)
{
#if AW_IN
    aw_vars[0xE5] = *(volatile int16_t *)(AW_IN + 0);
    aw_vars[0xFA] = *(volatile int16_t *)(AW_IN + 2);
    aw_vars[0xFB] = *(volatile int16_t *)(AW_IN + 4);
    aw_vars[0xFC] = *(volatile int16_t *)(AW_IN + 6);
    aw_vars[0xFD] = *(volatile int16_t *)(AW_IN + 8);
    aw_vars[0xFE] = *(volatile int16_t *)(AW_IN + 10);
#endif
}

/* hostFrame, vm.cpp:433-476. Returns non-zero if a blit ended the frame. */
uint8_t aw_host_frame(void) __z88dk_fastcall
{
    uint8_t t, blitted = 0;
    for (t = 0; t < NUM_THREADS; ++t) {
        if (CTL_OUT_OF_BUDGET || CTL_FAULT)
            break;
        if (aw_state[t])
            continue;
        if (aw_pc[t] == INACTIVE)
            continue;
        aw_logrec(2, aw_pc[t], t);
        if (CTL_FAULT)
            break;
        seek(aw_pc[t]);
        aw_sp = 0;                      /* the shared stack, per thread */
        aw_goto_next = 0;
        execute_thread();
        aw_pc[t] = aw_pc_now;
    }
    return blitted;
}

/* ---- the entry point ----------------------------------------------------- */
/* The assembly loads the bytecode, pokes these two, and calls CRT_ORG_CODE once.
 * C owns the frame loop for Gate D, which is about the opcode stream rather than
 * about pacing; E1 moves the loop out to the frame interrupt. */

int main(void)
{
    uint16_t f;

    /* EVERYTHING initialised explicitly, and nothing trusted to start at zero.
     *
     * This is the fault that made Gate D look unrepeatable for a whole session. C
     * expects its statics zeroed and here they are not: ZEsarUX's smartload does
     * not clear RAM between loads, so a second run inherits the first run's memory
     * and the window bounds, the trace count and the stack pointer all start as
     * whatever was left. The same inputs then gave 0, 122 and 354 matching records
     * on different runs, which reads as a flaky machine rather than as an
     * uninitialised variable.
     *
     * A .nex cannot assume a clean machine. State it all. */
    wp = 0;
    w_lo = 0;
    w_hi = 0;
    aw_pc_now = 0;
    aw_sp = 0;
    aw_goto_next = 0;
    aw_part_req = 0;

    aw_init_vars(CTL_SEED);
    aw_init_part();
    aw_blits = 0;
    aw_log_count = 0;
    CTL_RECORDS = 0;
    CTL_OUT_OF_BUDGET = 0;
    CTL_BAD_OP = 0;
    CTL_FAULT = 0;
    CTL_FAULT_PC = 0;
    CTL_FAULT_A = 0;
    CTL_DIV_AT = 0;
    for (f = 0; f < CTL_FRAMES; ++f) {
        aw_frame_sync();
        CTL_FRAMES_DONE = f;
        if (CTL_OUT_OF_BUDGET || CTL_FAULT)
            break;
        aw_check_requests();
        aw_apply_input();
        aw_host_frame();
    }
    CTL_FRAMES_DONE = f;
    CTL_FINISHED = 0x5A;

    /* AND MAIN NEVER RETURNS, which is the point.
     *
     * z88dk's exit path is `im 1 / ei / ret` - ED 56 FB C9, at $8C40 in this build.
     * EI delays interrupt acceptance by exactly one instruction, and that one
     * instruction is the RET, so the interrupt is taken BEFORE the caller's first
     * instruction runs. A `di` placed immediately after `call CC_ORG` is therefore
     * too late by one instruction, every single time - and $0038 is not the ROM
     * here, it is the bytecode segment MMU0 and MMU1 are holding. The machine
     * executes Another World's bytecode as Z80 code, the stack runs down from $BF00
     * and wraps, and every counter the gate reads is overwritten.
     *
     * That is the whole of "Gate D will not repeat": 0, 64, 122 and 354 matching
     * records from identical inputs, because the checker was reading a machine that
     * had already begun destroying itself and how much survived depended on how long
     * the read took. Four other faults were found and fixed while chasing it - each
     * real, none of them this - which is exactly why fixing them changed nothing.
     *
     * Never coming back is the fix that needs nothing else to be true. The verdict is
     * in the control block, the checker reads it from there, and interrupts stay off
     * because nothing ever runs the code that turns them on. */
    for (;;)
        CTL_FINISHED = 0x5A;
}
