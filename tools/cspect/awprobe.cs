// AWProbe - a CSpect plugin that samples the Z80 from OUTSIDE the machine.
//
// Every marker so far has cost resident bytes below CC_ORG and answered one bit each. The
// emulator's own plugin interface hands over PC, SP, IFF1, IM and I directly, so the questions
// "are interrupts enabled", "what mode", "which vector page" and "where is it stuck" all get
// answered at once, from a build with no diagnostic code in it at all.
using System;
using System.Collections.Generic;
using System.IO;
using Plugin;

namespace AWProbe
{
    class BinaryStream : IDisposable
    {
        FileStream fs;
        public BinaryStream(string path) { fs = new FileStream(path, FileMode.Create); }
        public void Text(string t) { foreach (char c in t) fs.WriteByte((byte)c); }
        public void Byte(byte b) { fs.WriteByte(b); }
        public void Dispose() { fs.Close(); }
    }

    public class Probe : iPlugin
    {
        // CSpect 4's iPlugin asks for these; CSpect 3 never calls them
        public string GetName() { return "awprobe"; }
        public string GetDescription() { return "anotherworld-next's awprobe check plugin"; }

        iCSpect CSpect;
        StreamWriter log;
        string logPath;
        Dictionary<int, long> hist = new Dictionary<int, long>();
        long ticks = 0, osticks = 0, samples = 0;
        int reports = 0;
        System.Diagnostics.Stopwatch sw = new System.Diagnostics.Stopwatch();
        long nextReport = 1000;
        int maxReports = 40;

        // EXECUTION TRAPS. The frame trail put the break between clear_code's ldir and the
        // machine running inside the bytecode window, which is MMU0/MMU1 at $0000-$3FFF - not
        // ROM. Trapping execution of every address in that window catches the jump into data on
        // its FIRST instruction, with the stack still holding whatever put it there.
        //
        // OPT-IN, AWPROBE_LOWTRAP=<hex arm>:<hex mark> (clear_code and load_code's rst $08, from the
        // .exp). They were hard-coded as $8731 and $876E, which the code moved under: in the 320x256
        // build they are the input code, run every frame, so the probe armed at once, counted
        // esxDOS's own RST $08 at $0008 as faults and quit CSpect after 24 file calls (the Pi card's
        // upload; found by the GUS session, 2026-10-01). Unset, there are no low-window traps at all.
        const int WIN_TOP = 0x4000;
        int lowArm = -1, lowMark = -1;
        bool off = false;
        int goAddr = 0;
        int blitAddr = 0; List<int> blitAts = new List<int>();
        // AWPROBE_DDMA=<hex ddma_have>:<hex n_ddma> (plan-ddma.md D1), both in the CPU's map: both in every
        // report, and once as the ENTER wait is released, so a run that pokes ddma_have to 0 shows
        // the fills that went by the zxnDDMA before the poke and none after.
        int ddmaHave = 0, ddmaN = -1;
        // AWPROBE_PEEK=<hex addr>:<decimal length>[,...] logs those bytes of the CPU's map in every
        // report, one `# peek@<addr>` line a range (preflight/ddma's bench: its results, its screen).
        List<int[]> peeks = new List<int[]>();
        int paceTicks = 0, paceBlit = 0, pacePoly = 0, lastBlit = -1;
        StreamWriter pace;
        int streamPlayed = 0, streamAvail = 0;
        // AWPROBE_POKE="addr=val,addr=val" (hex) is written the frame BEFORE the ENTER wait is
        // released, so a run can choose its part and turn the synthetic player on.
        List<int[]> pokes = new List<int[]>();
        // AWPROBE_VOICES=<hex addr of the voice records> counts active voices every frame.
        // AWPROBE_STACK=<lo>:<hi> traps every WRITE in that range and keeps the lowest address
        // written: the stack's real high-water mark, not an estimate.
        int stackLo = 0, stackHi = 0, stackMin = 0x10000;
        // AWPROBE_PROF=<first blit>:<last blit> writes a profile to <log>.prof: at every frame
        // interrupt the address it interrupted is the word at SP, so that is sampled instead of PC
        // (which is always the IM2 trampoline at that instant). Needs AWPROBE_PACE for the blit count.
        int profLo = -1, profHi = -1; Dictionary<int, long> prof = new Dictionary<int, long>(); long profN = 0;
        // AWPROBE_NRLOG=<hex reg> traps every write to that Next register - from the CPU or, if the
        // emulator routes them the same way, from the copper - and checks each value steps by +-8
        // from the last, which is coptest's triangle.
        // AWPROBE_TEXTWATCH=1 traps writes to $E000-$EDFF and reports those made while MMU7 maps page 1,
        // TEXT_PAGE - the font and the strings, which nothing should ever write after boot.
        bool textWatch = false; int textHits = 0; long textAll = 0;
        int nrReg = -1; long nrWrites = 0, nrGood = 0, nrBad = 0; int nrLast = -1;
        int voicesAddr = 0; long[] voiceHist = new long[5]; long voiceFrames = 0, voiceSum = 0;
        bool armed = false;
        int trapped = 0;

