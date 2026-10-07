#!/usr/bin/env python3
"""Record the game running in the headless harness to a video file.

Frames are rendered pixel-exactly from emulated HIRES memory at 50 fps and
the AY-3-8912 sound is synthesised from the logged register writes.

usage: oricvideo.py game.tap out.mp4 --seconds 200 [--keys a-b:KEY ...]
"""
import argparse
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from harness import Machine, Mem, load_tap, KEYMAP, T1_PERIOD  # noqa: E402
from py65.devices.mpu6502 import MPU  # noqa: E402

PAL = np.array([(0, 0, 0), (255, 0, 0), (0, 255, 0), (255, 255, 0),
                (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255)], np.uint8)
BITS = np.array([[(b >> (5 - p)) & 1 for p in range(6)] for b in range(64)], np.uint8)


def render(ram):
    """Return a 224x240 array of colour indices."""
    out = np.zeros((224, 240), np.uint8)
    mem = np.frombuffer(bytes(ram[0x9800:0xC000]), np.uint8)
    base = 0xA000 - 0x9800
    for y in range(224):
        if y < 200:
            row = mem[base + y * 40: base + y * 40 + 40]
            pats = row & 0x3F
        else:
            t, cr = (y - 200) // 8, (y - 200) % 8
            o = 0xBF68 - 0x9800 + t * 40
            row = mem[o:o + 40]
            pats = mem[(row & 0x7F).astype(np.int32) * 8 + cr] & 0x3F
        ink, paper = 7, 0
        line = out[y]
        for c in range(40):
            b = int(row[c])
            inv = 7 if b & 0x80 else 0
            if (b & 0x60) == 0:
                v = b & 0x1F
                if v < 8:
                    ink = v
                elif 16 <= v < 24:
                    paper = v - 16
                line[c * 6:c * 6 + 6] = paper ^ inv
            else:
                bits = BITS[int(pats[c])]
                line[c * 6:c * 6 + 6] = np.where(bits, ink, paper) ^ inv
    return out


VOL = [0, 0.0106, 0.0150, 0.0222, 0.0320, 0.0466, 0.0665, 0.1039,
       0.1237, 0.1986, 0.2803, 0.3548, 0.4702, 0.6030, 0.7530, 1.0]


def _lfsr_table():
    seq = np.zeros(131071, np.uint8)
    lfsr = 1
    for i in range(131071):
        bit = (lfsr ^ (lfsr >> 3)) & 1
        lfsr = (lfsr >> 1) | (bit << 16)
        seq[i] = lfsr & 1
    return seq


