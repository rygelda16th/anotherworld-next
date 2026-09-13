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

void instrOp(int kind, int a, int b, int c) {
    if (!gTrace || gFrameNo >= gTraceFrames) return;
    w8(kind);
    if (kind == 2)      { w8(a); w8(b); }
    else if (kind == 3) { w8(a); w8(b); w16(c); }
    else                { w8(a); }
}

uint32_t gOpTable, gOpPoly7, gOpPoly6, gThreads, gPolys;
uint32_t gSpanN, gSpanBlend, gSpanP, gFillPage, gCopyPage;
uint32_t gSpanHist[336];
uint16_t gPart = 0;

struct Rec { uint16_t part; uint32_t tbl, p7, p6, th, poly, sN, sB, sP, fp, cp; };
static std::vector<Rec> gRecs;
static uint32_t gFrameCap = 4000;

void instrFrame(void) {
    ++gFrameNo;          /* here, not in the stub: see instrPages */
    Rec r; r.part=gPart; r.tbl=gOpTable; r.p7=gOpPoly7; r.p6=gOpPoly6; r.th=gThreads;
    r.poly=gPolys; r.sN=gSpanN; r.sB=gSpanBlend; r.sP=gSpanP; r.fp=gFillPage; r.cp=gCopyPage;
    gRecs.push_back(r);
    gOpTable=gOpPoly7=gOpPoly6=gThreads=gPolys=gSpanN=gSpanBlend=gSpanP=gFillPage=gCopyPage=0;
}

struct Headless : System {
    uint32_t _now = 0;
    void init(const char *) {}
    void destroy() {}
    void setPalette(const uint8_t *) {}
    void updateDisplay(const uint8_t *) {
        if (gRecs.size() >= gFrameCap) input.quit = true;
    }
    void processEvents() {}
    void sleep(uint32_t d) { _now += d; }
    uint32_t getTimeStamp() { return _now; }
    void startAudio(AudioCallback, void *) {}
    void stopAudio() {}
    uint32_t getOutputSampleRate() { return 22050; }
    int addTimer(uint32_t, TimerCallback, void *) { return 1; }
    void removeTimer(int) {}
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

int main(int argc, char **argv) {
    const char *data = (argc>1)? argv[1] : ".";
    if (argc>2) gFrameCap = atoi(argv[2]);
    if (argc>3) {
        gTraceFrames = atoi(argv[3]); gTrace = fopen("trace.bin","wb");
        /* Dump the font rather than transcribe it: 96 glyphs of 8 bytes from
         * ' ', which the reference reads back verbatim. */
        FILE *ff = fopen("font.bin","wb");
        if (ff) { fwrite(Video::_font, 1, 768, ff); fclose(ff); }
    }
    Engine *e = new Engine(stub, data, "/tmp");
    e->init();
    e->run();
    if (gTrace) {
        fclose(gTrace);
        printf("trace.bin written for the first %u frames\n", gTraceFrames);
    }
    report();
    return 0;
}
