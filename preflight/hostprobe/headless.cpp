/* Headless System stub + driver: measures VM and rasteriser load per frame.
 * No SDL, no audio, no real time. The clock is virtual so the engine's own
 * pacing arithmetic runs exactly but costs nothing. */
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "sys.h"
#include "engine.h"
#include "video.h"
#include "instr.h"

/* ---- video trace -------------------------------------------------------
 * A byte-for-byte record of every video operation, so a host reference can
 * replay exactly the same calls and be compared against the real engine's
 * framebuffers. The same file is the test vector Phase C replays on the Next.
 *
 * Little-endian records, each starting with a 1-byte kind:
 *   1 polygon : u32 frame, u16 color, u16 zoom, i16 x, i16 y, u16 bbw, u16 bbh,
 *               u8 npoints, u8 page, then npoints * (i16 x, i16 y)
 *   2 fillPage: u8 page, u8 colour
 *   3 copyPage: u8 src, u8 dst, i16 vscroll        (RAW operands)
 *   4 select  : u8 page
 *   5 blit    : u8 page                            (ends a frame)
 */
static FILE *gTrace = NULL;
static uint32_t gFrameNo = 0;
static uint32_t gTraceFrames = 0;      /* trace only the first N frames */

static void w8(unsigned v)  { unsigned char b = (unsigned char)v; fwrite(&b,1,1,gTrace); }
static void w16(int v)      { unsigned char b[2] = {(unsigned char)(v & 0xFF),
                                                    (unsigned char)((v >> 8) & 0xFF)};
                              fwrite(b,1,2,gTrace); }
static void w32(unsigned v) { for (int i=0;i<4;++i) w8((v >> (8*i)) & 0xFF); }

void instrPolygon(int color, int zoom, int px, int py, int bbw, int bbh,
                  int npoints, const short *xy, int page) {
    if (!gTrace || gFrameNo >= gTraceFrames) return;
    w8(1); w32(gFrameNo); w16(color); w16(zoom); w16(px); w16(py);
    w16(bbw); w16(bbh); w8(npoints); w8(page);
    for (int i = 0; i < npoints * 2; ++i) w16(xy[i]);
}

/* All four framebuffers at the moment the traced window closes. 4bpp, 32000
 * bytes each, exactly as the engine holds them. */
void instrPages(const unsigned char *p0, const unsigned char *p1,
                const unsigned char *p2, const unsigned char *p3) {
    if (!gTraceFrames || gFrameNo != gTraceFrames) return;
    const unsigned char *pp[4] = {p0, p1, p2, p3};
    for (int i = 0; i < 4; ++i) {
        char nm[32]; snprintf(nm, sizeof nm, "page%d.bin", i);
        FILE *f = fopen(nm, "wb");
        if (f) { fwrite(pp[i], 1, 320 * 200 / 2, f); fclose(f); }
    }
    printf("dumped four pages at frame %u\n", gFrameNo);
}

/* kind 6: one glyph. x is a character cell, y a pixel row. */
void instrChar(int ch, int x, int y, int colour, int page) {
    if (!gTrace || gFrameNo >= gTraceFrames) return;
    w8(6); w8(ch); w8(x); w16(y); w8(colour); w8(page);
}

/* kind 7: one top-level polygon draw, as the bytecode asked for it. The record
 * is what the reader needs and nothing else: which segment, the byte offset into
 * it, and the three parameters the two opcode forms compute. */
void instrDraw(int useVideo2, int off, int colour, int zoom, int x, int y) {
    if (!gTrace || gFrameNo >= gTraceFrames) return;
    w8(7); w8(useVideo2); w16(off); w16(colour); w16(zoom); w16(x); w16(y);
}

/* The segments themselves, written once a part. Without these the kind 7 records
 * are offsets into nothing. */
static int gSegDump = 0;
void instrSegments(const unsigned char *cine, int cineSize,
                   const unsigned char *v2, int v2Size) {
    if (!gTraceFrames) return;
    char nm[48];
    snprintf(nm, sizeof nm, "seg_cine_%d.bin", gSegDump);
    FILE *f = fopen(nm, "wb");
    if (f) { fwrite(cine, 1, cineSize, f); fclose(f); }
    if (v2 && v2Size) {
        snprintf(nm, sizeof nm, "seg_video2_%d.bin", gSegDump);
        f = fopen(nm, "wb");
        if (f) { fwrite(v2, 1, v2Size, f); fclose(f); }
    }
    printf("dumped segments for part index %d: cinematic %d bytes, video2 %d\n",
           gSegDump, cineSize, v2Size);
    /* And a marker IN the trace, because a kind 7 offset means nothing without
     * knowing which segment it indexes and the part changes mid-trace. */
    if (gTrace) { w8(8); w8(gSegDump); }
    ++gSegDump;
}