        public List<sIO> Init(iCSpect _CSpect)
        {
            CSpect = _CSpect;
            // OPT IN, ALWAYS. The plugin quits the emulator when it has seen enough
            // reports, and registers sixteen thousand execution traps to do it, so an
            // ordinary play session must not get either. No AWPROBE_LOG, no probe.
            string p = Environment.GetEnvironmentVariable("AWPROBE_LOG");
            if (string.IsNullOrEmpty(p)) { off = true; return new List<sIO>(); }
            logPath = p;
            log = new StreamWriter(p);
            log.AutoFlush = true;
            string g = Environment.GetEnvironmentVariable("AWPROBE_GO");
            if (!string.IsNullOrEmpty(g)) goAddr = Convert.ToInt32(g, 16);
            // AWPROBE_BLIT=<hex addr of n_blit>:<decimal count>[,<count>...] dumps the screen once for
            // each count, the first frame the game's own blit counter reaches it - so a named scene
            // is captured, rather than whatever happened to be up at a round number of seconds. The
            // file is named by the counter as it was (100000 + n_blit): two blits in one frame skip one.
            string bl = Environment.GetEnvironmentVariable("AWPROBE_BLIT");
            if (!string.IsNullOrEmpty(bl))
            {
                var parts = bl.Split(':'); blitAddr = Convert.ToInt32(parts[0], 16);
                foreach (var c in parts[1].Split(',')) blitAts.Add(int.Parse(c));
                blitAts.Sort();
            }
            string pe = Environment.GetEnvironmentVariable("AWPROBE_PEEK");
            if (!string.IsNullOrEmpty(pe))
                foreach (var r in pe.Split(','))
                {
                    var q = r.Split(':');
                    peeks.Add(new int[] { Convert.ToInt32(q[0], 16), int.Parse(q[1]) });
                }
            string dd = Environment.GetEnvironmentVariable("AWPROBE_DDMA");
            if (!string.IsNullOrEmpty(dd)) { var q = dd.Split(':'); ddmaHave = Convert.ToInt32(q[0], 16); ddmaN = Convert.ToInt32(q[1], 16); }
            // AWPROBE_PACE=<ticks>:<n_blit>:<n_poly> writes one line per blit to <log>.pace:
            // the game's own 50 Hz tick count, the VM's frame count and the polygon count at
            // the moment the blit counter moved. Emulated time throughout, so the host's speed
            // does not enter into it.
            string pc = Environment.GetEnvironmentVariable("AWPROBE_PACE");
            if (!string.IsNullOrEmpty(pc))
            {
                var q = pc.Split(':');
                paceTicks = Convert.ToInt32(q[0], 16); paceBlit = Convert.ToInt32(q[1], 16); pacePoly = Convert.ToInt32(q[2], 16);
                pace = new StreamWriter(p + ".pace"); pace.AutoFlush = true;
                pace.WriteLine("# blit ticks vmframes polys");
            }
            string sm = Environment.GetEnvironmentVariable("AWPROBE_STREAM");
            if (!string.IsNullOrEmpty(sm))
            {
                var q = sm.Split(':');
                streamPlayed = Convert.ToInt32(q[0], 16); streamAvail = Convert.ToInt32(q[1], 16);
            }
            string pk = Environment.GetEnvironmentVariable("AWPROBE_POKE");
            if (!string.IsNullOrEmpty(pk))
                foreach (var kv in pk.Split(','))
                {
                    var q = kv.Split('=');
                    pokes.Add(new int[] { Convert.ToInt32(q[0], 16), Convert.ToInt32(q[1], 16) });
                }
            string st = Environment.GetEnvironmentVariable("AWPROBE_STACK");
            if (!string.IsNullOrEmpty(st)) { var q = st.Split(':'); stackLo = Convert.ToInt32(q[0], 16); stackHi = Convert.ToInt32(q[1], 16); }
            textWatch = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("AWPROBE_TEXTWATCH"));
            string nr = Environment.GetEnvironmentVariable("AWPROBE_NRLOG");
            if (!string.IsNullOrEmpty(nr)) nrReg = Convert.ToInt32(nr, 16);
            string pf = Environment.GetEnvironmentVariable("AWPROBE_PROF");
            if (!string.IsNullOrEmpty(pf)) { var q = pf.Split(':'); profLo = int.Parse(q[0]); profHi = int.Parse(q[1]); }
            string va = Environment.GetEnvironmentVariable("AWPROBE_VOICES");
            if (!string.IsNullOrEmpty(va)) voicesAddr = Convert.ToInt32(va, 16);
            string lt = Environment.GetEnvironmentVariable("AWPROBE_LOWTRAP");
            if (!string.IsNullOrEmpty(lt))
            {
                string[] q = lt.Split(':');
                lowArm = Convert.ToInt32(q[0], 16);
                lowMark = q.Length > 1 ? Convert.ToInt32(q[1], 16) : -1;
            }
            string m = Environment.GetEnvironmentVariable("AWPROBE_MAX");
            if (!string.IsNullOrEmpty(m)) int.TryParse(m, out maxReports);
            log.WriteLine("# AWProbe up");
            sw.Start();