def synth(log, total_cycles, rate=44100, clock=1000000):
    """Small AY-3-8912 model (3 tones + noise, fixed volumes), vectorised
    over the stretches between register writes."""
    n = int(total_cycles / clock * rate)
    out = np.zeros(n, np.float32)
    vol = np.array(VOL, np.float32)
    noise_seq = _lfsr_table()
    regs = [0] * 16
    regs[7] = 0x7F
    phase = [0.0, 0.0, 0.0]
    nphase = 0.0
    step = clock / 16.0 / rate
    # segment boundaries in samples
    events = [(int(c / clock * rate), r, v) for c, r, v in log]
    events.append((n, None, None))
    pos = 0
    for smp, r, v in events:
        smp = min(max(smp, 0), n)
        if smp > pos:
            k = np.arange(smp - pos, dtype=np.float64)
            mix = regs[7]
            nper = (regs[6] & 31) or 1
            nidx = (nphase + k * step / nper).astype(np.int64) % 131071
            nval = noise_seq[nidx]
            nphase += (smp - pos) * step / nper
            acc = np.zeros(smp - pos, np.float32)
            for ch in range(3):
                per = (regs[ch * 2] | ((regs[ch * 2 + 1] & 15) << 8)) or 1
                ph = phase[ch] + k * step / per
                phase[ch] = (phase[ch] + (smp - pos) * step / per) % 1.0
                lv = regs[8 + ch] & 15
                if not lv:
                    continue
                tone = ((ph % 1.0) < 0.5) | bool((mix >> ch) & 1)
                noise = (nval == 1) | bool((mix >> (ch + 3)) & 1)
                acc += np.where(tone & noise, vol[lv], 0.0).astype(np.float32)
            out[pos:smp] = acc
            pos = smp
        if r is not None:
            regs[r] = v
    out -= out.mean()
    peak = np.abs(out).max() or 1
    return (out / peak * 0.6 * 32767).astype(np.int16)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tap')
    ap.add_argument('out')
    ap.add_argument('--seconds', type=float, default=60)
    ap.add_argument('--skip', type=float, default=0, help='seconds to run before recording')
    ap.add_argument('--keys', action='append', default=[])
    ap.add_argument('--poke', action='append', default=[],
                    help='tick:symbol=value[,symbol=value] (e.g. 10:_mono=1)')
    ap.add_argument('--log', help='write per-tick game state (frame, deck, room, x, y) here')
    args = ap.parse_args()

    syms = {}
    for line in open(args.tap.replace('.tap', '.lbl')):
        parts = line.split()
        if len(parts) >= 3:
            syms[parts[2].lstrip('.')] = int(parts[1], 16)

    def addr(x):
        if '+' in x:
            b, o = x.split('+')
            return syms[b] + int(o, 0)
        return syms[x] if x in syms else int(x, 16)

    pokes = []
    for pk in args.poke:
        pt, rest = pk.split(':')
        for kv in rest.split(','):
            a, v = kv.split('=')
            pokes.append((int(pt), addr(a), int(v, 0)))
    logf = open(args.log, 'w') if args.log else None
    logvars = [addr(n) for n in ('_frame', '_deck', '_rx', '_ry', '_p_x', '_p_y', '_p_type')]

    m = Machine()
    start, end, hdr = load_tap(args.tap, m.ram)
    mpu = MPU(memory=Mem(m), pc=start + 12)
    mpu.sp = 0xFF
    m.aylog = []

    events = []
    for k in args.keys:
        rng, names = k.split(':')
        a, b = (rng.split('-') + [None])[:2]
        events.append((int(a), int(b) if b else int(a) + 2, [KEYMAP[x] for x in names.split('+')]))

    first = int(args.skip * 50)
    last = first + int(args.seconds * 50)
    vid = args.out + '.video.mp4'
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                           '-s', '240x224', '-r', '50', '-i', '-',
                           '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', vid],
                          stdin=subprocess.PIPE)
    tick = -1
    rec_start_cycles = None
    while True:
        mpu.step()
        m.cycles = mpu.processorCycles
        t = m.cycles // T1_PERIOD
        if t == tick:
            continue
        tick = t
        m.pressed = set()
        for a, b, ks in events:
            if a <= tick < b:
                m.pressed.update(ks)
        for pt, a, v in pokes:
            if pt == tick:
                m.ram[a] = v
        if logf and tick >= first:
            logf.write('%d %s\n' % (tick - first, ' '.join(str(m.ram[a]) for a in logvars)))
        if tick == first:
            rec_start_cycles = m.cycles
        if first <= tick < last:
            ff.stdin.write(PAL[render(m.ram)].tobytes())
            if tick % 500 == 0:
                print('frame', tick - first, file=sys.stderr)
        if tick >= last:
            break
    ff.stdin.close()
    ff.wait()

    log = [(c - rec_start_cycles, r, v) for c, r, v in m.aylog]
    # carry register state from before the recording window
    state = {}
    for c, r, v in log:
        if c < 0:
            state[r] = v
    log = [(0, r, v) for r, v in state.items()] + [x for x in log if x[0] >= 0]
    pcm = synth(log, m.cycles - rec_start_cycles)
    wav = args.out + '.wav'
    with wave.open(wav, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(pcm.tobytes())
    subprocess.check_call(['ffmpeg', '-y', '-loglevel', 'error', '-i', vid, '-i', wav,
                           '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k', '-shortest', args.out])
    print('wrote', args.out)


if __name__ == '__main__':
    main()