/* The opcode stream, as a separate file: it is far larger than the video trace
 * and only the first frames of it are wanted. Text, because it is read once by a
 * checker and being able to look at it matters more than its size. */
static FILE *gOps = NULL;
static uint32_t gOpFrames = 0;

void instrOpcode(int thread, int pc, int opcode) {
    if (gOps && gFrameNo < gOpFrames)
        fprintf(gOps, "op %u %d %d %d\n", gFrameNo, thread, pc, opcode);
}

void instrThread(int thread, int pc) {
    if (gOps && gFrameNo < gOpFrames)
        fprintf(gOps, "thread %u %d %d\n", gFrameNo, thread, pc);
}

void instrFrameEdge(void) {
    if (gOps && gFrameNo < gOpFrames)
        fprintf(gOps, "frame %u\n", gFrameNo);
}

unsigned instrFrameNow(void) { return gFrameNo; }

static int gJumpPart = 0;
static uint32_t gJumpFrame = 0;

int instrJumpPart(unsigned frame) {
    if (!gJumpPart || frame < gJumpFrame) return 0;
    int p = gJumpPart;
    gJumpPart = 0;                  /* once */
    printf("requesting part %d (index %d) at frame %u\n", p, p - 0x3E80, frame);
    return p;
}

void instrSeed(int seed) {
    if (gOps) fprintf(gOps, "seed %d\n", seed);
    printf("random seed: %d\n", seed);
}

void instrBytecode(const unsigned char *code, int size) {
    if (!gOpFrames) return;
    static int n = 0;
    char nm[48];
    snprintf(nm, sizeof nm, "bytecode_%d.bin", n++);
    FILE *f = fopen(nm, "wb");
    if (f) { fwrite(code, 1, size, f); fclose(f); }
    printf("dumped bytecode %d: %d bytes\n", n - 1, size);
}

void instrOp(int kind, int a, int b, int c) {
    if (!gTrace || gFrameNo >= gTraceFrames) return;
    w8(kind);
    if (kind == 2)      { w8(a); w8(b); }
    else if (kind == 3) { w8(a); w8(b); w16(c); }
    else                { w8(a); }
}

/* ---- second round -------------------------------------------------------
 * Structure, heap and sound. The sound events go to a text file covering the
 * WHOLE run rather than into trace.bin's traced window, because voice
 * concurrency is a property of minutes of play, not of the first few frames.
 */
uint32_t gPolyDepth, gPolyPts, gPolyChilds, gPolyLeaves, gPolyHiers;
uint32_t gBitmaps, gHeapPeak;
static FILE *gSnd = NULL;
static uint32_t gNow = 0;           /* the virtual clock, in ms */

void instrTick(unsigned ms) { gNow = ms; }

void instrPolyDepth(int depth, int offset) {
    (void)offset;
    if ((uint32_t)depth > gPolyDepth) gPolyDepth = depth;
}

void instrPolyRecord(int npoints, int zoom) {
    (void)zoom;
    ++gPolyLeaves;
    if ((uint32_t)npoints > gPolyPts) gPolyPts = npoints;
}

void instrPolyHier(int childs) {
    ++gPolyHiers;
    if ((uint32_t)childs + 1 > gPolyChilds) gPolyChilds = childs + 1;
}

void instrBitmap(void) { ++gBitmaps; }

void instrHeap(unsigned used, int type, int size) {
    if (used > gHeapPeak) gHeapPeak = used;
    if (gSnd) fprintf(gSnd, "load %u %u %d %d %u\n", gNow, gFrameNo, type, size, used);
}

void instrSound(int resNum, int freqIndex, int vol, int chan,
                int len, int loopLen) {
    if (gSnd) fprintf(gSnd, "sfx %u %u %d %d %d %d %d %d\n", gNow, gFrameNo,
                      resNum, freqIndex, vol, chan, len, loopLen);
}

void instrNote(int chan, int hz, int vol, int len, int loopLen) {
    if (gSnd) fprintf(gSnd, "note %u %u %d %d %d %d %d\n", gNow, gFrameNo,
                      chan, hz, vol, len, loopLen);
}

void instrMusic(int resNum, int delay, int pos) {
    if (gSnd) fprintf(gSnd, "music %u %u %d %d %d\n", gNow, gFrameNo,
                      resNum, delay, pos);
}

