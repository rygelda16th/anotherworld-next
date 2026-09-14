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

/* ---- third round: the polygon reader ------------------------------------
 * Gate C proved the rasteriser against geometry the probe recorded AFTER
 * readVertices had applied the zoom, which was right - it left one thing under
 * test - but it means the reader, the zoom multiply and the record structure are
 * outside every gate so far. These log the TOP-LEVEL draw calls, the two opcode
 * forms in vm.cpp, and dump the raw polygon segments they index into, so a
 * reference reader can be proved to emit exactly the same fillPolygon calls the
 * engine does.
 */
extern void instrDraw(int useVideo2, int off, int colour, int zoom, int x, int y);
extern void instrSegments(const unsigned char *cine, int cineSize,
                          const unsigned char *v2, int v2Size);

/* ---- fourth round: the opcode stream ------------------------------------
 * Gate D's third claim. A VM that is wrong in one opcode is a VM that renders
 * almost correctly, which is the worst kind of wrong to debug at the end - so
 * the stream is compared thread by thread and opcode by opcode before any
 * picture is. This logs (thread, pc, opcode) as the engine dispatches them, plus
 * the bytecode segment itself, so the port can be fed exactly the same input.
 */
extern void instrOpcode(int thread, int pc, int opcode);
extern void instrThread(int thread, int pc);
extern void instrFrameEdge(void);
extern void instrBytecode(const unsigned char *code, int size);
extern void instrSeed(int seed);

/* ---- fifth round: reaching a later part ---------------------------------
 * Every measurement in this project comes from two parts out of ten, because the
 * probe can only reach what synthetic input can play. The game's own route to a
 * later part is the password screen, and its codes are not in the data. So the
 * part is requested directly instead - which the engine's own comments say can
 * crash - and the report says plainly which parts produced sane figures and which
 * did not, rather than averaging the two together.
 */
extern int instrJumpPart(unsigned frame);
extern unsigned instrFrameNow(void);

/* ---- sixth round: the full-screen bitmap path ---------------------------
 * Step 9 found where these live - 70 of them load in the arena - so the deplaner
 * in tools/mkassets.py can finally be compared against the engine's own, which is
 * the only part of the asset pipeline that has never been checked against
 * anything. instrBitmapId records which resource it is; instrBitmapDump writes the
 * engine's page 0 straight after copyPage has filled it.
 */
extern void instrBitmapId(int id);
extern void instrBitmapDump(const unsigned char *page0);
/* ---- seventh round: WHICH resources, by id -------------------------------
 * I3's second claim - "the port asked for the same resources the engine did" - had no
 * oracle. instrHeap already logs every load, but keyed by time, type and size, so a port
 * that silently SKIPPED a load passed the other two claims and this one could not be
 * written at all. This logs the id, on its own file, so nothing that already parses
 * sound.txt changes.
 */
extern void instrLoadId(int id, int type, int size);
extern void instrPace(int slices);   /* vmVariables[0xFF] at each blit */
extern void instrTick(unsigned ms);   /* the virtual clock, for sound.txt */
#endif
