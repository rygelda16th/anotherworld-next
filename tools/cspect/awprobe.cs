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
        const int WIN_TOP = 0x4000;
        bool off = false;
        int goAddr = 0;
        int blitAddr = 0, blitAt = 0; bool blitDumped = false;
        int paceTicks = 0, paceBlit = 0, pacePoly = 0, lastBlit = -1;
        StreamWriter pace;
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
            // AWPROBE_BLIT=<hex addr of n_blit>:<decimal count> dumps the screen once, the
            // first frame the game's own blit counter reaches that count - so a named scene
            // is captured, rather than whatever happened to be up at a round number of seconds.
            string bl = Environment.GetEnvironmentVariable("AWPROBE_BLIT");
            if (!string.IsNullOrEmpty(bl)) { var parts = bl.Split(':'); blitAddr = Convert.ToInt32(parts[0], 16); blitAt = int.Parse(parts[1]); }
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
            string m = Environment.GetEnvironmentVariable("AWPROBE_MAX");
            if (!string.IsNullOrEmpty(m)) int.TryParse(m, out maxReports);
            log.WriteLine("# AWProbe up");
            sw.Start();

            var io = new List<sIO>();
            for (int a = 0; a < WIN_TOP; a++) io.Add(new sIO(a, eAccess.Memory_EXE, 0, 0));
            // Arm only once our own code is running: the NEX loader and the ROM execute the
            // low window legitimately before that, and those hits are not the fault.
            io.Add(new sIO(0x8731, eAccess.Memory_EXE, 0, 0));   // clear_code
            io.Add(new sIO(0x876E, eAccess.Memory_EXE, 0, 0));   // load_code's rst $08
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
            hist.Clear();
            samples = 0;
            if (reports % 15 == 0 || reports >= maxReports) DumpScreen(reports);
            if (reports >= maxReports) CSpect.SetGlobal(eGlobal.DoQuit, true);
        }

        // Both are per-frame (~50 Hz), so sample on every one.
        int W(int a) { return CSpect.Peek((ushort)a) | (CSpect.Peek((ushort)(a + 1)) << 8); }

        // THE VISIBLE LAYER 2 PAGE, straight out of the banks, as a PPM. 256x192 at 8bpp is
        // three 8K banks; NextReg $12 names the first of them and the palette comes from the
        // emulator's own table, so this is what is on the glass, not what we think is.
        void DumpScreen(int n)
        {
            int bank = CSpect.GetNextRegister(0x12, -1);       // in 16K banks
            int baseAddr = bank * 0x4000;
            var px = new byte[256 * 192];
            for (int i = 0; i < px.Length; i++) px[i] = CSpect.PeekPhysical(baseAddr + i);
            string path = string.Format("{0}.{1}.ppm", logPath, n);
            using (var f = new BinaryStream(path))
            {
                f.Text("P6\n256 192\n255\n");
                for (int y = 0; y < 192; y++)
                    for (int x = 0; x < 256; x++)
                    {
                        // 256x192 8bpp Layer 2 is a flat row-major bitmap across three 16K
                        // banks: 64 rows each, address = y * 256 + x.
                        //
                        // GetColour hands back the NINE-BIT palette word, not 24-bit RGB:
                        // RRRGGGBB with bit 8 carrying blue's low bit. Read as 0xRRGGBB it
                        // is pure blue at a twentieth of its brightness, which is exactly
                        // what the first dumps looked like.
                        uint c = CSpect.GetColour(1, px[y * 256 + x]);
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
            if (goAddr != 0 && ticks == 150) { CSpect.Poke((ushort)goAddr, 1); log.WriteLine("# released the ENTER wait"); }
            if (pace != null)
            {
                int b = W(paceBlit);
                if (b != lastBlit) { lastBlit = b; pace.WriteLine("{0} {1} {2} {3}", b, W(paceTicks), W(0xC008), W(pacePoly)); }
            }
            if (blitAddr != 0 && !blitDumped && W(blitAddr) >= blitAt) { blitDumped = true; DumpScreen(100000 + W(blitAddr)); }
            Sample();
        }
        public void OSTick() { osticks++; }
        public bool Write(eAccess _t, int _p, int _id, byte _v) { return false; }

        public byte Read(eAccess _t, int _p, int _id, out bool _valid)
        {
            _valid = false;                     // never substitute the opcode - just watch
            if (off || _t != eAccess.Memory_EXE) return 0;

            if (_p == 0x8731) { if (!armed) log.WriteLine("# armed at clear_code"); armed = true; return 0; }
            if (_p == 0x876E) { log.WriteLine("# load_code rst $08 reached"); return 0; }
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
        public void Quit() { if (!off && log != null) { log.WriteLine("# AWProbe down"); log.Close(); } }
    }
}