            var io = new List<sIO>();
            // Arm only once our own code is running: the NEX loader and the ROM execute the
            // low window legitimately before that, and those hits are not the fault.
            if (lowArm >= 0) for (int a = 0; a < WIN_TOP; a++) io.Add(new sIO(a, eAccess.Memory_EXE, 0, 0));
            if (nrReg >= 0) io.Add(new sIO(nrReg, eAccess.NextReg_Write, 2, 0));
            if (textWatch) for (int a = 0xE000; a < 0xEE00; a++) io.Add(new sIO(a, eAccess.Memory_Write, 4, 0));
            // THE PROFILER SAMPLES AT THE IM2 TRAMPOLINE, from an execution trap: with the copper
            // driving the DAC the game's interrupts are LINE interrupts, and the frame-time Tick no
            // longer lands on the trampoline. At $CECE the interrupt has just pushed the address it
            // interrupted, so it is the word at SP.
            if (profLo >= 0) io.Add(new sIO(0xCECE, eAccess.Memory_EXE, 3, 0));
            for (int a = stackLo; stackHi != 0 && a < stackHi; a++) io.Add(new sIO(a, eAccess.Memory_Write, 1, 0));
            if (lowArm >= 0) io.Add(new sIO(lowArm, eAccess.Memory_EXE, 0, 0));    // clear_code
            if (lowMark >= 0) io.Add(new sIO(lowMark, eAccess.Memory_EXE, 0, 0));  // load_code's rst $08
            return io;
        }

