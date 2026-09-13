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
#endif
