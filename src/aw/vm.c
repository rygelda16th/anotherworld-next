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
#define AW_LOG_BUF      ((volatile uint8_t *)0xC000)

/* And the control values are ordinary C globals again, which is the arrangement
 * that worked: 354 of 354 records identical to the engine's. Two attempts to move
 * them into assembly-owned memory - an `extern uint8_t x[]` against a defc, then a
 * cast address constant - both came back reading four different fields as the same
 * value, and neither was worth more time than it had already taken. The checker
 * finds them through z88dk's map, which it already parses for everything else. */
uint16_t aw_seed;
uint16_t aw_frames;
uint16_t aw_budget;
uint16_t aw_records;
uint16_t aw_frames_done;
uint8_t aw_finished;
uint8_t aw_out_of_budget;
uint8_t aw_bad_op;

#define CTL_SEED          aw_seed
#define CTL_FRAMES        aw_frames
#define CTL_BUDGET        aw_budget
#define CTL_RECORDS       aw_records
#define CTL_FRAMES_DONE   aw_frames_done
#define CTL_FINISHED      aw_finished
#define CTL_OUT_OF_BUDGET aw_out_of_budget
#define CTL_BAD_OP        aw_bad_op

/* Parameters for aw_draw_poly, because a fastcall takes one argument. */
uint16_t aw_draw_off;
uint16_t aw_draw_zoom;
int16_t aw_draw_x;
int16_t aw_draw_y;
uint8_t aw_draw_colour;
uint8_t aw_draw_video2;

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
#define LOG_RECS 2048
uint16_t aw_log_count;

/* Four bytes a record: kind, the program counter as a word, then the opcode or
 * the thread. Kind 1 is an opcode, kind 2 a thread edge. */
static void aw_logrec(uint8_t kind, uint16_t pc, uint8_t v)
{
    volatile uint8_t *p;
    if (aw_log_count >= LOG_RECS)
        return;
    p = AW_LOG_BUF + (aw_log_count << 2);
    p[0] = kind;
    p[1] = (uint8_t)pc;
    p[2] = (uint8_t)(pc >> 8);
    p[3] = v;
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

static void op_ret(void)        { --aw_sp; seek(aw_call_stack[aw_sp]); }
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

static void op_updateMemList(void)
{
    uint16_t res = fetch_word();
    if (res > 150)                  /* above the mem list: a part request */
        aw_part_req = res;
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
    x = (int8_t)fetch_byte();
    y = (int8_t)fetch_byte();
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
        else if (opcode > 0x1A)
            CTL_BAD_OP = opcode;        /* the engine calls error() here */
        else
            op_table[opcode]();
    }
}

/* hostFrame, vm.cpp:433-476. Returns non-zero if a blit ended the frame. */
uint8_t aw_host_frame(void) __z88dk_fastcall
{
    uint8_t t, blitted = 0;
    for (t = 0; t < NUM_THREADS; ++t) {
        if (CTL_OUT_OF_BUDGET)
            break;
        if (aw_state[t])
            continue;
        if (aw_pc[t] == INACTIVE)
            continue;
        aw_logrec(2, aw_pc[t], t);
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
    aw_init_vars(CTL_SEED);
    aw_init_part();
    aw_blits = 0;
    aw_log_count = 0;
    CTL_RECORDS = 0;
    CTL_OUT_OF_BUDGET = 0;
    for (f = 0; f < CTL_FRAMES; ++f) {
        CTL_FRAMES_DONE = f;
        if (CTL_OUT_OF_BUDGET)
            break;
        aw_check_requests();
        aw_host_frame();
    }
    CTL_FRAMES_DONE = f;
    CTL_FINISHED = 0x5A;
    return 0;
}
