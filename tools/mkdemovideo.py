#!/usr/bin/env python3
"""Build the side-by-side demo video: the ZX Spectrum original and the Oric
port playing the same demo script (demo/demo_script.txt).

usage: mkdemovideo.py spectrum.mp4 oric.mp4 out.mp4 [--script ...]

1920x1080 at 50 fps.  Spectrum on the left (320x240 with border, x3), Oric
on the right (240x224, x3).  The current script step is captioned under
the two screens.  Audio: Spectrum on the left channel, Oric on the right.
"""
import argparse
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (14, 14, 24)
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
SPEC_X, SPEC_Y = 40, 190
ORIC_BOX_X, ORIC_BOX_Y, ORIC_BOX_W = 1040, 190, 840
ORIC_X, ORIC_Y = ORIC_BOX_X + (ORIC_BOX_W - 720) // 2, ORIC_BOX_Y + (720 - 672) // 2
CAP_Y = 925


def font(size):
    return ImageFont.truetype(FONT, size)


def centred(d, y, text, size, fill, cx=W // 2):
    f = font(size)
    w = d.textlength(text, font=f)
    d.text((cx - w / 2, y), text, font=f, fill=fill)


def rainbow(d, y, text, size, cx=W // 2):
    cols = [(255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 80, 80)]
    f = font(size)
    x = cx - d.textlength(text, font=f) / 2
    for i, ch in enumerate(text):
        d.text((x, y), ch, font=f, fill=cols[i % len(cols)])
        x += d.textlength(ch, font=f)


def load_script(path):
    steps = []
    for line in open(path):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(None, 2)
        steps.append((float(parts[0]), parts[1], parts[2] if len(parts) > 2 else ''))
    return steps


def make_background(path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    rainbow(d, 24, "QUAZATRON  vs  ORICTRON", 68)
    centred(d, 106, "The ZX Spectrum original and the Oric Atmos port playing the same demo script",
            32, (200, 200, 220))
    centred(d, 148, "ZX SPECTRUM 48K  -  Quazatron, Graftgold / Hewson 1986", 25, (255, 90, 90),
            cx=SPEC_X + 480)
    centred(d, 148, "ORIC ATMOS  -  Orictron, new port 2026", 25, (90, 220, 255),
            cx=ORIC_BOX_X + ORIC_BOX_W // 2)
    d.rectangle([ORIC_BOX_X, ORIC_BOX_Y, ORIC_BOX_X + ORIC_BOX_W - 1, ORIC_BOX_Y + 719], fill=(0, 0, 0))
    d.rectangle([40, CAP_Y - 10, W - 40, CAP_Y + 60], fill=(30, 30, 48))
    centred(d, 1010, "Audio: Spectrum on the left channel, Oric AY-3-8912 on the right", 22, (150, 150, 170))
    centred(d, 1040, "Spectrum: a real player's recorded session, replayed in Fuse.   "
            "Oric: the same script played in an emulated Oric Atmos.", 20, (120, 120, 140))
    im.save(path)


def make_caption(path, n, step, text):
    im = Image.new("RGBA", (W - 80, 70), (30, 30, 48, 255))
    d = ImageDraw.Draw(im)
    f1, f2 = font(30), font(30)
    label = "Step %d  %s" % (n, step)
    d.text((24, 16), label, font=f1, fill=(255, 220, 90))
    d.text((24 + d.textlength(label, font=f1) + 40, 16), text, font=f2, fill=(235, 235, 245))
    im.save(path)


def make_title(path, steps):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    rainbow(d, 250, "QUAZATRON  vs  ORICTRON", 96)
    centred(d, 400, "ZX Spectrum original  -  Oric Atmos port", 44, (210, 210, 230))
    centred(d, 480, "Both machines play the same demo script:", 34, (180, 180, 200))
    seen = []
    for _, s, _ in steps:
        if s not in seen and s not in ('END',):
            seen.append(s)
    centred(d, 530, "  -  ".join(x.lower() for x in seen), 30, (255, 220, 90))
    centred(d, 700, "Isometric decks  -  droid transfer battles  -  lifts between decks", 30, (150, 150, 170))
    im.save(path)


def make_credits(path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    rainbow(d, 260, "ORICTRON", 90)
    centred(d, 390, "Oric Atmos port of Quazatron - new code and graphics, built with cc65", 36, (210, 210, 230))
    centred(d, 450, "Same deck style, status panel, transfer battle and text screens as the Spectrum game", 30,
            (170, 170, 190))
    centred(d, 560, "Quazatron (c) 1986 Graftgold / Hewson Consultants - original by Steve Turner", 30,
            (255, 120, 120))
    centred(d, 620, "Spectrum footage: an archive.org RZX recording of a real player, replayed in Fuse", 26,
            (150, 150, 170))
    im.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spectrum")
    ap.add_argument("oric")
    ap.add_argument("out")
    ap.add_argument("--script", default="demo/demo_script.txt")
    args = ap.parse_args()

    steps = load_script(args.script)
    T = [t for t, s, _ in steps if s == 'END'][0]
    tmp = tempfile.mkdtemp()
    bg, title, cred = (os.path.join(tmp, n) for n in ("bg.png", "title.png", "credits.png"))
    make_background(bg)
    make_title(title, steps)
    make_credits(cred)
    caps = []
    n = 0
    for k, (t, s, text) in enumerate(steps):
        if s == 'END':
            break
        n += 1
        p = os.path.join(tmp, "cap%02d.png" % k)
        make_caption(p, n, s, text)
        caps.append((t, steps[k + 1][0], p))

    CARD = 5
    inputs = ["-loop", "1", "-framerate", "50", "-i", bg,
              "-i", args.spectrum, "-i", args.oric,
              "-loop", "1", "-framerate", "50", "-i", title,
              "-loop", "1", "-framerate", "50", "-i", cred]
    for _, _, p in caps:
        inputs += ["-loop", "1", "-framerate", "50", "-i", p]
    fc = (f"[1:v]trim=duration={T},setpts=PTS-STARTPTS,fps=50,scale=960:720:flags=neighbor[sv];"
          f"[2:v]trim=duration={T},setpts=PTS-STARTPTS,fps=50,scale=720:672:flags=neighbor[ov];"
          f"[0:v]fps=50,trim=duration={T},format=yuv420p[bgv];"
          f"[bgv][sv]overlay={SPEC_X}:{SPEC_Y}:shortest=1[t1];"
          f"[t1][ov]overlay={ORIC_X}:{ORIC_Y}:shortest=1[t2];")
    last = "t2"
    for k, (a, b, _) in enumerate(caps):
        fc += (f"[{5 + k}:v]fps=50,trim=duration={T},format=rgba[c{k}];"
               f"[{last}][c{k}]overlay=40:{CAP_Y - 10}:enable='between(t,{a},{b - 0.02})'[m{k}];")
        last = f"m{k}"
    fc += (f"[{last}]format=yuv420p,setsar=1[main];"
           f"[1:a]atrim=duration={T},asetpts=PTS-STARTPTS,pan=mono|c0=0.5*c0+0.5*c1,aresample=48000[sa];"
           f"[2:a]atrim=duration={T},asetpts=PTS-STARTPTS,volume=0.7,aresample=48000[oa];"
           f"[sa][oa]join=inputs=2:channel_layout=stereo[mainA];"
           f"[3:v]fps=50,trim=duration={CARD},format=yuv420p,setsar=1,"
           f"fade=in:st=0:d=1,fade=out:st={CARD - 1}:d=1[tv];"
           f"[4:v]fps=50,trim=duration={CARD + 2},format=yuv420p,setsar=1,"
           f"fade=in:st=0:d=1,fade=out:st={CARD + 1}:d=1[cv];"
           f"anullsrc=r=48000:cl=stereo,atrim=duration={CARD}[ta];"
           f"anullsrc=r=48000:cl=stereo,atrim=duration={CARD + 2}[ca];"
           f"[tv][ta][main][mainA][cv][ca]concat=n=3:v=1:a=1[v][a]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stats"] + inputs + [
        "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-tune", "animation",
        "-pix_fmt", "yuv420p", "-r", "50",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", args.out]
    subprocess.check_call(cmd)


if __name__ == "__main__":
    main()
