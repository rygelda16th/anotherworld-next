// AwSnd - a CSpect plugin that logs the game's own sound calls, from outside it (plan-pi-gus.md, A0).
//
// Off unless AWSND_LOG names a file. It traps execution of two jump-table slots, which every call
// from the C goes through: $8024 (aw_play_sound: SND_BLOCK's resource, frequency index, volume and
// channel at $C3B4) and $8021 (aw_play_music: MUS_BLOCK's resource, delay and position at $C3B0).
// Each call is one line: the machine's tick (AWSND_TICKS, the hex address of `ticks`), the kind, the
// operands. It costs the image nothing: no marker, no byte of code.
//
// Build: mcs -target:library -r:<CSpect>/Plugin.dll -out:<CSpect>/AwSnd.dll awsnd.cs
using System;
using System.IO;
using System.Collections.Generic;
using Plugin;

namespace AwSnd
{
    public class Probe : iPlugin
    {
        iCSpect CSpect;
        StreamWriter log;
        bool off = true;
        int ticksAt = 0;

        public List<sIO> Init(iCSpect _CSpect)
        {
            CSpect = _CSpect;
            List<sIO> io = new List<sIO>();
            string path = Environment.GetEnvironmentVariable("AWSND_LOG");
            if (string.IsNullOrEmpty(path)) return io;
            off = false;
            log = new StreamWriter(path);
            log.AutoFlush = true;
            string t = Environment.GetEnvironmentVariable("AWSND_TICKS");
            if (!string.IsNullOrEmpty(t)) ticksAt = Convert.ToInt32(t, 16);
            io.Add(new sIO(0x8024, eAccess.Memory_EXE, 1, 0));
            io.Add(new sIO(0x8021, eAccess.Memory_EXE, 2, 0));
            log.WriteLine("# awsnd up");
            return io;
        }

        int B(int a) { return CSpect.Peek((ushort)a); }
        int Ticks() { return ticksAt == 0 ? 0 : (B(ticksAt) | (B(ticksAt + 1) << 8)); }

        public byte Read(eAccess _t, int _p, int _id, out bool _valid)
        {
            _valid = false;
            if (off || _t != eAccess.Memory_EXE) return 0;
            if (_id == 1)
                log.WriteLine(string.Format("sfx {0} {1} {2} {3} {4}", Ticks(), B(0xC3B4), B(0xC3B5), B(0xC3B6), B(0xC3B7)));
            else if (_id == 2)
                log.WriteLine(string.Format("music {0} {1} {2} {3}", Ticks(), B(0xC3B0), B(0xC3B1) | (B(0xC3B2) << 8), B(0xC3B3)));
            return 0;
        }

        public void Tick() { }
        public void OSTick() { }
        public bool Write(eAccess _t, int _p, int _id, byte _v) { return false; }
        public bool KeyPressed(int _id) { return false; }
        public void Reset() { }
        public void Quit() { if (log != null) log.Close(); }
    }
}