        void Sample()
        {
            Z80Regs r = CSpect.GetRegs();
            if (r == null) return;
            samples++;
            int pc = r.PC;
            long n;
            hist.TryGetValue(pc, out n);
            hist[pc] = n + 1;

            if (sw.ElapsedMilliseconds < nextReport) return;
            nextReport += 1000;
            reports++;

            // The top of the histogram IS the answer: a hung machine spends every sample in a
            // handful of addresses, a running one spreads across thousands.
            var top = new List<KeyValuePair<int, long>>(hist);
            top.Sort((a, b) => b.Value.CompareTo(a.Value));
            var sb = new System.Text.StringBuilder();
            sb.AppendFormat("t={0,3}s ticks={1,-10} osticks={2,-6} distinct_pc={3,-6} IFF1={4} IM={5} I=${6:X2} SP=${7:X4}",
                            sw.ElapsedMilliseconds / 1000, ticks, osticks, hist.Count,
                            r.IFF1 ? 1 : 0, r.IM, r.I, r.SP);
            sb.AppendFormat("  ticks={0} frames={1} polys={2} blits={3} loads={4} err={5} L2bank={6} L2cfg=${7:X2} L2on={8} turbo={9}",
                            W(0x9B69), W(0x9C0B + 6), W(0x9B70), W(0x9B78), W(0x9BFC), CSpect.Peek(0x87DC),
                            CSpect.GetNextRegister(0x12, -1), CSpect.GetNextRegister(0x70, -1),
                            (CSpect.GetNextRegister(0x69, -1) & 0x80) != 0 ? 1 : 0, CSpect.GetNextRegister(0x07, -1));
            sb.Append("  top:");
            for (int i = 0; i < top.Count && i < 8; i++)
                sb.AppendFormat(" ${0:X4}={1:0.0}%", top[i].Key, 100.0 * top[i].Value / samples);
            log.WriteLine(sb.ToString());
            if (ddmaN >= 0) log.WriteLine(DdmaLine());
            foreach (var pr in peeks)
            {
                var pk = new System.Text.StringBuilder(string.Format("# peek@{0:X4}", pr[0]));
                for (int i = 0; i < pr[1]; i++) pk.AppendFormat(" {0:X2}", CSpect.Peek((ushort)(pr[0] + i)));
                log.WriteLine(pk.ToString());
            }
            hist.Clear();
            samples = 0;
            if (textWatch) log.WriteLine(string.Format("# text watch: {0} writes to $E000-$EDFF seen, {1} while MMU7 was page 1", textAll, textHits));
            if (nrReg >= 0) log.WriteLine(string.Format("# nextreg ${0:X2}: {1} writes, {2} steps of 8, {3} others, osticks {4}", nrReg, nrWrites, nrGood, nrBad, osticks));
            if (stackHi != 0) log.WriteLine(string.Format("# stack low-water: ${0:X4}", stackMin));
            if (voiceFrames > 0)
                log.WriteLine(string.Format("# voices so far: mean {0:0.00} over {1} frames; 0:{2} 1:{3} 2:{4} 3:{5} 4:{6}",
                    (double)voiceSum / voiceFrames, voiceFrames, voiceHist[0], voiceHist[1], voiceHist[2], voiceHist[3], voiceHist[4]));
            if (reports % 15 == 0 || reports >= maxReports) DumpScreen(reports);
            if (reports >= maxReports) CSpect.SetGlobal(eGlobal.DoQuit, true);
        }

        // Both are per-frame (~50 Hz), so sample on every one.
        int W(int a) { return CSpect.Peek((ushort)a) | (CSpect.Peek((ushort)(a + 1)) << 8); }
        string DdmaLine()
        {
            return string.Format("# ddma have={0} n={1}", CSpect.Peek((ushort)ddmaHave), W(ddmaN));
        }

        // THE VISIBLE LAYER 2 PAGE, straight out of the banks, as a PPM. 256x192 at 8bpp is
        // three 8K banks; NextReg $12 names the first of them and the palette comes from the
        // emulator's own table, so this is what is on the glass, not what we think is.
        void DumpScreen(int n)
        {
            int bank = CSpect.GetNextRegister(0x12, -1);       // in 16K banks
            int baseAddr = bank * 0x4000;
            // NextReg $70 bits 5-4 say which layout: 01 is 320x256, column-major across five 16K
            // banks (address = x * 256 + y), the game's normal build since 2026-10-01; 00 is
            // 256x192, row-major across three (address = y * 256 + x). Read it rather than assume.
            bool wide = ((CSpect.GetNextRegister(0x70, -1) >> 4) & 3) == 1;
            int w = wide ? 320 : 256, h = wide ? 256 : 192;
            var px = new byte[w * h];
            for (int i = 0; i < px.Length; i++) px[i] = CSpect.PeekPhysical(baseAddr + i);
            string path = string.Format("{0}.{1}.ppm", logPath, n);
            using (var f = new BinaryStream(path))
            {
                f.Text(string.Format("P6\n{0} {1}\n255\n", w, h));
                for (int y = 0; y < h; y++)
                    for (int x = 0; x < w; x++)
                    {
                        //
                        // GetColour hands back the NINE-BIT palette word, not 24-bit RGB:
                        // RRRGGGBB with bit 8 carrying blue's low bit. Read as 0xRRGGBB it
                        // is pure blue at a twentieth of its brightness, which is exactly
                        // what the first dumps looked like.
                        uint c = CSpect.GetColour(1, wide ? px[x * 256 + y] : px[y * 256 + x]);
                        int r = (int)((c >> 5) & 7), g = (int)((c >> 2) & 7);
                        int b = (int)(((c & 3) << 1) | ((c >> 8) & 1));
                        f.Byte((byte)(r * 255 / 7)); f.Byte((byte)(g * 255 / 7)); f.Byte((byte)(b * 255 / 7));
                    }
            }
            log.WriteLine("# screen -> " + path);
            var pal = new System.Text.StringBuilder("# palette:");
            for (int i = 0; i < 16; i++) pal.AppendFormat(" {0:X8}", CSpect.GetColour(1, i));
            log.WriteLine(pal.ToString());
        }