uint32_t gOpTable, gOpPoly7, gOpPoly6, gThreads, gPolys;
uint32_t gSpanN, gSpanBlend, gSpanP, gFillPage, gCopyPage;
uint32_t gSpanHist[336];
uint16_t gPart = 0;

uint32_t gPaceHist[16];
uint32_t gPace = 0;
void instrPace(int slices) {
    gPace = (unsigned)slices;
    if (slices >= 0 && slices < 16) ++gPaceHist[slices];
}

struct Rec { uint16_t part; uint32_t tbl, p7, p6, th, poly, sN, sB, sP, fp, cp, pace; };
static std::vector<Rec> gRecs;
static uint32_t gFrameCap = 4000;
static int gAutoplay = 0;

void instrFrame(void) {
    ++gFrameNo;          /* here, not in the stub: see instrPages */
    Rec r; r.part=gPart; r.tbl=gOpTable; r.p7=gOpPoly7; r.p6=gOpPoly6; r.th=gThreads;
    r.pace=gPace; r.poly=gPolys; r.sN=gSpanN; r.sB=gSpanBlend; r.sP=gSpanP; r.fp=gFillPage; r.cp=gCopyPage;
    gRecs.push_back(r);
    gOpTable=gOpPoly7=gOpPoly6=gThreads=gPolys=gSpanN=gSpanBlend=gSpanP=gFillPage=gCopyPage=0;
}

struct Headless : System {
    uint32_t _now = 0;
    TimerCallback _tcb = NULL;
    void *_tparam = NULL;
    uint32_t _tiv = 0, _tnext = 0;
    void init(const char *) {}
    void destroy() {}
    void setPalette(const uint8_t *) {}
    void updateDisplay(const uint8_t *) {
        if (gRecs.size() >= gFrameCap) input.quit = true;
    }
    /* Synthetic input. Without it the intro reaches its "press fire" prompt
     * and the run stalls there forever: 57,386 of 60,000 frames drew nothing,
     * so every number came from the protection screen and the intro, and the
     * player/enemy polygon segment and the full-screen bitmap path were never
     * exercised at all. This walks right, jumps, and fires, which is enough to
     * get into the game and to keep dying in it - and a death restarts the
     * part, which is exactly the drawing we want to weigh. */
    void processEvents() {
        if (!gAutoplay) return;
        uint32_t f = gFrameNo;
        input.dirMask = 0;
        if (f % 400 < 260)      input.dirMask |= PlayerInput::DIR_RIGHT;
        else if (f % 400 < 300) input.dirMask |= PlayerInput::DIR_UP;
        else if (f % 400 < 330) input.dirMask |= PlayerInput::DIR_LEFT;
        input.button = (f % 47) < 6;
    }
    /* SDL_AddTimer semantics against the virtual clock. Without this the
     * music player never ticks, so no note ever reaches the mixer and the
     * voice count reads as "sound effects only" - which is wrong by a factor
     * of four for most of the game. The callback's return value is the next
     * interval, exactly as SDL treats it. */
    void sleep(uint32_t d) {
        uint32_t end = _now + d;
        while (_tcb && _tnext <= end) {
            _now = _tnext;
            instrTick(_now);
            uint32_t iv = _tcb(_tiv, _tparam);
            if (!_tcb) break;                  /* removed from inside */
            _tiv = iv ? iv : 1;
            _tnext = _now + _tiv;
        }
        _now = end;
        instrTick(_now);
    }
    uint32_t getTimeStamp() { return _now; }
    void startAudio(AudioCallback, void *) {}
    void stopAudio() {}
    uint32_t getOutputSampleRate() { return 22050; }
    int addTimer(uint32_t iv, TimerCallback cb, void *p) {
        _tiv = iv ? iv : 1; _tcb = cb; _tparam = p; _tnext = _now + _tiv;
        return 1;
    }
    void removeTimer(int) { _tcb = NULL; }
    void *createMutex() { return (void *)1; }
    void destroyMutex(void *) {}
    void lockMutex(void *) {}
    void unlockMutex(void *) {}
};

static Headless gStub;
System *stub = &gStub;

