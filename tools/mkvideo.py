#!/usr/bin/env python3
"""Build the YouTube side-by-side comparison: ZX Spectrum original vs Oric port.

usage: mkvideo.py spectrum.mp4 oric.mp4 out.mp4 [--seconds 180]

Layout (1920x1080, 50 fps): Spectrum footage on the left (960x720, as
captured with border), Oric footage on the right at 3x integer scale, title
and credit cards before/after.  Audio: Spectrum on the left channel, Oric on
the right.
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


def font(size):
    return ImageFont.truetype(FONT, size)


def centred(d, y, text, size, fill, cx=W // 2):
    f = font(size)
    w = d.textlength(text, font=f)
    d.text((cx - w / 2, y), text, font=f, fill=fill)


def rainbow(d, y, text, size):
    cols = [(255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0)]
    f = font(size)
    x = W / 2 - d.textlength(text, font=f) / 2
    for i, ch in enumerate(text):
        d.text((x, y), ch, font=f, fill=cols[i % len(cols)])
        x += d.textlength(ch, font=f)


def make_background(path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    rainbow(d, 28, "QUAZATRON", 72)
    centred(d, 112, "ZX Spectrum original  vs  Oric Atmos port", 34, (200, 200, 220))
    centred(d, 150, "ZX SPECTRUM 48K  -  Graftgold / Hewson, 1986", 26, (255, 90, 90),
            cx=SPEC_X + 480)
    centred(d, 150, "ORIC ATMOS  -  new port, 2026", 26, (90, 220, 255),
            cx=ORIC_BOX_X + ORIC_BOX_W // 2)
    # Oric panel backdrop (the Oric's black border)
    d.rectangle([ORIC_BOX_X, ORIC_BOX_Y, ORIC_BOX_X + ORIC_BOX_W - 1, ORIC_BOX_Y + 719],
                fill=(0, 0, 0))
    centred(d, 935, "Left: monochrome Spectrum graphics      Right: Oric HIRES with per-droid colour attributes",
            26, (210, 210, 210))
    centred(d, 975, "Audio: Spectrum on the left channel, Oric AY-3-8912 on the right",
            24, (150, 150, 170))
    centred(d, 1012, "Spectrum: real-player RZX recording replayed in Fuse    "
            "Oric: the port's built-in demo mode, captured from emulated video memory",
            20, (120, 120, 140))
    im.save(path)


def make_title(path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    rainbow(d, 300, "QUAZATRON", 150)
    centred(d, 500, "ZX Spectrum (1986)  vs  Oric Atmos (2026)", 56, (230, 230, 240))
    centred(d, 600, "A side-by-side comparison of the original and a new Oric port", 34,
            (170, 170, 190))
    centred(d, 700, "6502 assembly + C (cc65)  -  isometric HIRES  -  multicolour", 30,
            (90, 220, 255))
    im.save(path)


def make_credits(path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    rainbow(d, 260, "QUAZATRON", 110)
    lines = [
        ("Quazatron (c) 1986 Graftgold Ltd / Hewson Consultants.", (230, 230, 240)),
        ("Designed by Steve Turner. Spectrum footage: archive.org RZX recording, Fuse emulator.", (190, 190, 210)),
        ("", None),
        ("The Oric Atmos version is an original reimplementation of the gameplay:", (90, 220, 255)),
        ("new code (C + 6502 assembly) and new graphics; no original code or assets.", (90, 220, 255)),
        ("", None),
        ("Load quazatron.tap on an Oric Atmos or emulator - it autoruns.", (255, 255, 0)),
    ]
    y = 440
    for text, col in lines:
        if text:
            centred(d, y, text, 34, col)
        y += 56
    im.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spectrum")
    ap.add_argument("oric")
    ap.add_argument("out")
    ap.add_argument("--seconds", type=float, default=180)
    ap.add_argument("--spec-start", type=float, default=0)
    ap.add_argument("--oric-start", type=float, default=0)
    args = ap.parse_args()

    tmp = tempfile.mkdtemp()
    bg, title, cred = (os.path.join(tmp, n) for n in ("bg.png", "title.png", "credits.png"))
    make_background(bg)
    make_title(title)
    make_credits(cred)

    T, CARD = args.seconds, 5
    fc = (
        # side-by-side section
        f"[1:v]trim=start={args.spec_start}:duration={T},setpts=PTS-STARTPTS,fps=50[sv];"
        f"[2:v]trim=start={args.oric_start}:duration={T},setpts=PTS-STARTPTS,fps=50,"
        f"scale=720:672:flags=neighbor[ov];"
        f"[0:v]fps=50,trim=duration={T},format=yuv420p[bgv];"
        f"[bgv][sv]overlay={SPEC_X}:{SPEC_Y}:shortest=1[t1];"
        f"[t1][ov]overlay={ORIC_X}:{ORIC_Y}:shortest=1,format=yuv420p,setsar=1[main];"
        f"[1:a]atrim=start={args.spec_start}:duration={T},asetpts=PTS-STARTPTS,"
        f"pan=mono|c0=0.5*c0+0.5*c1,aresample=48000[sa];"
        f"[2:a]atrim=start={args.oric_start}:duration={T},asetpts=PTS-STARTPTS,"
        f"volume=0.7,aresample=48000[oa];"
        f"[sa][oa]join=inputs=2:channel_layout=stereo[mainA];"
        # cards with fades
        f"[3:v]fps=50,trim=duration={CARD},format=yuv420p,setsar=1,"
        f"fade=in:st=0:d=1,fade=out:st={CARD - 1}:d=1[tv];"
        f"[4:v]fps=50,trim=duration={CARD + 2},format=yuv420p,setsar=1,"
        f"fade=in:st=0:d=1,fade=out:st={CARD + 1}:d=1[cv];"
        f"anullsrc=r=48000:cl=stereo,atrim=duration={CARD}[ta];"
        f"anullsrc=r=48000:cl=stereo,atrim=duration={CARD + 2}[ca];"
        f"[tv][ta][main][mainA][cv][ca]concat=n=3:v=1:a=1[v][a]"
    )
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stats",
           "-loop", "1", "-framerate", "50", "-i", bg,
           "-i", args.spectrum, "-i", args.oric,
           "-loop", "1", "-framerate", "50", "-i", title,
           "-loop", "1", "-framerate", "50", "-i", cred,
           "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-tune", "animation",
           "-pix_fmt", "yuv420p", "-r", "50",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", args.out]
    subprocess.check_call(cmd)
    for p in (bg, title, cred):
        im = Image.open(p)
        im.save(os.path.splitext(args.out)[0] + "_" + os.path.basename(p))


if __name__ == "__main__":
    main()
