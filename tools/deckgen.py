#!/usr/bin/env python3
"""Quazatron deck generator: lays out each deck as an isometric tile grid
with height levels, renders it Spectrum-style at 1 bit per pixel, then cuts
the picture into 1-byte x 6-row cells for the Oric's scrolling renderer.

Per deck the game gets (all packed into one LZ-compressed blob):
    header        16 bytes (see HDR below)
    planes        6 x 256 bytes: row r of every cell id (planar charset)
    leftfix       256 bytes: byte to show for a cell in the leftmost column
    tiles         W*H bytes: bits 0-1 level, bits 2-4 kind
    cellmap       MAPW*MAPH cell ids, row-major
"""
import random
import sys

import numpy as np

from oricenc import decode_rows, write_png

TWH = 12          # half diamond width (px)
THH = 6           # half diamond height (rows)
LH = 12           # height of one level (rows)
WALLH = 3         # wall height in levels
SLAB = 18         # deck slab thickness under level 0

# tile kinds
K_VOID, K_FLOOR, K_WALL, K_PAD, K_ENERG, K_LIFT, K_CONSOLE = range(7)
WALKABLE = {K_FLOOR, K_PAD, K_ENERG, K_LIFT}


# ---------------------------------------------------------------- layout --
def rect(g, lv, i0, j0, w, h, kind, level):
    for j in range(j0, j0 + h):
        for i in range(i0, i0 + w):
            if 0 <= i < g.shape[1] and 0 <= j < g.shape[0]:
                g[j, i] = kind
                lv[j, i] = level


def can_step(g, lv, a, b):
    ka, kb = g[a[1], a[0]], g[b[1], b[0]]
    if kb not in WALKABLE or ka not in WALKABLE:
        return False
    d = int(lv[b[1], b[0]]) - int(lv[a[1], a[0]])
    if d == 0:
        return True
    return abs(d) == 1 and (ka == K_PAD or kb == K_PAD)


def reach(g, lv, start):
    H, W = g.shape
    seen = {start}
    q = [start]
    while q:
        a = q.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            b = (a[0] + dx, a[1] + dy)
            if 0 <= b[0] < W and 0 <= b[1] < H and b not in seen and can_step(g, lv, a, b):
                seen.add(b)
                q.append(b)
    return seen