static void report() {
    if (gRecs.empty()) { printf("no frames recorded\n"); return; }
    printf("frames recorded: %zu\n\n", gRecs.size());
    // per-part aggregation
    printf("%-6s %7s | %9s %9s %9s %9s | %8s %9s | %7s %7s\n",
      "part","frames","ops/frame","tbl/f","poly7/f","poly6/f","polys/f","spans/f","fill/f","copy/f");
    uint16_t cur=0xFFFF; size_t i=0;
    while (i < gRecs.size()) {
        cur = gRecs[i].part; size_t j=i;
        double tbl=0,p7=0,p6=0,poly=0,sp=0,fp=0,cp=0,th=0;
        while (j < gRecs.size() && gRecs[j].part==cur) {
            tbl+=gRecs[j].tbl; p7+=gRecs[j].p7; p6+=gRecs[j].p6; th+=gRecs[j].th;
            poly+=gRecs[j].poly; sp+=gRecs[j].sN+gRecs[j].sB+gRecs[j].sP;
            fp+=gRecs[j].fp; cp+=gRecs[j].cp; ++j;
        }
        double n = j-i;
        printf("%-6u %7.0f | %9.1f %9.1f %9.1f %9.1f | %8.1f %9.1f | %7.2f %7.2f\n",
          cur-0x3E80, n, (tbl+p7+p6)/n, tbl/n, p7/n, p6/n, poly/n, sp/n, fp/n, cp/n);
        i=j;
    }
    // worst frames by total opcodes
    printf("\nworst frames by dispatched opcodes:\n");
    std::vector<size_t> idx; for (size_t k=0;k<gRecs.size();++k) idx.push_back(k);
    for (size_t a=0;a<idx.size();++a) for (size_t b=a+1;b<idx.size();++b) {
        const Rec &A=gRecs[idx[a]], &B=gRecs[idx[b]];
        if (B.tbl+B.p7+B.p6 > A.tbl+A.p7+A.p6) { size_t t=idx[a]; idx[a]=idx[b]; idx[b]=t; }
        if (a>8) break;
    }
    printf("  %-7s %-5s %8s %8s %8s %8s %8s\n","frame","part","ops","polys","spans","fill","copy");
    for (size_t a=0; a<8 && a<idx.size(); ++a) { const Rec &r=gRecs[idx[a]];
        printf("  %-7zu %-5u %8u %8u %8u %8u %8u\n", idx[a], r.part-0x3E80,
               r.tbl+r.p7+r.p6, r.poly, r.sN+r.sB+r.sP, r.fp, r.cp); }
    /* Worst by SPANS as well as by opcodes. They are not the same frame, and
     * the rasteriser's budget is set by the span count, so reporting only the
     * opcode ranking understates the frame that actually has to fit. */
    printf("\nworst frames by spans drawn:\n");
    std::vector<size_t> sx; for (size_t k=0;k<gRecs.size();++k) sx.push_back(k);
    for (size_t a=0;a<sx.size();++a) { for (size_t b=a+1;b<sx.size();++b) {
        const Rec &A=gRecs[sx[a]], &B=gRecs[sx[b]];
        if (B.sN+B.sB+B.sP > A.sN+A.sB+A.sP) { size_t t=sx[a]; sx[a]=sx[b]; sx[b]=t; }
    } if (a>=8) break; }
    printf("  %-7s %-5s %8s %8s %8s %8s %8s\n","frame","part","ops","polys","spans","fill","copy");
    for (size_t a=0; a<8 && a<sx.size(); ++a) { const Rec &r=gRecs[sx[a]];
        printf("  %-7zu %-5u %8u %8u %8u %8u %8u\n", sx[a], r.part-0x3E80,
               r.tbl+r.p7+r.p6, r.poly, r.sN+r.sB+r.sP, r.fp, r.cp); }

    // span histogram
    uint64_t tot=0; for (int k=0;k<336;++k) tot+=gSpanHist[k];
    printf("\nspan lengths (pixels at 320 wide; bytes at 256 wide = x0.8), n=%llu\n",
           (unsigned long long)tot);
    const int edges[]={1,2,4,8,16,32,48,64,96,128,192,256,336};
    uint64_t cum=0;
    for (int e=0;e+1<(int)(sizeof(edges)/sizeof(int));++e){
        uint64_t c=0; for(int k=edges[e];k<edges[e+1];++k) c+=gSpanHist[k];
        cum+=c;
        printf("  %4d-%-4d %9llu  %5.1f%%  cum %5.1f%%\n", edges[e], edges[e+1]-1,
               (unsigned long long)c, tot?100.0*c/tot:0, tot?100.0*cum/tot:0);
    }
    uint64_t under=0; for(int k=0;k<=59;++k) under+=gSpanHist[k];  // 59px@320 = 47B@256
    uint64_t under2=0; for(int k=0;k<=139;++k) under2+=gSpanHist[k];// 139px@320 = 111B@256
    printf("\n  spans below the 47-byte DMA crossover : %5.1f%%\n", tot?100.0*under/tot:0);
    printf("  spans below the 111-byte crossover    : %5.1f%%\n", tot?100.0*under2/tot:0);
}

