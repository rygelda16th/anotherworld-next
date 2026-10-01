// AwIdle - a CSpect plugin that measures how much of each blit the game spends WAITING.
//
// tools/wide320.py needs it: to project what a slower renderer would do to the intro's speed, the
// projection has to know each blit's busy time, and the pace log alone cannot tell it - a blit that
// finished early waited in pace_blit, and the ticks between blits include that wait.
//
// So it samples where the CPU was at every interrupt, from an execution trap on the IM2 trampoline
// (AWIDLE_TRAMP, hex, default CECE): there the interrupt has just pushed the address it interrupted.
// If that address is in one of AWIDLE_RANGES ("lo-hi,lo-hi", hex, hi exclusive) - pace_blit's wait,
// and the streamed music's card reads it calls while waiting - the sample is idle. Two interrupts
// a frame, so a sample is 10 ms. At each change of n_blit (AWIDLE_BLIT, hex) it writes a line to
// AWIDLE_LOG: blit, ticks (AWIDLE_TICKS, hex), samples so far, idle samples so far.
//
// The plugin API has no T-state counter (Z80Regs carries none), so the interrupt's own share of the
// machine is measured in ZEsarUX instead: tools/wide320.py `isr`.
//
// Off unless AWIDLE_LOG is set. Costs the image nothing.
// Build: mcs -target:library -r:<CSpect>/Plugin.dll -out:<CSpect>/AwIdle.dll awidle.cs
using System;
using System.IO;
using System.Collections.Generic;
using Plugin;

namespace AwIdle
{
    public class Probe : iPlugin
    {
        iCSpect CSpect;
        StreamWriter log;
        bool off = true;
        int blitAt, ticksAt, tramp = 0xCECE, lastBlit = -1;
        long samples, idle;
        List<int[]> ranges = new List<int[]>();

        public List<sIO> Init(iCSpect _CSpect)
        {
            CSpect = _CSpect;
            var io = new List<sIO>();
            string path = Environment.GetEnvironmentVariable("AWIDLE_LOG");
            if (string.IsNullOrEmpty(path)) return io;
            off = false;
            log = new StreamWriter(path);
            log.AutoFlush = true;
            blitAt = Convert.ToInt32(Environment.GetEnvironmentVariable("AWIDLE_BLIT"), 16);
            ticksAt = Convert.ToInt32(Environment.GetEnvironmentVariable("AWIDLE_TICKS"), 16);
            string t = Environment.GetEnvironmentVariable("AWIDLE_TRAMP");
            if (!string.IsNullOrEmpty(t)) tramp = Convert.ToInt32(t, 16);
            foreach (string r in Environment.GetEnvironmentVariable("AWIDLE_RANGES").Split(','))
            {
                var q = r.Split('-');
                ranges.Add(new int[] { Convert.ToInt32(q[0], 16), Convert.ToInt32(q[1], 16) });
            }
            log.WriteLine("# blit ticks samples idle");
            io.Add(new sIO(tramp, eAccess.Memory_EXE, 1, 0));
            return io;
        }

        int W(int a) { return CSpect.Peek((ushort)a) | (CSpect.Peek((ushort)(a + 1)) << 8); }

        public byte Read(eAccess _t, int _p, int _id, out bool _valid)
        {
            _valid = false;
            if (off || _t != eAccess.Memory_EXE || _id != 1) return 0;
            int ret = W(CSpect.GetRegs().SP);
            samples++;
            foreach (var r in ranges) if (ret >= r[0] && ret < r[1]) { idle++; break; }
            return 0;
        }

        public void Tick()
        {
            if (off) return;
            int b = W(blitAt);
            if (b == lastBlit) return;
            lastBlit = b;
            log.WriteLine("{0} {1} {2} {3}", b, W(ticksAt), samples, idle);
        }
        public void OSTick() { }
        public bool Write(eAccess _t, int _p, int _id, byte _v) { return false; }
        public bool KeyPressed(int _id) { return false; }
        public void Reset() { }
        public void Quit() { if (log != null) log.Close(); }
    }
}