def make_layout(seed, W, H):
    rnd = random.Random(seed)
    g = np.zeros((H, W), np.uint8)
    lv = np.zeros((H, W), np.uint8)
    # base: big rectangle with bites taken out of the corners and edges
    rect(g, lv, 1, 1, W - 2, H - 2, K_FLOOR, 0)
    for _ in range(4):
        w, h = rnd.randint(2, 5), rnd.randint(2, 5)
        corner = rnd.randint(0, 3)
        i0 = 1 if corner & 1 else W - 1 - w
        j0 = 1 if corner & 2 else H - 1 - h
        rect(g, lv, i0, j0, w, h, K_VOID, 0)
    # raised walkways and blocks
    for _ in range(rnd.randint(5, 7)):
        w, h = rnd.randint(3, 8), rnd.randint(2, 7)
        if rnd.random() < 0.5:
            w, h = h, w
        i0, j0 = rnd.randint(2, W - 2 - w), rnd.randint(2, H - 2 - h)
        sub = g[j0:j0 + h, i0:i0 + w]
        if (sub == K_VOID).any():
            continue
        base = int(lv[j0:j0 + h, i0:i0 + w].max())
        if base >= 2:
            continue
        rect(g, lv, i0, j0, w, h, K_FLOOR, base + 1)
    # long narrow walkways running along the iso axes
    for _ in range(rnd.randint(2, 3)):
        horiz = rnd.random() < 0.5
        n = rnd.randint(6, W - 4)
        a0 = rnd.randint(2, W - 2 - n)
        b0 = rnd.randint(2, H - 4)
        cells = [((a0 + t, b0 + u) if horiz else (b0 + u, a0 + t)) for t in range(n) for u in range(2)]
        if any(g[j, i] == K_VOID for (i, j) in cells):
            continue
        top = min(2, max(int(lv[j, i]) for (i, j) in cells) + 1)
        for (i, j) in cells:
            g[j, i] = K_FLOOR
            lv[j, i] = top
    # a partition wall across the lower floor, with two doorways
    if rnd.random() < 0.8:
        horiz = rnd.random() < 0.5
        k = rnd.randint(5, W - 6)
        gaps = rnd.sample(range(2, W - 3), 2)
        for t in range(1, W - 1):
            if any(abs(t - gp) <= 1 for gp in gaps):
                continue
            i, j = (t, k) if horiz else (k, t)
            if g[j, i] == K_FLOOR and lv[j, i] == 0:
                g[j, i] = K_WALL
    # tall walls along the back (low i / low j) edges of the deck
    for j in range(H):
        for i in range(W):
            if g[j, i] != K_FLOOR:
                continue
            back_void = (i == 0 or g[j, i - 1] == K_VOID) or (j == 0 or g[j - 1, i] == K_VOID)
            if back_void and rnd.random() < 0.85:
                g[j, i] = K_WALL
    # some interior wall blocks at the back of raised platforms
    for _ in range(rnd.randint(2, 4)):
        i, j = rnd.randint(2, W - 4), rnd.randint(2, H - 4)
        if g[j, i] == K_FLOOR and g[j, i + 1] == K_FLOOR:
            l = lv[j, i]
            n = rnd.randint(2, 4)
            horiz = rnd.random() < 0.5
            for k in range(n):
                ii, jj = (i + k, j) if horiz else (i, j + k)
                if ii < W - 1 and jj < H - 1 and g[jj, ii] == K_FLOOR and lv[jj, ii] == l:
                    g[jj, ii] = K_WALL
    # pads (the <-> tiles) on level boundaries: put them on upper tiles
    edges = []
    for j in range(H):
        for i in range(W):
            if g[j, i] != K_FLOOR:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ii, jj = i + dx, j + dy
                if 0 <= ii < W and 0 <= jj < H and g[jj, ii] == K_FLOOR and lv[jj, ii] + 1 == lv[j, i]:
                    edges.append((i, j))
                    break
    rnd.shuffle(edges)
    start = None
    for j in range(H):
        for i in range(W):
            if g[j, i] == K_FLOOR and lv[j, i] == 0 and start is None and i > 3 and j > 3:
                start = (i, j)
    # connect: keep adding pads until everything walkable is reachable
    for _ in range(200):
        r = reach(g, lv, start)
        unreached = [(i, j) for j in range(H) for i in range(W)
                     if g[j, i] in WALKABLE and (i, j) not in r]
        if not unreached:
            break
        placed = False
        for e in edges:
            i, j = e
            if g[j, i] != K_FLOOR:
                continue
            nb_r = any((i + dx, j + dy) in r for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            if (i, j) in r or nb_r:
                if (i, j) in r and not any((i + dx, j + dy) not in r and 0 <= i + dx < W and 0 <= j + dy < H
                                           and g[j + dy, i + dx] in WALKABLE
                                           for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    continue
                g[j, i] = K_PAD
                placed = True
                break
        if not placed:
            # knock a doorway through a wall between reached and unreached
            un = set(unreached)
            door = None
            for j in range(1, H - 1):
                for i in range(1, W - 1):
                    if g[j, i] != K_WALL:
                        continue
                    for (a, b) in (((i - 1, j), (i + 1, j)), ((i, j - 1), (i, j + 1))):
                        for (p, q) in ((a, b), (b, a)):
                            if p in r and q in un and lv[p[1], p[0]] == lv[q[1], q[0]] == lv[j, i]:
                                door = (i, j)
                if door:
                    break
            if door:
                g[door[1], door[0]] = K_FLOOR
                continue
            # isolated region: drop it to void
            for (i, j) in unreached:
                g[j, i] = K_VOID
    # a few extra pads for looks
    for e in edges[:6]:
        if g[e[1], e[0]] == K_FLOOR:
            g[e[1], e[0]] = K_PAD
    r = reach(g, lv, start)
    floor0 = [p for p in r if g[p[1], p[0]] == K_FLOOR]
    rnd.shuffle(floor0)

    def free_block(i, j, n):
        return all(0 <= i + a < W and 0 <= j + b < H and g[j + b, i + a] == K_FLOOR and
                   lv[j + b, i + a] == lv[j, i] and (i + a, j + b) in r
                   for a in range(n) for b in range(n))
    # lift near the start, energiser blocks, consoles next to walls
    g[start[1], start[0]] = K_LIFT
    ne = 0
    for (i, j) in floor0:
        if ne < 2 and free_block(i, j, 2) and abs(i - start[0]) + abs(j - start[1]) > 6:
            for a in range(2):
                for b in range(2):
                    g[j + b, i + a] = K_ENERG
            ne += 1
    nc = 0
    for (i, j) in floor0:
        if nc >= 4 or g[j, i] != K_FLOOR:
            continue
        if (i > 0 and g[j, i - 1] == K_WALL) or (j > 0 and g[j - 1, i] == K_WALL):
            g[j, i] = K_CONSOLE
            if len(reach(g, lv, start)) < len(r) - 1:
                g[j, i] = K_FLOOR
            else:
                nc += 1
    return g, lv, start


# --------------------------------------------------------------- render ---
def diamond_rows():
    """half widths of the 12 diamond rows"""
    return [2 * k + 2 if k < 6 else 2 * (11 - k) + 2 for k in range(12)]


DW = diamond_rows()

# black pixels of the double arrow on a <-> pad, as (dx, row): a thick
# line along the up-right iso diagonal with an L-shaped head at each end
PAD_ARROW = set()
for _t in range(6):
    for _w in range(2):
        PAD_ARROW.add((-5 + 2 * _t + _w, 8 - _t))
for _x in range(-5, -1):
    PAD_ARROW.add((_x, 8))
PAD_ARROW.update({(-5, 7), (-4, 7)})
for _x in range(3, 7):
    PAD_ARROW.add((_x, 3))
PAD_ARROW.update({(5, 4), (6, 4)})


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.pix = np.zeros((h, w), np.uint8)     # ink
        self.solid = np.zeros((h, w), np.uint8)   # painted (not void)

    def put(self, x, y, ink, solid=1):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.pix[y, x] = ink
            self.solid[y, x] = solid


def tile_pos(i, j, level, X0, Y0):
    return X0 + (i - j) * TWH, Y0 + (i + j) * THH - level * LH


def face_bottom_row(dx):
    """for a column offset dx (-12..11) from the centre, the first row below
    the diamond (relative to the diamond top)"""
    for k in range(11, -1, -1):
        if -DW[k] <= dx < DW[k]:
            return k + 1
    return 0


FB = {dx: face_bottom_row(dx) for dx in range(-12, 12)}


class Style:
    def __init__(self, kind):
        self.kind = kind     # 'panel' (white deck look) or 'brick' (cyan deck look)

    # top surface of an ordinary floor tile; x, y are map coordinates
    def floor(self, x, y, u, v, i, j):
        if self.kind == 'brick':
            # alternate solid and dithered diamonds
            if (i + j) & 1:
                return 1 if (x + y) & 1 else 0
            return 0 if (x % 4 == 0 and y % 2 == 0) else 1
        return (x + y) & 1

    def wall(self, u, v, h, left):
        """tall wall face pixel. u = 0..11 across the face, v = rows down"""
        if v < 2:
            return 1
        if v >= h - 1:
            return 0
        if self.kind == 'brick':
            course = (v - 2) // 4
            if (v - 2) % 4 == 3:
                return 0
            off = 0 if course & 1 else 3
            return 0 if (u + off) % 6 == 0 else (1 if left or (u + v) & 1 else 1)
        # vertical panels: white strip, black gap, dotted rivet strip
        m = u % 6
        if m == 0:
            return 1
        if m == 3:
            return 1 if v % 3 == 0 else 0
        if m == 1:
            return 0
        return 0 if left else (1 if m == 5 and v % 2 == 0 else 0)

    def step(self, u, v, h, left):
        """face of a raised platform (one level)"""
        if v < 2:
            return 1
        if v == 2:
            return 0
        if v >= h - 1:
            return 0
        if self.kind == 'brick':
            if (v - 3) % 4 == 3:
                return 0
            return 0 if (u + (2 if ((v - 3) // 4) & 1 else 0)) % 4 == 0 else 1
        # black with white rivets
        return 1 if (u % 6 == 3 and v % 4 == 1) else 0


def render_deck(g, lv, style, X0, Y0, MW, MH):
    H, W = g.shape
    cv = Canvas(MW, MH)

    def face(cx, ty, top_lv, bot_lv, left, kind):
        # the face hangs from the diamond's lower edge at level top_lv down to
        # bot_lv.  kind: 'slab', 'step', 'wall'
        hrows = (top_lv - bot_lv) * LH if kind != 'slab' else SLAB
        rng = range(-12, 0) if left else range(0, 12)
        for dx in rng:
            u = dx + 12 if left else dx
            y0 = ty + FB[dx]
            for v in range(hrows):
                y = y0 + v
                x = cx + dx
                if kind == 'slab':
                    # the ledge, as on the Spectrum: white edge, a dark
                    # band with bolts, then bars ending in drips that hang
                    # over the void.  The band is 8 rows deep so the cell
                    # where the paper changes back to black hides in it.
                    m = u % 6
                    if v < 2:
                        cv.put(x, y, 1)
                    elif v < 10:
                        cv.put(x, y, 1 if (m in (2, 3) and v in (5, 6)) else 0)
                    elif v < 16:
                        if m in (2, 3):
                            cv.put(x, y, 1, solid=0)
                    elif v == 16:
                        if m in (1, 2, 3, 4):
                            cv.put(x, y, 1, solid=0)
                    elif m in (2, 3):
                        cv.put(x, y, 1, solid=0)
                    continue
                if kind == 'wall':
                    p = style.wall(u, v, hrows, left)
                else:
                    # split the column into one-level steps
                    vv = v % LH
                    p = style.step(u, vv, LH, left)
                # shade: right faces get a little darker in panel style
                cv.put(x, y, p)

    def top(cx, ty, i, j, kind):
        for k in range(12):
            for dx in range(-DW[k], DW[k]):
                x, y = cx + dx, ty + k
                # u, v: diamond-local coordinates
                u, v = dx, k
                if kind == K_FLOOR or kind == K_CONSOLE:
                    p = style.floor(x, y, u, v, i, j)
                elif kind == K_WALL:
                    p = (x + y) & 1
                elif kind == K_PAD:
                    # white diamond with a black rim
                    p = 1 if (1 <= k <= 10 and -DW[k] + 2 <= dx < DW[k] - 2) else 0
                    if (dx, k) in PAD_ARROW:
                        p = 0
                elif kind == K_ENERG:
                    # black diamond with a light ring
                    e = abs(dx + 0.5) / 2.0 + abs(k - 5.5)
                    p = 1 if 2.5 <= e <= 3.6 else 0
                    if k == 0 or k == 11:
                        p = 0
                elif kind == K_LIFT:
                    e = abs(dx + 0.5) / 2.0 + abs(k - 5.5)
                    if e > 4.8:
                        p = 0
                    elif e > 3.6:
                        p = 1
                    elif e > 2.6:
                        p = 0
                    else:
                        p = 1 if dx % 3 == 0 else 0
                else:
                    p = 0
                cv.put(x, y, p)

    def console(cx, ty):
        # monitor on a stand, standing on the tile centre
        art = [
            "..##############..",
            ".#..............#.",
            "#..############..#",
            "#.#............#.#",
            "#.#............#.#",
            "#.#............#.#",
            "#.#............#.#",
            "#..############..#",
            ".#..............#.",
            "..######..######..",
            ".......#..#.......",
            ".......#..#.......",
            ".....########.....",
        ]
        ox = cx - 9
        oy = ty + 6 - len(art) + 2
        for r, line in enumerate(art):
            for c, ch in enumerate(line):
                if ch == '#':
                    cv.put(ox + c, oy + r, 1)
                elif ch == '.' and (line.strip('.') and line.find('#') <= c <= line.rfind('#')):
                    cv.put(ox + c, oy + r, 0)

    for s in range(W + H - 1):
        for i in range(W):
            j = s - i
            if not (0 <= j < H):
                continue
            kind = g[j, i]
            if kind == K_VOID:
                continue
            L = int(lv[j, i])
            topL = L + (WALLH if kind == K_WALL else 0)
            cx, ty = tile_pos(i, j, topL, X0, Y0)
            # slab under level 0
            _, ty0 = tile_pos(i, j, 0, X0, Y0)
            face(cx, ty0, 0, -1, True, 'slab')
            face(cx, ty0, 0, -1, False, 'slab')
            if L > 0:
                _, tyL = tile_pos(i, j, L, X0, Y0)
                face(cx, tyL, L, 0, True, 'step')
                face(cx, tyL, L, 0, False, 'step')
            if kind == K_WALL:
                face(cx, ty, topL, L, True, 'wall')
                face(cx, ty, topL, L, False, 'wall')
            top(cx, ty, i, j, kind)
            if kind == K_CONSOLE:
                console(cx, ty)
    return cv


# ---------------------------------------------------------------- cells ---
# costs for the paper optimiser, per pixel
C_WRONG = 1.0       # ink pixel lost, or void shown black
C_BLUEBG = 0.35     # deck background shown blue - the Spectrum does this
                    # too, in attribute cells that straddle the deck edge
C_ATTR = 2.0        # small charge per paper change


def cellify(cv, void_col):
    """Cut the canvas into 1 byte x 6 row cells; returns (cellmap, cells,
    leftfix).  Cells are 6 raw Oric bytes plus the paper they leave set.

    Changing paper (blue void <-> black deck) costs a whole cell shown as
    solid paper, so for each row of cells a small dynamic programme picks
    where the changes go: blue may run on behind the ledge fringe and the
    deck edge, the way the Spectrum's blue attribute cells overlap it."""
    MW, MH = cv.w, cv.h
    cols, rows = MW // 6, MH // 6
    cellmap = np.zeros((rows, cols), np.int32)
    cells = {}
    order = []

    def cid(t):
        if t not in cells:
            cells[t] = len(order)
            order.append(t)
        return cells[t]
    BLUE, BLACK = 1, 0
    for r in range(rows):
        pix = cv.pix[r * 6:r * 6 + 6]
        sol = cv.solid[r * 6:r * 6 + 6]
        # per cell: ink pixels, deck-background pixels, void pixels
        ink_n = [int(pix[:, c * 6:c * 6 + 6].sum()) for c in range(cols)]
        bg_n = [int(((pix[:, c * 6:c * 6 + 6] == 0) & (sol[:, c * 6:c * 6 + 6] == 1)).sum()) for c in range(cols)]
        void_n = [int(((pix[:, c * 6:c * 6 + 6] == 0) & (sol[:, c * 6:c * 6 + 6] == 0)).sum()) for c in range(cols)]
        if not void_col:
            choice = [(BLACK, False)] * cols
        else:
            INF = 1e18
            cost = {BLUE: 0.0, BLACK: 0.0}
            back = []
            for c in range(cols):
                nc = {BLUE: INF, BLACK: INF}
                nb = {}
                for sp in (BLUE, BLACK):
                    base = cost[sp]
                    if base >= INF:
                        continue
                    # pixel cell, paper unchanged
                    e = base + (bg_n[c] * C_BLUEBG if sp == BLUE else void_n[c] * C_WRONG)
                    if e < nc[sp]:
                        nc[sp], nb[sp] = e, (sp, False)
                    # attribute cell switching to the other paper
                    np_ = 1 - sp
                    e = base + C_ATTR + ink_n[c] * C_WRONG + \
                        (bg_n[c] * C_BLUEBG if np_ == BLUE else void_n[c] * C_WRONG)
                    if e < nc[np_]:
                        nc[np_], nb[np_] = e, (sp, True)
                back.append(nb)
                cost = nc
            st = min(cost, key=cost.get)
            choice = [None] * cols
            for c in range(cols - 1, -1, -1):
                prev, attr = back[c][st]
                choice[c] = (st, attr)
                st = prev
        for c in range(cols):
            paper, attr = choice[c]
            if attr:
                t = tuple([16 + (void_col if paper == BLUE else 0)] * 6)
            else:
                blk = pix[:, c * 6:c * 6 + 6]
                t = tuple(0x40 | int(sum(int(blk[y, x]) << (5 - x) for x in range(6))) for y in range(6))
            cellmap[r, c] = cid(t + (paper,))
    # leftfix: the paper attribute the leftmost visible column must show
    leftfix = [16 + (void_col if t[6] == BLUE else 0) for t in order]
    return cellmap, order, leftfix


def preview(cellmap, cells, ink, path, leftfix=None):
    rows, cols = cellmap.shape
    out = []
    for r in range(rows):
        for y in range(6):
            lf = [leftfix[cellmap[r, 0]]] if leftfix else []
            line = [ink] + lf + [cells[cellmap[r, c]][y] for c in range(cols)]
            out.append(line)
    write_png(path, decode_rows(out), 2)


DECKS = [
    # seed, W, H, style, ink, void colour
    (11, 16, 16, 'panel', 7, 4),
    (23, 16, 16, 'brick', 6, 4),
    (37, 16, 16, 'brick', 4, 0),
    (41, 16, 16, 'panel', 2, 4),
    (53, 16, 16, 'brick', 5, 4),
    (71, 16, 16, 'panel', 3, 4),
]


def build(idx):
    seed, W, H, sty, ink, void = DECKS[idx]
    g, lv, start = make_layout(seed, W, H)
    X0 = H * TWH + 6
    Y0 = WALLH * LH + 3 * LH + 6
    MW = (W + H) * TWH + 12
    MW = (MW + 5) // 6 * 6
    MH = Y0 + (W + H) * THH + SLAB + 12
    MH = (MH + 5) // 6 * 6
    cv = render_deck(g, lv, Style(sty), X0, Y0, MW, MH)
    cellmap, cells, leftfix = cellify(cv, void)
    return dict(g=g, lv=lv, start=start, X0=X0, Y0=Y0, cellmap=cellmap, cells=cells,
                leftfix=leftfix, ink=ink, void=void, W=W, H=H)


if __name__ == '__main__':
    for d in range(len(DECKS)):
        b = build(d)
        print("deck", d, "cells", len(b['cells']), "map", b['cellmap'].shape,
              "bytes", b['cellmap'].size)
        if len(sys.argv) > 1:
            preview(b['cellmap'], b['cells'], b['ink'], "%s/deck%d.png" % (sys.argv[1], d), b['leftfix'])