        // AWPROBE_GO releases the ENTER wait from outside, so the SHIPPED image - the one
        // that waits at its title screen - can be run unattended without building a
        // different one. It pokes the flag the key handler would have poked.
        public void Tick()
        {
            if (off) return;
            ticks++;
            if (ticks == 149) foreach (var pp in pokes) CSpect.Poke((ushort)pp[0], (byte)pp[1]);
            if (voicesAddr != 0 && ticks > 150)
            {
                int n = 0;
                for (int v = 0; v < 4; v++) if (CSpect.Peek((ushort)(voicesAddr + v * 18 + 11)) != 0) n++;
                voiceHist[n]++; voiceFrames++; voiceSum += n;
            }
            if (goAddr != 0 && ticks == 150)
            {
                CSpect.Poke((ushort)goAddr, 1); log.WriteLine("# released the ENTER wait");
                if (ddmaN >= 0) log.WriteLine(DdmaLine() + " at go");
            }
            if (false)
            {
                int bb = 0; Z80Regs rr = null;
                {
                    int ret = W(rr.SP);
                    long c0; prof.TryGetValue(ret, out c0); prof[ret] = c0 + 1; profN++;
                    if ((profN & 63) == 0)
                    {
                        var top = new List<KeyValuePair<int, long>>(prof);
                        top.Sort((x, y) => y.Value.CompareTo(x.Value));
                        using (var pw = new StreamWriter(logPath + ".prof"))
                        {
                            pw.WriteLine("# samples " + profN);
                            foreach (var kv in top) pw.WriteLine(string.Format("{0:X4} {1}", kv.Key, kv.Value));
                        }
                    }
                }
            }
            if (pace != null)
            {
                int b = W(paceBlit);
                if (b != lastBlit)
                {
                    lastBlit = b;
                    // AWPROBE_STREAM=<st_played>:<st_avail> adds the emulator's own frame count and the
                    // streamed music's two 24-bit counters, so lost ticks and a dry ring show per blit.
                    if (streamPlayed != 0)
                        pace.WriteLine("{0} {1} {2} {3} {4} {5} {6} on={7} eof={8}", b, W(paceTicks), W(0xC008), W(pacePoly), ticks,
                            W(streamPlayed) | (CSpect.Peek((ushort)(streamPlayed + 2)) << 16),
                            W(streamAvail) | (CSpect.Peek((ushort)(streamAvail + 2)) << 16),
                            CSpect.Peek((ushort)(streamPlayed - 1)), CSpect.Peek((ushort)(streamAvail + 3)));
                    else
                        pace.WriteLine("{0} {1} {2} {3}", b, W(paceTicks), W(0xC008), W(pacePoly));
                }
            }
            if (blitAddr != 0 && blitAts.Count > 0 && W(blitAddr) >= blitAts[0])
            {
                int b = W(blitAddr);
                while (blitAts.Count > 0 && blitAts[0] <= b) blitAts.RemoveAt(0);
                DumpScreen(100000 + b);
            }
            Sample();
        }
        public void OSTick() { osticks++; }
        public bool Write(eAccess _t, int _p, int _id, byte _v)
        {
            if (_t == eAccess.Memory_Write && _id == 4)
            {
                textAll++;
                if (ticks > 150 && textHits < 40 && CSpect.GetNextRegister(0x57, -1) == 1)
                {
                    textHits++;
                    Z80Regs r = CSpect.GetRegs();
                    var sb = new System.Text.StringBuilder();
                    sb.AppendFormat("TEXTWRITE ${0:X4}=${1:X2} PC=${2:X4} SP=${3:X4} IFF1={4} blit={5} MMU=", _p, _v, r.PC, r.SP, r.IFF1 ? 1 : 0, paceBlit != 0 ? W(paceBlit) : -1);
                    for (int m = 0; m < 8; m++) sb.AppendFormat("{0}{1}", m == 0 ? "" : ",", CSpect.GetNextRegister((byte)(0x50 + m), -1));
                    sb.Append(" stack:");
                    for (int i = 0; i < 8; i++) sb.AppendFormat(" ${0:X4}", W((r.SP + 2 * i) & 0xFFFF));
                    log.WriteLine(sb.ToString());
                }
                return false;
            }
            if (_t == eAccess.NextReg_Write && _id == 2)
            {
                nrWrites++;
                if (nrLast >= 0) { int d = _v - nrLast; if (d == 8 || d == -8) nrGood++; else nrBad++; }
                nrLast = _v;
                return false;
            }
            if (_t == eAccess.Memory_Write && _id == 1 && ticks > 150 && _p < stackMin) stackMin = _p;
            return false;                       // never swallow the write
        }

