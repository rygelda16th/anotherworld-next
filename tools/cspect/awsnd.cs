// AwSnd - a CSpect plugin that logs the game's own sound calls, from outside it (plan-pi-gus.md, A0).
//
// Off unless AWSND_LOG names a file. It traps execution of two jump-table slots, which every call
// from the C goes through: $8024 (aw_play_sound: SND_BLOCK's resource, frequency index, volume and
// channel at $C3B4) and $8021 (aw_play_music: MUS_BLOCK's resource, delay and position at $C3B0).
// Each call is one line: the machine's tick (AWSND_TICKS, the hex address of `ticks`), the kind, the
// operands; with AWSND_RESPAGE=<hex address of res_page>, an sfx line ends with the sound's first
// page (0: not loaded, which the game ignores). AWSND_INVAL=<hex address of aw_inval_res> logs an `inval` line whenever it runs - from
// op_updateMemList(0), a part's setup (the boot's too) or a load: each stops the player and every
// voice in the reference, and the Pi card with it (plan-pi-gus.md A3). It costs the image nothing: no marker, no byte of code.
//
// AWSND_CARD=<hex physical address>:<length> (plan-pi-gus.md A2) adds a line a second (50 frames):
// `card <frame> <ticks> <hex bytes>`, the Pi card's state block (card.inc's card_abi), read from
// its PHYSICAL address in page 11 - so it is read whatever MMU7 holds at that moment. Page 11 is
// bank 5, and CSPECT KEEPS BANKS 5 AND 7 APART (the ULA's): PeekPhysical reads stale RAM there,
// PeekPhysicalULA the real bytes, at the same address. Found by searching both for the page's
// first bytes: PeekPhysical has bank 2 at 0x8000 and page 11 nowhere; PeekPhysicalULA has it at
// 0x16000.
// AWSND_WATCH=<hex>,<hex>,... appends those words (little-endian, Z80 addresses) to each such line:
// the game's own counters, to see it run.
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
        int cardAt = 0, cardLen = 0, frame = 0, resPage = 0;
        List<int> watch = new List<int>();

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
            string c = Environment.GetEnvironmentVariable("AWSND_CARD");
            if (!string.IsNullOrEmpty(c))
            {
                string[] p = c.Split(':');
                cardAt = Convert.ToInt32(p[0], 16);
                cardLen = int.Parse(p[1]);
            }
            string w = Environment.GetEnvironmentVariable("AWSND_WATCH");
            if (!string.IsNullOrEmpty(w)) foreach (string a in w.Split(',')) watch.Add(Convert.ToInt32(a, 16));
            io.Add(new sIO(0x8024, eAccess.Memory_EXE, 1, 0));
            io.Add(new sIO(0x8021, eAccess.Memory_EXE, 2, 0));
            string rp = Environment.GetEnvironmentVariable("AWSND_RESPAGE");
            if (!string.IsNullOrEmpty(rp)) resPage = Convert.ToInt32(rp, 16);
            string iv = Environment.GetEnvironmentVariable("AWSND_INVAL");
            if (!string.IsNullOrEmpty(iv)) io.Add(new sIO(Convert.ToInt32(iv, 16), eAccess.Memory_EXE, 3, 0));
            log.WriteLine("# awsnd up");
            return io;
        }

        int B(int a) { return CSpect.Peek((ushort)a); }
        int Phys(int a)
        {
            int bank = a >> 14;
            return (bank == 5 || bank == 7) ? CSpect.PeekPhysicalULA(a) : CSpect.PeekPhysical(a);
        }
        int Ticks() { return ticksAt == 0 ? 0 : (B(ticksAt) | (B(ticksAt + 1) << 8)); }

        public byte Read(eAccess _t, int _p, int _id, out bool _valid)
        {
            _valid = false;
            if (off || _t != eAccess.Memory_EXE) return 0;
            if (_id == 1)
                log.WriteLine(string.Format("sfx {0} {1} {2} {3} {4}{5}", Ticks(), B(0xC3B4), B(0xC3B5), B(0xC3B6), B(0xC3B7),
                    resPage == 0 ? "" : " " + B(resPage + B(0xC3B4))));
            else if (_id == 2)
                log.WriteLine(string.Format("music {0} {1} {2} {3}", Ticks(), B(0xC3B0), B(0xC3B1) | (B(0xC3B2) << 8), B(0xC3B3)));
            else if (_id == 3)
                log.WriteLine(string.Format("inval {0}", Ticks()));
            return 0;
        }

        public void Tick()
        {
            if (off || cardAt == 0 || (++frame % 50) != 0) return;
            var sb = new System.Text.StringBuilder();
            sb.AppendFormat("card {0} {1} ", frame, Ticks());
            for (int i = 0; i < cardLen; i++) sb.AppendFormat("{0:X2}", Phys(cardAt + i));
            foreach (int a in watch) sb.AppendFormat(" {0}", B(a) | (B(a + 1) << 8));
            log.WriteLine(sb.ToString());
        }
        public void OSTick() { }
        public bool Write(eAccess _t, int _p, int _id, byte _v) { return false; }
        public bool KeyPressed(int _id) { return false; }
        public void Reset() { }
        public void Quit() { if (log != null) log.Close(); }
    }
}
