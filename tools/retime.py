#!/usr/bin/env python3
"""Retime one Oric recording onto another's timeline, game frame for game frame.

Two runs of the same deterministic demo play identical game frames, but they
can drift in wall-clock time: mono mode draws rooms slightly faster.  Using
the per-tick state logs written by oricvideo.py --log, every output frame
shows the slave run at the same game frame (and the same offset into that
frame) as the master run.

usage: retime.py master.log slave.log slave.mp4 out.mp4
"""
import subprocess
import sys

W, H = 240, 224
FRAME = W * H * 3


def frames_by_tick(path):
    """Return per tick: (unwrapped game frame, first tick of that frame)."""
    out, first = [], {}
    prev, wrap = None, 0
    for t, line in enumerate(open(path)):
        fr = int(line.split()[1])
        if prev is not None and fr < prev:
            wrap += 256
        prev = fr
        f = fr + wrap
        first.setdefault(f, t)
        out.append(f)
    return out, first


def main():
    mlog, slog, svid, out = sys.argv[1:5]
    mf, mfirst = frames_by_tick(mlog)
    sf, sfirst = frames_by_tick(slog)
    n_slave = len(sf)

    src = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-i', svid, '-f', 'rawvideo',
                            '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    dst = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo',
                            '-pix_fmt', 'rgb24', '-s', '%dx%d' % (W, H), '-r', '50', '-i', '-',
                            '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', out],
                           stdin=subprocess.PIPE)
    cur_idx, cur = -1, None
    for t, f in enumerate(mf):
        if f in sfirst:
            want = sfirst[f] + (t - mfirst[f])
            nxt = sfirst.get(f + 1, n_slave)
            want = min(want, nxt - 1)
        else:
            want = n_slave - 1
        want = max(want, cur_idx)          # never go backwards
        while cur_idx < want:
            buf = src.stdout.read(FRAME)
            if len(buf) < FRAME:
                break
            cur, cur_idx = buf, cur_idx + 1
        dst.stdin.write(cur)
    dst.stdin.close()
    dst.wait()
    src.stdout.close()
    src.wait()
    print('wrote', out)


if __name__ == '__main__':
    main()
