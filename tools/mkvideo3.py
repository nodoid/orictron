#!/usr/bin/env python3
"""Three-panel YouTube video: Spectrum original | Oric mono | Oric colour.

usage: mkvideo3.py spectrum_native.mkv spectrum_audio.mp4 oric_mono.mp4 \
                   oric_colour.mp4 out.mp4 [--seconds 180]

1920x1080, 50 fps.  Every panel is an exact 2x nearest-neighbour scale.
Each panel is labelled underneath, centred.  Audio: Spectrum on the left
channel, Oric on the right.
"""
import argparse
import os
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mkvideo import W, H, BG, font, centred, rainbow, make_title, make_credits  # noqa: E402

PW, PH = 608, 456                      # panel size (2x of 304x228)
GAP = (W - 3 * PW) // 4
PX = [GAP, 2 * GAP + PW, 3 * GAP + 2 * PW]
PY = 200
ORIC_OX, ORIC_OY = (PW - 480) // 2, (PH - 448) // 2

LABELS = [
    ("ZX Spectrum - Original", "Graftgold / Hewson, 1986", (255, 90, 90)),
    ("Oric Atmos - Monochrome", "new port, mono playfield", (230, 230, 230)),
    ("Oric Atmos - Colour", "new port, colour playfield", (90, 220, 255)),
]


def make_background(path):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    rainbow(d, 30, "QUAZATRON", 80)
    centred(d, 128, "ZX Spectrum original  vs  Oric Atmos port in mono and colour", 34,
            (200, 200, 220))
    for i, (title, sub, col) in enumerate(LABELS):
        x = PX[i]
        d.rectangle([x, PY, x + PW - 1, PY + PH - 1], fill=(0, 0, 0))
        cx = x + PW // 2
        centred(d, PY + PH + 18, title, 34, col, cx=cx)
        centred(d, PY + PH + 62, sub, 24, (160, 160, 180), cx=cx)
    centred(d, 820, "Both Oric panels run the same built-in demo, frame for frame - "
            "only the playfield rendering differs", 26, (210, 210, 210))
    centred(d, 862, "Mono mimics the Spectrum's black-on-white look; colour uses Oric "
            "serial attributes (deck gradients, per-droid colour)", 24, (170, 170, 190))
    centred(d, 940, "Audio: Spectrum on the left channel, Oric AY-3-8912 on the right",
            24, (150, 150, 170))
    centred(d, 980, "Spectrum: a real player's RZX recording replayed in Fuse     "
            "Oric: the port's demo mode, captured from emulated video memory",
            20, (120, 120, 140))
    im.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spectrum")
    ap.add_argument("spectrum_audio")
    ap.add_argument("oric_mono")
    ap.add_argument("oric_colour")
    ap.add_argument("out")
    ap.add_argument("--seconds", type=float, default=180)
    args = ap.parse_args()

    tmp = tempfile.mkdtemp()
    bg, title, cred = (os.path.join(tmp, n) for n in ("bg.png", "title.png", "credits.png"))
    make_background(bg)
    make_title(title)
    make_credits(cred)

    T, CARD = args.seconds, 5
    ox = [PX[1] + ORIC_OX, PX[2] + ORIC_OX]
    oy = PY + ORIC_OY
    fc = (
        f"[1:v]fps=50,trim=duration={T},setpts=PTS-STARTPTS,"
        f"crop=304:228:8:6,scale={PW}:{PH}:flags=neighbor[sv];"
        f"[3:v]trim=duration={T},setpts=PTS-STARTPTS,scale=480:448:flags=neighbor[mv];"
        f"[4:v]trim=duration={T},setpts=PTS-STARTPTS,scale=480:448:flags=neighbor[cv0];"
        f"[0:v]fps=50,trim=duration={T},format=yuv444p[bgv];"
        f"[bgv][sv]overlay={PX[0]}:{PY}:shortest=1[t1];"
        f"[t1][mv]overlay={ox[0]}:{oy}:shortest=1[t2];"
        f"[t2][cv0]overlay={ox[1]}:{oy}:shortest=1,format=yuv420p,setsar=1[main];"
        f"[2:a]atrim=duration={T},asetpts=PTS-STARTPTS,"
        f"pan=mono|c0=0.5*c0+0.5*c1,aresample=48000[sa];"
        f"[4:a]atrim=duration={T},asetpts=PTS-STARTPTS,volume=0.7,aresample=48000[oa];"
        f"[sa][oa]join=inputs=2:channel_layout=stereo[mainA];"
        f"[5:v]fps=50,trim=duration={CARD},format=yuv420p,setsar=1,"
        f"fade=in:st=0:d=1,fade=out:st={CARD - 1}:d=1[tv];"
        f"[6:v]fps=50,trim=duration={CARD + 2},format=yuv420p,setsar=1,"
        f"fade=in:st=0:d=1,fade=out:st={CARD + 1}:d=1[ev];"
        f"anullsrc=r=48000:cl=stereo,atrim=duration={CARD}[ta];"
        f"anullsrc=r=48000:cl=stereo,atrim=duration={CARD + 2}[ea];"
        f"[tv][ta][main][mainA][ev][ea]concat=n=3:v=1:a=1[v][a]"
    )
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-stats",
           "-loop", "1", "-framerate", "50", "-i", bg,
           "-i", args.spectrum, "-i", args.spectrum_audio,
           "-i", args.oric_mono, "-i", args.oric_colour,
           "-loop", "1", "-framerate", "50", "-i", title,
           "-loop", "1", "-framerate", "50", "-i", cred,
           "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-tune", "animation",
           "-pix_fmt", "yuv420p", "-r", "50",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", args.out]
    subprocess.check_call(cmd)
    Image.open(bg).save(os.path.splitext(args.out)[0] + "_layout.png")


if __name__ == "__main__":
    main()
