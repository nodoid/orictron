#!/usr/bin/env python3
"""Generate the graphics data (ca65 source) for the Oric Quazatron port.

Sprite descriptor layout (what spr_draw in oric.s expects):
    .byte h, w, h*w
    .word phase0, phase1              (pixel shifts 0 and 3)
    .byte x offset of the sprite's centre
  each phase block = h*w data bytes followed by h*w mask bytes.
  data bytes carry $40; mask bytes have bit=1 where the background is kept.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import numpy as np

import deckgen
from fontdata import FONT5
from oricenc import decode_rows, emit_bytes, encode_line, lz_compress, write_png

OUT = []
PREVIEW = None
NPHASE = 2
SHIFTS = [0, 3]


def emit(s=""):
    OUT.append(s)


# ---------------------------------------------------------------- font ----
def font_rows():
    """Bold 6x8 font: the 5x7 glyphs thickened one pixel to the right."""
    rows = []
    for ch in range(64):
        cols = FONT5[ch * 5:ch * 5 + 5]
        for r in range(8):
            b = 0
            for c in range(5):
                if (cols[c] >> r) & 1:
                    b |= 1 << (5 - c)
            rows.append((b | (b >> 1)) & 0x3F)
    return rows


FONT = font_rows()


def glyph(ch):
    return FONT[(ord(ch) - 32) * 8:(ord(ch) - 32) * 8 + 8]


# ------------------------------------------------------------- droids -----
TINY = {
    '0': ["###", "#.#", "#.#", "#.#", "###"], '1': [".#.", "##.", ".#.", ".#.", "###"],
    '2': ["###", "..#", "###", "#..", "###"], '3': ["###", "..#", ".##", "..#", "###"],
    '4': ["#.#", "#.#", "###", "..#", "..#"], '5': ["###", "#..", "###", "..#", "###"],
    '6': ["###", "#..", "###", "#.#", "###"], '7': ["###", "..#", "..#", ".#.", ".#."],
    '8': ["###", "#.#", "###", "#.#", "###"], '9': ["###", "#.#", "###", "..#", "###"],
    'B': ["##.", "#.#", "##.", "#.#", "##."], 'M': ["#.#", "###", "###", "#.#", "#.#"],
    'S': [".##", "#..", ".#.", "..#", "##."], 'W': ["#.#", "#.#", "###", "###", "#.#"],
    'G': [".##", "#..", "#.#", "#.#", ".##"], 'R': ["##.", "#.#", "##.", "#.#", "#.#"],
    'X': ["#.#", "#.#", ".#.", "#.#", "#.#"],
}

# lids float above the body; '#' = ink, 'o' = black, '.' = clear
LIDS = {
    'flat': ["...########...", ".############.", "#oooooooooooo#", ".############.", "...########..."],
    'dome': ["....######....", "..##########..", ".#o#o#o#o#o#o.", "##############", "..##########.."],
    'antenna': [".......##.....", "......####....", "..##########..", ".#oooooooooo#.", "..##########.."],
    'crown': ["#..#..##..#..#", "##.##.##.##.##", "##############", "#oooooooooooo#", ".############."],
    'big': ["..##########..", "##############", "#o#o#o#o#o#o##", "##############", ".############."],
}

BODY = [
    "..##########..",
    ".############.",
    "##############",
    "##############",
    "##############",
    "##############",
    "##############",
    "##############",
    "##############",
    ".############.",
    "..##########..",
    "....######....",
]

# class: (code, name, lid)
CLASSES = [
    ("", "INFLUENCE DEVICE", 'dome'),
    ("M1", "MESSENGER UNIT", 'flat'),
    ("S2", "SENTRY DROID", 'antenna'),
    ("W3", "WORKER UNIT", 'flat'),
    ("G4", "GUARD ROBOT", 'crown'),
    ("B5", "BATTLE ROBOT", 'big'),
    ("R6", "REPAIR ROBOT", 'antenna'),
    ("B7", "BATTLE DROID", 'big'),
    ("X9", "COMMAND UNIT", 'crown'),
]


def droid_art(cls):
    code, _, lid = CLASSES[cls]
    body = [list(r) for r in BODY]
    if cls == 0:
        # the influence device: a round shell with a dark visor band
        art = [
            "....######....",
            "..##########..",
            ".############.",
            "##############",
            "#oooooooooooo#",
            "##############",
            ".############.",
            "..##########..",
            "....######....",
        ]
        return ["." * 14] * 4 + LIDS['dome'][:2] + ["." * 14] + art + ["." * 14] * 3
    for k, ch in enumerate(code):
        g = TINY[ch]
        for r in range(5):
            for c in range(3):
                if g[r][c] == '#':
                    body[3 + r][3 + k * 5 + c] = 'o'
    # a short horizontal rule under the code, like the Spectrum sprites
    for c in range(8, 12):
        body[8][c] = 'o'
    return LIDS[lid] + ["." * 14] + ["".join(r) for r in body]


BOOM0 = [
    "..............",
    "....#....#....",
    ".#...#..#...#.",
    "..#..####..#..",
    "....######....",
    "...########...",
    ".###oooooo###.",
    "...########...",
    "....######....",
    "..#..####..#..",
    ".#...#..#...#.",
    "....#....#....",
]
BOOM1 = [
    "#.....#......#",
    "..#.......#...",
    "....#..#...#..",
    ".#..........#.",
    "...#...#......",
    "#......#....#.",
    "..#..#.....#..",
    "......#.#.....",
    ".#..#......#.#",
    "....#....#....",
    "#......#...#..",
    "..#..#.......#",
]
BULLET = [
    ".##.",
    "####",
    ".##.",
]


def to_pixels(art):
    h = len(art)
    w = max(len(r) for r in art)
    ink = np.zeros((h, w), bool)
    opq = np.zeros((h, w), bool)
    for y, row in enumerate(art):
        for x, ch in enumerate(row):
            if ch == '#':
                ink[y, x] = opq[y, x] = True
            elif ch == 'o':
                opq[y, x] = True
    return ink, opq


def outline(opq):
    h, w = opq.shape
    out = opq.copy()
    for y in range(h):
        for x in range(w):
            if opq[y, x]:
                out[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = True
    return out


def pack(ink, opq, shift, wbytes):
    h, w = ink.shape
    data, mask = [], []
    for y in range(h):
        for b in range(wbytes):
            d, m = 0x40, 0xC0
            for p in range(6):
                x = b * 6 + p - shift
                bit = 1 << (5 - p)
                if 0 <= x < w:
                    if ink[y, x]:
                        d |= bit
                    if not opq[y, x]:
                        m |= bit
                else:
                    m |= bit
            data.append(d)
            mask.append(m)
    return data, mask


def emit_sprite(name, art, auto_outline=True):
    ink, opq = to_pixels(art)
    # pad a column each side so the outline fits
    ink = np.pad(ink, ((1, 1), (1, 1)))
    opq = np.pad(opq, ((1, 1), (1, 1)))
    if auto_outline:
        opq = outline(opq)
    h, w = ink.shape
    wbytes = (w + max(SHIFTS) + 5) // 6
    assert h * wbytes < 256, name
    emit("_%s:" % name)
    emit("        .byte %d, %d, %d" % (h, wbytes, h * wbytes))
    emit("        .word " + ",".join("%s_p%d" % (name, s) for s in range(NPHASE)))
    emit("        .byte %d" % (w // 2))           # x offset of the centre
    for s in range(NPHASE):
        d, m = pack(ink, opq, SHIFTS[s], wbytes)
        emit("%s_p%d:" % (name, s))
        emit_bytes(OUT, d)
        emit_bytes(OUT, m)
    return h, wbytes


# ---------------------------------------------------------- images -------
RED, YEL, BLU, MAG, GRN, CYA, WHT, BLK = 1, 3, 4, 5, 2, 6, 7, 0


def blank(h, col):
    return np.full((h, 240), col, np.uint8)


def chamfer_box(img, x0, y0, x1, y1, c, ch, fill=None, thick=1):
    """octagon outline (corners cut by ch) from x0,y0 to x1,y1 inclusive"""
    for y in range(y0, y1 + 1):
        dy = min(y - y0, y1 - y)
        inset = max(0, ch - dy) * 2 // 2
        xa, xb = x0 + inset, x1 - inset
        if fill is not None:
            img[y, xa:xb + 1] = fill
        if dy < thick:
            img[y, xa:xb + 1] = c
        else:
            img[y, xa:xa + thick * 2] = c
            img[y, xb - thick * 2 + 1:xb + 1] = c


def encode(img, fixed_rows=None):
    rows = []
    for y in range(img.shape[0]):
        fx = fixed_rows.get(y) if fixed_rows else None
        rows.append(encode_line(list(img[y]), fixed=fx))
    return rows


# Panel layout, byte columns - keep in step with main.c.  Every colour
# change is a serial attribute; the fields use inverse video so their text
# can stay in the line's white ink (inverse white = black on the field).
#   capsule = [paper black][edge][...interior...][paper black][edge]
CAPSULES = [(1, 14), (16, 23), (25, 39)]
FIELDS = [            # (attribute column, chars, colour shown)
    (3, 8, YEL),      # status word
    (18, 1, MAG),     # deck
    (20, 1, GRN),     # droids left
    (27, 2, WHT),     # unit code
    (31, 6, CYA),     # score
]
FIELD_END = {3: 12, 18: None, 20: None, 27: 30, 31: None}
P_TOP, P_BOT = 6, 41          # capsule rows (panel-relative)
P_FY = 15                     # field rows: 10, text at +1
P_BARY = 29                   # energy bar rows: 3
EDGE = 0x4C                   # black, white line, black


def panel_image():
    """The status panel, rows 152-199: three capsules on red."""
    H = 48
    rows = [[0x11] + [0x40] * 39 for _ in range(H)]
    # outer rim: a white line with rounded ends, top and bottom
    for y in (1, 45):
        rows[y][1] = 0x47
        for c in range(2, 38):
            rows[y][c] = 0x7F
        rows[y][38] = 0x78
    for y in (2, 3, 4, 42, 43, 44):
        rows[y][1] = 0x44
        rows[y][38] = 0x48
    for (a, b) in CAPSULES:
        for y in range(P_TOP, P_BOT + 1):
            r = rows[y]
            off = min(y - P_TOP, P_BOT - y)
            if off < 3:
                inset = 1 if off < 2 else 0
                r[a + inset] = 0x10
                for c in range(a + inset + 1, b - inset + 1):
                    r[c] = 0x7F if off == 1 else 0x40
                if off == 2:
                    r[a + 1] = EDGE | 0x03
                    r[b] = EDGE | 0x30
                if b + 1 < 40:
                    r[b - inset + 1] = 0x11
                continue
            r[a] = 0x10
            r[a + 1] = EDGE
            r[a + 2] = 0x11
            r[b - 1] = 0x10
            r[b] = EDGE
            if b + 1 < 40:
                r[b + 1] = 0x11
    for y in range(P_FY, P_FY + 10):
        r = rows[y]
        # ink black for the field text: it replaces each capsule's left edge
        for (a, b) in CAPSULES:
            r[a + 1] = 0x00
        for (c0, n, col) in FIELDS:
            r[c0] = 16 + col
            for k in range(n):
                r[c0 + 1 + k] = 0x40
        r[12] = 0x11
        r[30] = 0x11
    for y in range(P_BARY, P_BARY + 3):
        rows[y][3] = 0x13
    return rows


def frame_image():
    """The blue framed text screen (rows 8-151)."""
    H = 144
    img = blank(H, RED)
    img[:, 6:234] = BLU
    # inner black panel with a white line round it
    img[16:128, 30:210] = BLK
    for (x0, y0, x1, y1) in ((26, 13, 213, 130),):
        img[y0, x0:x1 + 1] = WHT
        img[y1, x0:x1 + 1] = WHT
        img[y0:y1 + 1, x0:x0 + 2] = WHT
        img[y0:y1 + 1, x1 - 1:x1 + 1] = WHT
    img[16:128, 30:210] = BLK
    # ornaments along the top and bottom bands: chains of small boxes
    for x in range(40, 200, 24):
        for (yy) in (3, 135):
            img[yy:yy + 6, x:x + 10] = WHT
            img[yy + 2:yy + 4, x + 2:x + 8] = BLU
            img[yy + 2:yy + 4, x + 10:x + 22] = WHT
    for y in range(28, 120, 18):
        for xx in (10, 220):
            img[y:y + 8, xx:xx + 8] = WHT
            img[y + 2:y + 6, xx + 2:xx + 6] = BLU
    fixed = {}
    for y in range(H):
        f = {0: 0x11}
        if 16 <= y < 128:
            f[4] = 0x07           # interior text colour (patched at run time)
            f[5] = 0x10
            f[35] = 0x14
        fixed[y] = f
    return encode(img, fixed)


LOGO_W = 26


def logo_bytes():
    """ORICTRON in big outlined letters: LOGO_W columns x 18 rows, yellow ink"""
    text = "ORICTRON"
    W = LOGO_W * 6
    big = np.zeros((18, W), bool)
    x = (W - 16 * len(text)) // 2 + 1
    for ch in text:
        g = FONT5[(ord(ch) - 32) * 5:(ord(ch) - 32) * 5 + 5]
        for c in range(5):
            for r in range(7):
                if (g[c] >> r) & 1:
                    for dx in range(3):
                        for dy in range(2):
                            big[2 + r * 2 + dy, x + c * 3 + dx] = True
        x += 16
    # outline: ink where a neighbour is set but the pixel itself is not,
    # plus a dotted fill inside the strokes
    out = np.zeros_like(big)
    for y in range(18):
        for x in range(W):
            if big[y, x]:
                out[y, x] = (y % 2 == 0 and x % 2 == 0)
            else:
                nb = big[max(0, y - 1):y + 2, max(0, x - 1):x + 2].any()
                out[y, x] = nb
    rows = []
    for y in range(18):
        for c in range(LOGO_W):
            b = 0x40
            for p in range(6):
                if out[y, c * 6 + p]:
                    b |= 0x20 >> p
            rows.append(b)
    return rows


# ----------------------------------------------------------------- main ---
STYLES = ['panel', 'brick']


def deck_blobs():
    """One shared planar charset per deck style, plus per deck: header,
    leftfix table, tiles and cell map.  Returns (charset blobs, deck blobs)."""
    builds = [deckgen.build(d) for d in range(len(deckgen.DECKS))]
    sets = {st: set() for st in STYLES}
    for d, b in enumerate(builds):
        sets[deckgen.DECKS[d][3]].update(b['cells'])
    orders = {st: sorted(sets[st]) for st in STYLES}
    csets = []
    for st in STYLES:
        assert len(orders[st]) <= 256, (st, len(orders[st]))
        planes = bytearray(1536)
        for k, c in enumerate(orders[st]):
            for r in range(6):
                planes[r * 256 + k] = c[r]
        csets.append(lz_compress(bytes(planes)))
    decks = []
    for d, b in enumerate(builds):
        st = deckgen.DECKS[d][3]
        idx = {c: k for k, c in enumerate(orders[st])}
        remap = [idx[c] for c in b['cells']]
        cm = np.vectorize(lambda k: remap[k])(b['cellmap']).astype(np.uint8)
        lf = bytearray(256)
        for k, c in enumerate(b['cells']):
            lf[remap[k]] = b['leftfix'][k]
        W, H = b['W'], b['H']
        rows, cols = cm.shape
        hdr = bytearray(16)
        hdr[0], hdr[1], hdr[2], hdr[3] = W, H, cols, rows
        hdr[4], hdr[5] = b['X0'] & 255, b['X0'] >> 8
        hdr[6], hdr[7] = b['Y0'] & 255, b['Y0'] >> 8
        hdr[8], hdr[9] = b['ink'], b['void']
        hdr[10], hdr[11] = b['start']
        hdr[12] = STYLES.index(st)
        tiles = ((b['g'].astype(int) << 2) | b['lv']).astype(np.uint8).flatten()
        blob = bytes(lf) + bytes(hdr) + bytes(tiles) + bytes(cm.flatten())
        assert 0x9000 + len(blob) <= 0x9F00, len(blob)
        decks.append(lz_compress(blob))
    return csets, decks


def main():
    global PREVIEW
    out = sys.argv[1]
    if len(sys.argv) > 2:
        PREVIEW = sys.argv[2]
    emit("; generated by tools/mkgfx.py - do not edit")
    emit("        .export _font, _rowlo, _rowhi")
    emit("        .export _droid_spr, _spr_boom0, _spr_boom1, _spr_bullet")
    emit("        .export _deck_data, _cset_data, _panel_lz, _frame_lz, _logo")
    emit("        .rodata")
    emit("_font:")
    emit_bytes(OUT, FONT)
    emit("_rowlo:")
    emit_bytes(OUT, [(0xA000 + 40 * y) & 0xFF for y in range(200)])
    emit("_rowhi:")
    emit_bytes(OUT, [(0xA000 + 40 * y) >> 8 for y in range(200)])

    names = []
    for i in range(len(CLASSES)):
        nm = "spr_droid%d" % i
        emit_sprite(nm, droid_art(i))
        names.append(nm)
    emit("_droid_spr:")
    emit("        .word " + ",".join("_" + n for n in names))
    emit_sprite("spr_boom0", BOOM0)
    emit_sprite("spr_boom1", BOOM1, auto_outline=False)
    emit_sprite("spr_bullet", BULLET)

    csets, decks = deck_blobs()
    total = 0
    for k, comp in enumerate(csets):
        emit("cset%d:" % k)
        emit_bytes(OUT, list(comp))
        total += len(comp)
    emit("_cset_data:")
    emit("        .word " + ",".join("cset%d" % k for k in range(len(csets))))
    for d, comp in enumerate(decks):
        emit("deck%d:" % d)
        emit_bytes(OUT, list(comp))
        total += len(comp)
    emit("_deck_data:")
    emit("        .word " + ",".join("deck%d" % d for d in range(len(decks))))
    print("decks: %d bytes compressed" % total, file=sys.stderr)

    prow = panel_image()
    comp = lz_compress(bytes(sum(prow, [])))
    emit("_panel_lz:")
    emit_bytes(OUT, list(comp))
    print("panel: %d bytes" % len(comp), file=sys.stderr)
    frow = frame_image()
    comp = lz_compress(bytes(sum(frow, [])))
    emit("_frame_lz:")
    emit_bytes(OUT, list(comp))
    print("frame: %d bytes" % len(comp), file=sys.stderr)
    emit("_logo:")
    emit_bytes(OUT, logo_bytes())

    if PREVIEW:
        os.makedirs(PREVIEW, exist_ok=True)
        top = [[0x11] + [0x40] * 39 for _ in range(8)]
        write_png(os.path.join(PREVIEW, "panel.png"), decode_rows(top + frow + prow), 3)

    with open(out, "w") as f:
        f.write("\n".join(OUT) + "\n")


if __name__ == "__main__":
    main()
