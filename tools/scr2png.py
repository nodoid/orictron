#!/usr/bin/env python3
"""Convert ZX Spectrum screen dumps (6912-byte .scr) to PNG, optionally
tiled into a contact sheet.  usage: scr2png.py out.png a.scr [b.scr ...]"""
import sys
from PIL import Image

N = [(0, 0, 0), (0, 0, 205), (205, 0, 0), (205, 0, 205), (0, 205, 0), (0, 205, 205), (205, 205, 0), (205, 205, 205)]
B = [(0, 0, 0), (0, 0, 255), (255, 0, 0), (255, 0, 255), (0, 255, 0), (0, 255, 255), (255, 255, 0), (255, 255, 255)]


def scr_image(data):
    im = Image.new('RGB', (256, 192))
    px = im.load()
    for y in range(192):
        base = ((y & 0xC0) << 5) | ((y & 7) << 8) | ((y & 0x38) << 2)
        for cx in range(32):
            b = data[base + cx]
            a = data[6144 + (y >> 3) * 32 + cx]
            pal = B if a & 64 else N
            ink, paper = pal[a & 7], pal[(a >> 3) & 7]
            for k in range(8):
                px[cx * 8 + k, y] = ink if b & (0x80 >> k) else paper
    return im


def main():
    out = sys.argv[1]
    ims = [scr_image(open(f, 'rb').read()) for f in sys.argv[2:]]
    if len(ims) == 1:
        ims[0].save(out)
        return
    import os
    cols = int(os.environ.get('COLS', 4))
    sc = int(os.environ.get('SCALE', 1))
    rows = (len(ims) + cols - 1) // cols
    W, H = 256 * sc + 4, 192 * sc + 4
    sheet = Image.new('RGB', (cols * W, rows * H), (40, 40, 40))
    for k, im in enumerate(ims):
        sheet.paste(im.resize((256 * sc, 192 * sc), Image.NEAREST), ((k % cols) * W, (k // cols) * H))
    sheet.save(out)


if __name__ == '__main__':
    main()