        public byte Read(eAccess _t, int _p, int _id, out bool _valid)
        {
            _valid = false;                     // never substitute the opcode - just watch
            if (off || _t != eAccess.Memory_EXE) return 0;

            if (_id == 3 && profLo >= 0 && paceBlit != 0)
            {
                int bb = W(paceBlit);
                if (bb >= profLo && bb <= profHi)
                {
                    Z80Regs rr = CSpect.GetRegs();
                    int ret = W(rr.SP);
                    long c0; prof.TryGetValue(ret, out c0); prof[ret] = c0 + 1; profN++;
                    if ((profN & 63) == 0)
                    {
                        var top = new List<KeyValuePair<int, long>>(prof);
                        top.Sort((x, y) => y.Value.CompareTo(x.Value));
                        using (var pw = new StreamWriter(logPath + ".prof"))
                        {
                            pw.WriteLine("# samples " + profN);
                            foreach (var kv in top) pw.WriteLine(string.Format("{0:X4} {1}", kv.Key, kv.Value));
                        }
                    }
                }
                return 0;
            }
            if (lowArm < 0) return 0;
            if (_p == lowArm) { if (!armed) log.WriteLine("# armed at clear_code"); armed = true; return 0; }
            if (_p == lowMark) { log.WriteLine("# load_code rst $08 reached"); return 0; }
            if (!armed || _p >= WIN_TOP || trapped >= 24) return 0;

            Z80Regs r = CSpect.GetRegs();
            var sb = new System.Text.StringBuilder();
            sb.AppendFormat("EXE ${0:X4}  SP=${1:X4} IFF1={2} IM={3} I=${4:X2} AF=${5:X4} BC=${6:X4} DE=${7:X4} HL=${8:X4} IX=${9:X4}",
                            _p, r.SP, r.IFF1 ? 1 : 0, r.IM, r.I, r.AF, r.BC, r.DE, r.HL, r.IX);
            sb.Append("  stack:");
            for (int i = 0; i < 10; i++)
            {
                int a = (r.SP + i * 2) & 0xFFFF;
                sb.AppendFormat(" ${0:X4}", CSpect.Peek((ushort)a) | (CSpect.Peek((ushort)((a + 1) & 0xFFFF)) << 8));
            }
            sb.Append("  MMU=");
            for (int m = 0; m < 8; m++) sb.AppendFormat("{0}{1}", m == 0 ? "" : ",", CSpect.GetNextRegister((byte)(0x50 + m), -1));
            log.WriteLine(sb.ToString());
            if (++trapped >= 24) { log.WriteLine("# trapped enough"); CSpect.SetGlobal(eGlobal.DoQuit, true); }
            return 0;
        }
        public bool KeyPressed(int _id) { return false; }
        public void Reset() { }
        public void Quit() { if (!off && log != null && voiceFrames > 0) {
                log.WriteLine(string.Format("# voices: mean {0:0.00} over {1} frames; 0:{2} 1:{3} 2:{4} 3:{5} 4:{6}",
                    (double)voiceSum / voiceFrames, voiceFrames, voiceHist[0], voiceHist[1], voiceHist[2], voiceHist[3], voiceHist[4])); }
            if (!off && log != null) { log.WriteLine("# AWProbe down"); log.Close(); } }
    }
}