/* What the second round measured. Each line is here because it decides a
 * design question rather than merely describing the engine. */
static void reportStructure(void) {
    printf("\nstructure, heap and sound over the whole run\n");
    printf("  polygon records drawn        %10u\n", gPolyLeaves);
    printf("  hierarchy records walked     %10u\n", gPolyHiers);
    printf("  deepest nesting              %10u   (1 = a leaf reached directly)\n",
           gPolyDepth);
    printf("  widest fan-out               %10u   children in one record\n",
           gPolyChilds);
    printf("  most vertices in one record  %10u   -> %u-byte record\n",
           gPolyPts, 3 + 2 * gPolyPts);
    printf("  full-screen bitmaps loaded   %10u   (never in the video trace)\n",
           gBitmaps);
    printf("  peak script-heap use         %10u bytes of %u\n",
           gHeapPeak, 600 * 1024 - 0x800 * 16);
    printf("  sound.txt written for the whole run\n");
    /* The budget's denominator. A frame is allowed pause_slices * 20 ms, and
     * the received wisdom is "the scripts use 1 to 5"; this is what they
     * actually use. */
    { uint64_t n = 0; for (int k = 0; k < 16; ++k) n += gPaceHist[k];
      printf("  pause slices asked for, over %llu blits:\n",
             (unsigned long long)n);
      for (int k = 0; k < 16; ++k) if (gPaceHist[k])
          printf("      %2d slices (%3d ms) %10u  %5.1f%%\n", k, k * 20,
                 gPaceHist[k], n ? 100.0 * gPaceHist[k] / n : 0.0); }

    /* Every frame's counts, so the T-state model can be fitted and its
     * percentiles taken on the host with the per-polygon cost as a free
     * parameter. The worst frame alone decides nothing: a room entry is
     * allowed to be slow, a walking frame is not. */
    FILE *f = fopen("frames.txt", "w");
    if (f) {
        fprintf(f, "# part ops polys spans fill copy pause_slices\n");
        for (size_t k = 0; k < gRecs.size(); ++k) {
            const Rec &r = gRecs[k];
            fprintf(f, "%u %u %u %u %u %u %u\n", r.part - 0x3E80,
                    r.tbl + r.p7 + r.p6, r.poly, r.sN + r.sB + r.sP,
                    r.fp, r.cp, r.pace);
        }
        fclose(f);
        printf("  frames.txt written: %zu frames\n", gRecs.size());
    }
}

int main(int argc, char **argv) {
    const char *data = (argc>1)? argv[1] : ".";
    if (argc>2) gFrameCap = atoi(argv[2]);
    if (argc>4) gAutoplay = atoi(argv[4]);
    /* argv[5] = a part INDEX 0..9 to request, argv[6] = the frame to do it at */
    if (argc>5 && atoi(argv[5]) >= 0) gJumpPart = 0x3E80 + atoi(argv[5]);
    if (argc>6) gJumpFrame = atoi(argv[6]);
    if (argc>3 && atoi(argv[3])) {
        gTraceFrames = atoi(argv[3]); gTrace = fopen("trace.bin","wb");
        /* Dump the font rather than transcribe it: 96 glyphs of 8 bytes from
         * ' ', which the reference reads back verbatim. */
        FILE *ff = fopen("font.bin","wb");
        if (ff) { fwrite(Video::_font, 1, 768, ff); fclose(ff); }
    }
    gSnd = fopen("sound.txt", "w");
    /* The opcode stream, for the first few frames only: it is about 40 bytes an
     * opcode and the engine dispatches thousands a frame in gameplay. */
    if (gTraceFrames) {
        gOpFrames = gTraceFrames < 40 ? gTraceFrames : 40;
        gOps = fopen("ops.txt", "w");
    }
    Engine *e = new Engine(stub, data, "/tmp");
    e->init();
    e->run();
    if (gSnd) { fclose(gSnd); gSnd = NULL; }
    if (gOps) { fclose(gOps); gOps = NULL;
                printf("ops.txt written for the first %u frames\n", gOpFrames); }
    if (gTrace) {
        fclose(gTrace);
        printf("trace.bin written for the first %u frames\n", gTraceFrames);
    }
    report();
    reportStructure();
    return 0;
}
