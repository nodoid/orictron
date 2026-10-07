#!/usr/bin/env python3
"""Play the demo script (demo/demo_script.txt) on the Oric port in the
headless harness and record it to video, like oricvideo.py.

The script comes from a Spectrum player's session.  EXPLORE steps replay the
Spectrum player's own recorded keys (mapped Sinclair joystick -> Oric keys).
The decks differ between the two machines, so HUNT, GRAPPLE and LIFT steps
are carried out by a small autopilot here that reads the game's memory and
presses keys.  Transfer battles are played by the game's own transfer AI.

usage: oricdemo.py game.tap out.mp4 [--script demo/demo_script.txt]
"""
import argparse
import os
import random
import subprocess
import sys
import wave
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Machine, Mem, load_tap, KEYMAP, T1_PERIOD  # noqa: E402
from oricvideo import PAL, render, synth  # noqa: E402
from py65.devices.mpu6502 import MPU  # noqa: E402

TILES, DHDR, SCREEN = 0x9110, 0x9100, 0xA000
WALK = {1, 3, 4, 5}                 # floor, pad, energiser, lift
K_PAD, K_LIFT = 3, 5

# Sinclair joystick keys on the Spectrum -> Oric keys
SPEC2ORIC = {'9': ['UP', 'LEFT'], '7': ['UP', 'RIGHT'], '8': ['DOWN', 'RIGHT'],
             '6': ['DOWN', 'LEFT'], '0': ['SPACE']}
# world direction (dx, dy) -> Oric keys
DIRKEYS = {(-1, -1): ['UP'], (1, 1): ['DOWN'], (-1, 1): ['LEFT'], (1, -1): ['RIGHT'],
           (-1, 0): ['UP', 'LEFT'], (1, 0): ['DOWN', 'RIGHT'],
           (0, -1): ['UP', 'RIGHT'], (0, 1): ['DOWN', 'LEFT']}


def load_script(path):
    steps = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(None, 2)
        steps.append((float(parts[0]), parts[1], parts[2] if len(parts) > 2 else ''))
    return steps


def load_keys(path):
    out = []
    for line in open(path):
        if line.startswith('#') or not line.strip():
            continue
        parts = line.split()
        out.append((int(parts[0]), parts[1:]))
    return out


def sgn(v, dead=0):
    return 1 if v > dead else (-1 if v < -dead else 0)


