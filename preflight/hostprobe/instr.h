#ifndef INSTR_H
#define INSTR_H
#include <stdint.h>
extern uint32_t gOpTable, gOpPoly7, gOpPoly6, gThreads, gPolys;
extern uint16_t gPart;
extern uint32_t gSpanN, gSpanBlend, gSpanP, gFillPage, gCopyPage;
extern uint32_t gSpanHist[336];          // span length in 320-wide pixels
extern void instrFrame(void);
extern void instrPolygon(int color, int zoom, int px, int py, int bbw, int bbh,
                         int npoints, const short *xy, int page);
extern void instrOp(int kind, int a, int b, int c);   /* fill/copy/select/blit */
extern void instrChar(int ch, int x, int y, int colour, int page);
extern void instrPages(const unsigned char *p0, const unsigned char *p1,
                       const unsigned char *p2, const unsigned char *p3);            // called from Video::updateDisplay

/* ---- second round: structure, heap and sound ------------------------------
 * Added after Gate A passed, to answer four questions the first round left
 * open, each of which changes a design decision rather than a number:
 *   how deep the polygon hierarchy nests and how wide it fans   (the reader)
 *   how long one polygon record is                              (the window)
 *   how much of the 600K heap a part actually uses              (the banks)
 *   how many mixer voices are ever live at once                 (the mixer)
 */
extern uint32_t gPolyDepth, gPolyPts, gPolyChilds, gPolyLeaves, gPolyHiers;
extern uint32_t gBitmaps, gHeapPeak;
extern void instrPolyDepth(int depth, int offset);
extern void instrPolyRecord(int npoints, int zoom);
extern void instrPolyHier(int childs);
extern void instrBitmap(void);
extern void instrHeap(unsigned used, int type, int size);
extern void instrSound(int resNum, int freqIndex, int vol, int chan,
                       int len, int loopLen);
extern void instrNote(int chan, int hz, int vol, int len, int loopLen);
extern void instrMusic(int resNum, int delay, int pos);
extern void instrPace(int slices);   /* vmVariables[0xFF] at each blit */
extern void instrTick(unsigned ms);   /* the virtual clock, for sound.txt */
#endif