class Pilot:
    def __init__(self, m, syms):
        self.m, self.r, self.s = m, m.ram, syms
        self.bfs_target = None
        self.dist = None
        self.last_pos = None
        self.still = 0
        self.wander = 0
        self.wdir = (0, 0)
        self.grab_t = 0
        self.done = False
        self.rnd = random.Random(5)

    def b(self, name, off=0):
        return self.r[self.s[name] + off]

    def tile(self, i, j):
        if not (0 <= i < 16 and 0 <= j < 16):
            return 0
        return self.r[TILES + (j << 4) + i]

    def step_ok(self, a, b):
        ta, tb = self.tile(*a), self.tile(*b)
        if (tb >> 2) not in WALK or (ta >> 2) not in WALK:
            return False
        la, lb = ta & 3, tb & 3
        if la == lb:
            return True
        return abs(la - lb) == 1 and K_PAD in ((ta >> 2), (tb >> 2))

    def bfs(self, target):
        if target == self.bfs_target and self.dist is not None:
            return
        dist = {target: 0}
        q = deque([target])
        while q:
            c = q.popleft()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                if n not in dist and self.step_ok(n, c):
                    dist[n] = dist[c] + 1
                    q.append(n)
        self.dist = dist
        self.bfs_target = target

    def player(self):
        return self.b('_p_x'), self.b('_p_y')

    def droids(self):
        eh = self.b('_eh') | (self.b('_eh', 1) << 8)
        nd = self.b('_nd')
        out = []
        for k in range(nd):
            if self.r[eh + k]:
                out.append((self.b('_a_x', k), self.b('_a_y', k)))
        return out

    def keys_for(self, d):
        return list(DIRKEYS.get(d, []))

    def unstick(self, d):
        """if we keep trying to move but don't, wander for a moment"""
        pos = self.player()
        if self.wander:
            self.wander -= 1
            return self.wdir
        if d != (0, 0) and pos == self.last_pos:
            self.still += 1
            if self.still > 40:
                self.still = 0
                self.wander = 25
                self.wdir = self.rnd.choice(list(DIRKEYS))
                return self.wdir
        else:
            self.still = 0
        self.last_pos = pos
        return d

    def goto(self, tx, ty):
        """direction to walk towards world point (tx, ty) along the tiles"""
        px, py = self.player()
        self.bfs((tx // 12, ty // 12))
        c = (px // 12, py // 12)
        if c == self.bfs_target or c not in self.dist:
            return (sgn(tx - px, 1), sgn(ty - py, 1))
        best = min(((c[0] + dx, c[1] + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))),
                   key=lambda n: self.dist.get(n, 999))
        cx, cy = best[0] * 12 + 6, best[1] * 12 + 6
        if best[1] == c[1]:
            return (sgn(cx - px), sgn(cy - py, 1))
        return (sgn(cx - px, 1), sgn(cy - py))

    def nearest(self):
        px, py = self.player()
        ds = self.droids()
        if not ds:
            return None
        return min(ds, key=lambda d: max(abs(d[0] - px), abs(d[1] - py)))

    def hunt(self, tick):
        px, py = self.player()
        t = self.nearest()
        if t is None:
            return self.lift(tick)
        dx, dy = t[0] - px, t[1] - py
        adx, ady = abs(dx), abs(dy)
        lv = lambda x, y: self.tile(x // 12, y // 12) & 3
        aligned = adx < 5 or ady < 5 or abs(adx - ady) < 5
        if aligned and max(adx, ady) < 70 and lv(px, py) == lv(*t):
            d = (0 if adx < 5 else sgn(dx), 0 if ady < 5 else sgn(dy))
            if max(adx, ady) < 22:
                d = (-d[0], -d[1])          # too close: back off (and turn)
                return self.keys_for(d) + (['SPACE'] if (tick // 3) % 2 else [])
            return self.keys_for(d) + (['SPACE'] if (tick // 3) % 2 else [])
        d = self.unstick(self.goto(t[0], t[1] - (12 if dy > 0 else -12) if ady > adx else t[1]))
        return self.keys_for(d)

    def grapple(self, tick):
        t = self.nearest()
        if t is None:
            return self.lift(tick)
        if not self.b('_p_grab'):
            # stand still holding fire until the game says GRAPPLE
            self.grab_t += 1
            if self.grab_t < 70:
                return ['SPACE']
            self.grab_t = 0
            return []
        self.grab_t = 0
        d = self.unstick(self.goto(t[0], t[1]))
        if d == (0, 0):
            d = (sgn(t[0] - self.player()[0]), sgn(t[1] - self.player()[1]))
        return self.keys_for(d)

    def lift(self, tick):
        lx, ly = self.r[DHDR + 10] * 12 + 6, self.r[DHDR + 11] * 12 + 6
        px, py = self.player()
        if (self.tile(px // 12, py // 12) >> 2) == K_LIFT:
            return ['L'] if (tick // 4) % 2 else []
        return self.keys_for(self.unstick(self.goto(lx, ly)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tap')
    ap.add_argument('out')
    ap.add_argument('--script', default='demo/demo_script.txt')
    ap.add_argument('--keys', default='demo/spectrum_keys.txt')
    ap.add_argument('--seconds', type=float, default=None)
    ap.add_argument('--log', default=None)
    args = ap.parse_args()

    syms = {}
    for line in open(args.tap.replace('.tap', '.lbl')):
        parts = line.split()
        if len(parts) >= 3:
            syms[parts[2].lstrip('.')] = int(parts[1], 16)
    steps = load_script(args.script)
    spec_keys = load_keys(args.keys)
    end_t = args.seconds or [t for t, s, _ in steps if s == 'END'][0]

    m = Machine()
    start, _, _ = load_tap(args.tap, m.ram)
    mpu = MPU(memory=Mem(m), pc=start + 12)
    mpu.sp = 0xFF
    m.aylog = []
    pilot = Pilot(m, syms)
    r = m.ram
    logf = open(args.log, 'w') if args.log else None

    last = int(end_t * 50)
    vid = args.out + '.video.mp4'
    ff = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                           '-s', '240x224', '-r', '50', '-i', '-',
                           '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', vid],
                          stdin=subprocess.PIPE)
    tick = -1
    ki = 0
    held = []
    started = False
    prev_step = None
    lift_from = None                 # deck we are trying to leave by lift
    while True:
        mpu.step()
        m.cycles = mpu.processorCycles
        tk = m.cycles // T1_PERIOD
        if tk == tick:
            continue
        tick = tk
        t = tick / 50.0
        step = [s for s in steps if s[0] <= t][-1][1]
        # recorded Spectrum keys at this moment
        while ki < len(spec_keys) and spec_keys[ki][0] <= tick:
            held = spec_keys[ki][1]
            ki += 1
        in_transfer = r[SCREEN + 40 * 40 + 21] == 0x04 and r[SCREEN + 40 * 40] == 0x11
        in_play = (not in_transfer and r[SCREEN + 40 * 40] == 0x11 and
                   r[SCREEN + 40 * 40 + 39] == 0x11 and r[SCREEN + 40 * 40 + 1] < 8)
        keys = []
        demo = 0
        if step != prev_step:
            pilot.grab_t = 0
            if step == 'GRAPPLE':
                pilot.done = False
            if step == 'LIFT':
                lift_from = r[syms['_deck']]
            prev_step = step
        # a lift step carries on until the Oric has changed deck - once
        if lift_from is not None and r[syms['_deck']] != lift_from:
            lift_from = -1
        if lift_from is not None and lift_from >= 0 and step in ('HUNT', 'EXPLORE'):
            step = 'LIFT'
        elif lift_from == -1 and step == 'LIFT':
            step = 'HUNT'
        # it's a demo: keep the player's energy up so it can't end early
        if in_play and r[syms['_p_hp']] < 12:
            r[syms['_p_hp']] = 20
        if in_transfer:
            pilot.done = True
            demo = 1                    # the game's own transfer AI plays
        elif step == 'TITLE':
            pass
        elif not in_play:
            # title (after START or a game over) or a text screen: fire
            if step == 'START' or not started or (tick // 25) % 4 == 0:
                keys = ['SPACE'] if tick % 50 < 3 else []
                if keys:
                    started = True
        elif step == 'EXPLORE':
            for k in held:
                keys += SPEC2ORIC.get(k, [])
        elif step in ('HUNT', 'RESULT'):
            keys = pilot.hunt(tick)
        elif step in ('GRAPPLE', 'TRANSFER'):
            # one transfer per grapple step, then back to hunting
            keys = pilot.hunt(tick) if pilot.done else pilot.grapple(tick)
        elif step == 'LIFT':
            keys = pilot.lift(tick)
        r[syms['_demo']] = demo
        m.pressed = set(KEYMAP[k] for k in keys)
        if logf:
            logf.write('%d %s %d %d %d %s\n' % (tick, step, in_play, in_transfer, r[syms['_deck']],
                                               '+'.join(keys)))
        if tick == 0:
            rec_start = m.cycles
        ff.stdin.write(PAL[render(r)].tobytes())
        if tick % 500 == 0:
            print('t=%.0fs %s' % (t, step), file=sys.stderr)
        if tick >= last:
            break
    ff.stdin.close()
    ff.wait()

    log = [(c - rec_start, rg, v) for c, rg, v in m.aylog]
    log = [(max(c, 0), rg, v) for c, rg, v in log]
    pcm = synth(log, m.cycles - rec_start)
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
