/*
 * QUAZATRON for the Oric Atmos - a reimplementation of Graftgold's 1986
 * ZX Spectrum game, laid out to look and play like the original: a
 * smooth-scrolling isometric deck with raised walkways, the red three-capsule
 * status panel, framed text screens and the vertical-wire transfer battle.
 *
 * You are an influence device aboard a ship overrun by rogue droids.  Shoot
 * or ram them, or grapple one (T) and win the transfer battle to take over
 * its body.  Clear every deck; travel between decks by lift (L).
 */
#include "hw.h"

/* ------------------------------------------------------------ tuning --- */
#define NDECKS   6
#define NTYPES   9
#define MAXE     12     /* droids per deck */
#define MAXB     6      /* bullets */
#define MAXX     4      /* explosions */
#define RMAX     (1 + MAXE + MAXB + MAXX)

/* tile kinds - see tools/deckgen.py */
#define K_VOID    0
#define K_FLOOR   1
#define K_WALL    2
#define K_PAD     3
#define K_ENERG   4
#define K_LIFT    5
#define K_CONSOLE 6
static const unsigned char walkable[8] = { 0, 1, 0, 1, 1, 1, 0, 0 };

/* screen layout */
#define PF_TOP   8
#define PF_BOT   152
#define PANEL_Y  152
#define FIELD_Y  (PANEL_Y + 16)     /* text row inside the panel fields */
#define BAR_Y    (PANEL_Y + 29)
#define C_STAT   4                  /* status text: 8 chars */
#define C_GBOX   18                 /* attribute of the left symbol box */
#define C_UNIT   28
#define C_SCORE  32
#define C_BAR    3                  /* energy bar: attribute + 9 columns */

/* droid classes */
static const char *const type_code[NTYPES] = {
    "  ", "M1", "S2", "W3", "G4", "B5", "R6", "B7", "X9"
};
static const char *const type_name[NTYPES] = {
    "INFLUENCE DEVICE", "MESSENGER UNIT", "SENTRY DROID", "WORKER UNIT",
    "GUARD ROBOT", "BATTLE ROBOT", "REPAIR ROBOT", "BATTLE DROID", "COMMAND UNIT"
};
static const char *const type_sec[NTYPES] = {
    "NONE", "ALPHA", "ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON", "ZETA", "OMEGA"
};
static const unsigned char type_speed[NTYPES]  = { 2, 1, 1, 1, 2, 2, 1, 2, 2 };
static const unsigned char type_hp[NTYPES]     = { 30, 12, 18, 20, 26, 34, 30, 44, 64 };
static const unsigned char type_dmg[NTYPES]    = { 3, 0, 3, 0, 4, 5, 4, 6, 8 };
static const unsigned char type_rate[NTYPES]   = { 5, 0, 26, 0, 22, 18, 24, 14, 10 };
static const unsigned char type_mass[NTYPES]   = { 2, 2, 3, 3, 4, 5, 4, 6, 8 };
static const unsigned char type_pulses[NTYPES] = { 4, 3, 4, 4, 5, 5, 5, 6, 7 };
static const unsigned char type_score[NTYPES]  = { 0, 5, 10, 10, 20, 30, 30, 50, 100 };

static const unsigned char deck_n[NDECKS]    = { 6, 7, 8, 9, 10, 12 };
static const unsigned char deck_tmin[NDECKS] = { 1, 1, 2, 3, 4, 5 };
static const unsigned char deck_tmax[NDECKS] = { 3, 4, 5, 6, 7, 7 };

/* --------------------------------------------------------------- state - */
#pragma bss-name (push, "PAGE2")
unsigned char d12[256];
#pragma bss-name (pop)
#pragma bss-name (push, "HIBSS")
static unsigned char e_type[NDECKS][MAXE], e_hp[NDECKS][MAXE];
static unsigned char a_x[MAXE], a_y[MAXE], a_tm[MAXE], a_cool[MAXE];
static signed char a_dx[MAXE], a_dy[MAXE];
static unsigned char b_on[MAXB], b_x[MAXB], b_y[MAXB], b_z[MAXB], b_life[MAXB], b_dmg[MAXB], b_own[MAXB];
static signed char b_dx[MAXB], b_dy[MAXB];
static unsigned char x_on[MAXX], x_x[MAXX], x_y[MAXX], x_z[MAXX];
#pragma bss-name (pop)

static unsigned char deck_alive[NDECKS];
static unsigned char *eh, *et;     /* e_hp / e_type of the current deck */
static unsigned char deck, dw, dh, maph, deck_ink, deck_void, nd;
static int X0, Y0, cam_x, cam_y, cam_xmax, cam_ymax;

/* player */
static unsigned char p_x, p_y, p_type, p_hp, p_cool, p_ram, p_burn, p_flash, p_fkind, p_hold, p_grab;
static signed char p_fx, p_fy;
static unsigned int score;

static unsigned char frame, msg_time, kprev, game_over, won, need_full;

/* abstract input - filled from the keyboard or by the demo autopilot */
static signed char in_dx, in_dy;
static unsigned char in_fire, in_grab, in_lift, in_esc, in_up, in_down, demo;
static unsigned char any_key(void);
static void read_input(void);

/* ---------------------------------------------------------------- rng -- */
static unsigned int rs = 0xACE1;
static unsigned char rnd(void)
{
    rs ^= rs << 7;
    rs ^= rs >> 9;
    rs ^= rs << 8;
    return (unsigned char)rs;
}

/* --------------------------------------------------------------- draw -- */
static void rect(unsigned char col, unsigned char y, unsigned char w, unsigned char h, unsigned char v)
{
    fr_col = col; fr_y = y; fr_w = w; fr_h = h; fr_val = v;
    fill_rect();
}

static void htext(unsigned char col, unsigned char y, const char *s)
{
    hc_col = col;
    hc_y = y;
    while (*s) {
        hc_ch = *s++;
        hchar();
        ++hc_col;
    }
}

static unsigned char slen(const char *s)
{
    unsigned char n = 0;
    while (s[n]) ++n;
    return n;
}

static char nbuf[8];
static char *num(unsigned int v, unsigned char digits)
{
    nbuf[digits] = 0;
    while (digits--) {
        nbuf[digits] = '0' + (unsigned char)(v % 10);
        v /= 10;
    }
    return nbuf;
}

/* --------------------------------------------------------------- sound - */
static unsigned char sa_vol, sa_per, sb_vol, sc_vol, sc_per;

static void snd_init(void)
{
    ay_write(7, 0x6A);  /* tone A, noise B, tone C; port A output */
    ay_write(6, 20);
    ay_write(1, 0);
    ay_write(5, 0);
}

static void snd_update(void)
{
    if (sa_vol) {
        --sa_vol;
        sa_per += 12;
        ay_write(0, sa_per);
        ay_write(8, sa_vol);
    }
    if (sb_vol) {
        --sb_vol;
        ay_write(9, sb_vol);
    }
    if (sc_vol) {
        --sc_vol;
        ay_write(4, sc_per);
        ay_write(10, sc_vol);
    }
}

static void sfx_shot(void) { sa_per = 40; sa_vol = 12; }
static void sfx_boom(void) { ay_write(6, 28); sb_vol = 15; }
static void sfx_ram(void)  { ay_write(6, 8); sb_vol = 9; }
static void sfx_blip(unsigned char p) { sc_per = p; sc_vol = 10; }

static void snd_off(void)
{
    sa_vol = sb_vol = sc_vol = 0;
    ay_write(8, 0);
    ay_write(9, 0);
    ay_write(10, 0);
}

/* frame pacing: at most 25 fps */
static void wait_frame(void)
{
    frame_sync();
    kbd_scan();
    snd_update();
    ++frame;
}

static void pause(unsigned char n)
{
    while (n--) wait_frame();
}

/* -------------------------------------------------------------- panel -- */
static void field(unsigned char col, unsigned char n, const char *s)
{
    hc_y = FIELD_Y;
    hc_col = col;
    while (n--) {
        hc_ch = *s ? *s++ : ' ';
        hchar();
        ++hc_col;
    }
}

static void draw_panel(void)
{
    lz_src = panel_lz;
    lz_dst = SCREEN + PANEL_Y * 40;
    unpack();
}

/* the left symbol box: white while grappling, as on the Spectrum */
static void gbox(unsigned char c)
{
    rect(C_GBOX, PANEL_Y + 15, 1, 10, c);
}

static void stat(const char *s, unsigned char t)
{
    field(C_STAT, 8, s);
    msg_time = t;
}

static void panel_update(void)
{
    unsigned char n;
    field(C_UNIT, 2, type_code[p_type]);
    field(C_SCORE, 5, num(score, 5));
    field(C_SCORE + 5, 1, "0");
    /* energy bar: 10 yellow cells */
    n = (unsigned char)((unsigned int)p_hp * 10 / type_hp[p_type]);
    if (p_hp && !n) n = 1;
    rect(C_BAR, BAR_Y, 10, 3, 0x40);
    if (n) {
        rect(C_BAR, BAR_Y, 1, 3, 0x13);
        if (n < 10) rect(C_BAR + n, BAR_Y, 1, 3, 0x11);
    }
}

/* ------------------------------------------------------- text screens -- */
/* the blue framed screen: interior text columns 6-34, rows 24-135 */
static void frame_open(void)
{
    rect(0, 0, 1, PF_TOP, 0x11);
    rect(1, 0, 39, PF_TOP, 0x40);
    lz_src = frame_lz;
    lz_dst = SCREEN + PF_TOP * 40;
    unpack();
}

static void ftext(unsigned char y, unsigned char ink, const char *s)
{
    rect(4, y, 1, 8, ink);
    htext(6 + (29 - slen(s)) / 2, y, s);
}

static void flogo(unsigned char y)
{
    unsigned char r, c;
    const unsigned char *p = logo;
    unsigned char *scr;
    rect(4, y, 1, 18, 3);
    for (r = 0; r < 18; ++r) {
        scr = SCREEN + (unsigned int)(y + r) * 40 + 7;
        for (c = 0; c < 26; ++c) scr[c] = *p++;
    }
}

static void unit_line(unsigned char y, unsigned char t)
{
    static char buf[30];
    const char *s;
    char *b = buf;
    s = "UNIT.. "; while (*s) *b++ = *s++;
    if (t) { s = type_code[t]; *b++ = s[0]; *b++ = s[1]; *b++ = ' '; }
    s = type_name[t]; while (*s) *b++ = *s++;
    *b = 0;
    ftext(y, 6, buf);
}

/* --------------------------------------------------------------- decks - */
static unsigned char ap_ok;
static unsigned char cur_t;
static unsigned char corner_ok(unsigned char t)
{
    unsigned char l = t & 3, cl = cur_t & 3;
    if (!walkable[t >> 2]) return 0;
    if (l == cl) return 1;
    if ((l == cl + 1 || l + 1 == cl) && ((t >> 2) == K_PAD || (cur_t >> 2) == K_PAD)) return 1;
    return 0;
}

static unsigned char can_go(unsigned char x, unsigned char y, unsigned char nx, unsigned char ny)
{
    cur_t = tile_at(x, y);
    return corner_ok(tile_at(nx - 4, ny - 4)) && corner_ok(tile_at(nx + 3, ny - 4)) &&
           corner_ok(tile_at(nx - 4, ny + 3)) && corner_ok(tile_at(nx + 3, ny + 3));
}

static const unsigned char lvz[4] = { 0, 12, 24, 36 };
static unsigned char zat(unsigned char x, unsigned char y)
{
    return lvz[tile_at(x, y) & 3];
}

static void load_deck(unsigned char d)
{
    unsigned char r;
    unsigned int a;
    static unsigned char cset = 0xFF;
    lz_src = deck_data[d];
    lz_dst = DECKBUF;
    unpack();
    if (DHDR[12] != cset) {
        cset = DHDR[12];
        lz_src = cset_data[cset];
        lz_dst = CSETBUF;
        unpack();
    }
    dw = DHDR[0]; dh = DHDR[1]; mapw = DHDR[2]; maph = DHDR[3];
    X0 = DHDR[4] | (DHDR[5] << 8);
    Y0 = DHDR[6] | (DHDR[7] << 8);
    deck_ink = DHDR[8];
    deck_void = DHDR[9];
    ap_ok = 0;
    a = (unsigned int)TILES + (unsigned int)dw * dh;
    for (r = 0; r < maph; ++r) {
        MAPROWLO[r] = (unsigned char)a;
        MAPROWHI[r] = (unsigned char)(a >> 8);
        a += mapw;
    }
    cam_xmax = (mapw - 37) * 6;
    cam_ymax = (maph * 6) - (PF_BOT - PF_TOP);
}

/* ------------------------------------------------------------- camera -- */
static void cam_set(void)
{
    cam_c = (unsigned char)(cam_x / 6);
    cam_cr = (unsigned char)(cam_y / 6);
    cam_sub = (unsigned char)(cam_y % 6);
}

/* follow the player; returns 1 if the view moved */
static unsigned char cam_follow(unsigned char snap)
{
    int tx, ty;
    int ox = cam_x, oy = cam_y;
    tx = X0 + p_x - p_y - 108;
    ty = Y0 + (((unsigned int)p_x + p_y) >> 1) - zat(p_x, p_y) - 70;
    if (snap) {
        cam_x = tx - tx % 6;
        cam_y = ty - ty % 3;
    } else {
        if (tx > cam_x + 6) cam_x += 6;
        else if (tx < cam_x - 6) cam_x -= 6;
        if (ty > cam_y + 4) cam_y += 3;
        else if (ty < cam_y - 4) cam_y -= 3;
    }
    if (cam_x < 0) cam_x = 0;
    if (cam_x > cam_xmax) cam_x = cam_xmax;
    if (cam_y < 0) cam_y = 0;
    if (cam_y > cam_ymax) cam_y = cam_ymax;
    cam_set();
    return cam_x != ox || cam_y != oy;
}

/* playfield borders: red left edge, deck ink, red right edge */
static void play_screen(void)
{
    cam_follow(1);
    rect(0, 0, 1, PF_TOP, 0x11);
    rect(1, 0, 39, PF_TOP, 0x40);
    rect(0, PF_TOP, 1, PF_BOT - PF_TOP, 0x11);
    rect(1, PF_TOP, 1, PF_BOT - PF_TOP, deck_ink);
    rect(39, PF_TOP, 1, PF_BOT - PF_TOP, 0x11);
    need_full = 1;
}

/* ------------------------------------------------------------ sprites -- */
static unsigned char o_n;
#pragma bss-name (push, "HIBSS")
static unsigned char q_k[RMAX], q_x[RMAX], q_y[RMAX], q_z[RMAX];
static const unsigned char *q_d[RMAX];
static unsigned char q_ord[RMAX];
#pragma bss-name (pop)
static unsigned char q_n;

/* clip a sprite at the top edge of a taller tile standing in front of it,
 * so droids go behind walls and raised walkways */
static void set_clip(unsigned char x, unsigned char y, unsigned char z)
{
    unsigned char i = d12[x], j = d12[y], k, ti, tj, t, h;
    int c, best = PF_BOT;
    for (k = 0; k < 3; ++k) {
        ti = i + (k != 1);
        tj = j + (k != 0);
        if ((ti | tj) & 0xF0) continue;
        t = TILES[(tj << 4) | ti];
        h = lvz[t & 3] + ((t >> 2) == K_WALL ? 36 : 0);
        if (h <= z) continue;
        c = Y0 - cam_y + PF_TOP + 6 + (ti + tj) * 6 - h;
        if (c < best) best = c;
    }
    spr_clip = best < PF_TOP ? PF_TOP : (unsigned char)best;
}

static void q_add(unsigned char wx, unsigned char wy, unsigned char z, const unsigned char *d)
{
    int k;
    if (q_n >= RMAX) return;
    k = org_y + (int)(((unsigned int)wx + wy) >> 1) - z;
    q_x[q_n] = wx; q_y[q_n] = wy; q_z[q_n] = z; q_d[q_n] = d;
    q_k[q_n] = k < PF_TOP ? PF_TOP : (k > PF_BOT ? PF_BOT : (unsigned char)k);
    ++q_n;
}

/* ------------------------------------------------------------- droids -- */

static void place_droids(void)
{
    unsigned char k, tries, x, y, t;
    for (k = 0; k < nd; ++k) {
        for (tries = 0; tries < 60; ++tries) {
            x = 6 + rnd() % (dw * 12 - 12);
            y = 6 + rnd() % (dh * 12 - 12);
            t = tile_at(x, y) >> 2;
            if (t != K_FLOOR) continue;
            if (!can_go(x, y, x, y)) continue;
            if ((unsigned char)(x - p_x + 48) < 96 && (unsigned char)(y - p_y + 48) < 96) continue;
            break;
        }
        a_x[k] = x;
        a_y[k] = y;
        a_tm[k] = 1;
        a_cool[k] = 30;
        a_dx[k] = a_dy[k] = 0;
    }
}

static void enter_deck(unsigned char d)
{
    unsigned char k;
    deck = d;
    nd = deck_n[d];
    eh = e_hp[d];
    et = e_type[d];
    load_deck(d);
    p_x = DHDR[10] * 12 + 6;
    p_y = DHDR[11] * 12 + 6;
    for (k = 0; k < MAXB; ++k) b_on[k] = 0;
    for (k = 0; k < MAXX; ++k) x_on[k] = 0;
    place_droids();
    cam_follow(1);
    play_screen();
    o_n = 0;
    panel_update();
    stat("DECK ", 50);
    field(C_STAT + 5, 1, num(d + 1, 1));
}

static void init_ship(void)
{
    unsigned char d, k, t, span;
    for (d = 0; d < NDECKS; ++d) {
        deck_alive[d] = deck_n[d];
        span = deck_tmax[d] - deck_tmin[d] + 1;
        for (k = 0; k < MAXE; ++k) {
            e_hp[d][k] = 0;
            if (k >= deck_n[d]) continue;
            t = deck_tmin[d] + rnd() % span;
            if (d == NDECKS - 1 && k == 0) t = 8;  /* the command unit */
            e_type[d][k] = t;
            e_hp[d][k] = type_hp[t];
        }
    }
}

/* ---------------------------------------------------------- transfer --- */
/* Two banks of wires feed a column of cells.  The player's side is yellow
 * (left), the droid's is blue (right).  A pulse fired down a wire turns its
 * cell to your colour for a while.  Whoever holds more cells when the
 * timer runs out wins. */
#define TWN   13
#define TW0   6        /* first wire column */
#define TWL   11       /* wire length in columns */
#define TCC   17       /* cell attribute column */
#pragma bss-name (push, "HIBSS")
static unsigned char t_base[TWN], t_own[TWN], t_hold[TWN];
static unsigned char t_lk[TWN], t_rk[TWN], t_lp[TWN], t_rp[TWN];
#pragma bss-name (pop)
/* wire kinds: 0 normal, 1 dead end, 2 joins the wire below at its middle,
 * 3 fed by the wire above (no wire of its own before the join) */

static unsigned char twy(unsigned char w) { return 38 + (w << 3); }

static void t_cell(unsigned char w)
{
    unsigned char k, n = 0;
    rect(TCC, twy(w) - 3, 1, 7, t_own[w] ? 0x14 : 0x13);
    /* the block on top of the column shows who's ahead */
    for (k = 0; k < TWN; ++k) n += t_own[k];
    rect(TCC, 21, 1, 10, n > TWN / 2 ? 0x14 : 0x13);
}

/* draw one side's wire w (right = enemy side) */
static void t_wire(unsigned char w, unsigned char right)
{
    unsigned char y = twy(w), k = right ? t_rk[w] : t_lk[w];
    unsigned char c0 = right ? 22 : TW0;
    rect(c0, y - 3, TWL, 8, 0x40);
    if (right) {
        rect(20, y, 1, 2, 0x10);
        if (k == 1) { rect(20, y, 1, 2, 0x11); rect(28, y, 1, 2, 0x10); }
        if (k == 3) rect(27, y, 1, 2, 0x11);
    } else {
        rect(5, y, 1, 2, 0x10);
        if (k == 1) rect(10, y, 1, 2, 0x11);
        if (k == 3) { rect(5, y, 1, 2, 0x11); rect(12, y, 1, 2, 0x10); }
    }
    if (k == 2) rect(right ? 27 : 11, y - 2, 1, 13, 0x7E);
}

static const unsigned char arrow_r[8] = { 0x60, 0x70, 0x78, 0x7C, 0x7C, 0x78, 0x70, 0x60 };
static const unsigned char arrow_l[8] = { 0x41, 0x43, 0x47, 0x4F, 0x4F, 0x47, 0x43, 0x41 };

static void t_arrow(unsigned char col, unsigned char w, unsigned char right)
{
    unsigned char r, y = twy(w) - 3;
    const unsigned char *a = right ? arrow_l : arrow_r;
    for (r = 0; r < 8; ++r) SCREEN[(unsigned int)(y + r) * 40 + col] = a[r];
}

static void t_clear_col(unsigned char col, unsigned char w, unsigned char dash)
{
    unsigned char y = twy(w) - 3;
    rect(col, y, 1, 8, 0x40);
    if (dash) rect(col, y + 3, 1, 2, 0x7C);
}

static const unsigned char stack_g[5] = { 0x60, 0x78, 0x7E, 0x78, 0x60 };

/* pulses left: a stack of little arrowheads */
static void t_stack(unsigned char col, unsigned char n)
{
    unsigned char k, r;
    unsigned char *p = SCREEN + 36 * 40 + col;
    rect(col, 36, 1, 56, 0x40);
    for (k = 0; k < n && k < 7; ++k) {
        for (r = 0; r < 5; ++r) {
            *p = stack_g[r];
            p += 40;
        }
        p += 120;
    }
}

static void t_take(unsigned char w, unsigned char side)
{
    t_own[w] = side;
    t_hold[w] = 75;
    t_cell(w);
}

/* advance the pulse on wire w; side 0 = player (left), 1 = droid (right) */
static void t_pulse(unsigned char side, unsigned char w)
{
    unsigned char *pp = side ? t_rp : t_lp;
    unsigned char kind = side ? t_rk[w] : t_lk[w];
    unsigned char prog = pp[w], end = kind == 1 ? 4 : TWL, col;
    if (prog > 1) {
        col = side ? 34 - prog : TW0 + prog - 2;
        t_clear_col(col, w, 1);
        if (kind == 2) t_clear_col(col, w + 1, prog > 6);
    }
    if (prog <= end) {
        col = side ? 33 - prog : TW0 + prog - 1;
        t_arrow(col, w, side);
        if (kind == 2 && prog > 6) t_arrow(col, w + 1, side);
        ++pp[w];
    } else {
        if (kind != 1) {
            t_take(w, side);
            if (kind == 2) t_take(w + 1, side);
            sfx_blip(side ? 120 : 30);
        }
        pp[w] = 0;
    }
}

static void t_screen(unsigned char et)
{
    unsigned char w, y;
    rect(0, 0, 1, PF_BOT, 0x11);
    rect(1, 0, 1, PF_BOT, 0x03);
    rect(2, 0, 38, PF_BOT, 0x40);
    rect(20, PF_TOP, 1, PF_BOT - PF_TOP, 0x11);
    rect(21, PF_TOP, 1, PF_BOT - PF_TOP, 0x04);
    rect(33, PF_TOP, 1, PF_BOT - PF_TOP, 0x11);
    /* centre column frame + the two bars */
    rect(TCC, 19, 1, 122, 0x10);
    rect(4, 31, 1, 112, 0x5E);
    rect(34, 31, 1, 112, 0x5E);
    for (w = 0; w < TWN; ++w) {
        y = twy(w);
        t_wire(w, 0);
        t_wire(w, 1);
        t_cell(w);
    }
    o_n = 0;
    (void)et;
}

static void t_icons(unsigned char et)
{
    spr_desc = droid_spr[0];
    spr_ph = 0; spr_sx = 3; spr_sy = 10; spr_off = 0;
    spr_rows = spr_desc[0]; spr_cols = spr_desc[1];
    spr_draw();
    spr_desc = droid_spr[et];
    spr_sx = 33;
    spr_draw();
}

static void t_result_fx(unsigned char win)
{
    unsigned char w, i;
    for (w = 0; w < TWN; ++w) {
        t_own[w] = !win;
        t_cell(w);
        sfx_blip(win ? 140 - w * 10 : 40 + w * 14);
        pause(2);
    }
    if (!win) sfx_boom();
    for (i = 0; i < 8; ++i) {
        rect(0, PF_TOP, 1, PF_BOT - PF_TOP, (i & 1) ? 0x11 : (win ? 0x13 : 0x10));
        if (win) sfx_blip((i & 1) ? 24 : 18);
        pause(2);
    }
    stat(win ? "COMPLETE" : "FAILED", 0);
}

/* returns 1 if player wins */
static unsigned char transfer(unsigned char et)
{
    unsigned char w, cur, lp, rp, time, rep, ecool, fired, i, mine, theirs;
    unsigned char sec;

    snd_off();
    /* the briefing screen */
    frame_open();
    flogo(30);
    unit_line(64, et);
    ftext(82, 6, "PREPARE TO ENGAGE");
    ftext(94, 6, "SECURITY DEVICE");
    stat("GRAPPLE", 0);
    for (i = 0; i < 60; ++i) {
        wait_frame();
        if (i > 15 && !demo && (K_SPACE || K_RETURN)) break;
    }
again:
    lp = type_pulses[p_type];
    rp = type_pulses[et];
    for (w = 0; w < TWN; ++w) {
        t_base[w] = t_own[w] = w & 1;
        t_hold[w] = t_lp[w] = t_rp[w] = 0;
        t_lk[w] = t_rk[w] = 0;
    }
    for (i = 0; i < 16; ++i) {
        w = rnd() % TWN;
        cur = rnd() % TWN;
        mine = t_base[w]; t_base[w] = t_base[cur]; t_base[cur] = mine;
    }
    /* dead ends and joins */
    for (i = 0; i < 3; ++i) {
        w = rnd() % TWN;
        if (!t_lk[w]) t_lk[w] = 1;
        w = rnd() % TWN;
        if (!t_rk[w]) t_rk[w] = 1;
    }
    for (i = 0; i < 2; ++i) {
        w = rnd() % (TWN - 1);
        if (!t_lk[w] && !t_lk[w + 1]) { t_lk[w] = 2; t_lk[w + 1] = 3; }
        w = rnd() % (TWN - 1);
        if (!t_rk[w] && !t_rk[w + 1]) { t_rk[w] = 2; t_rk[w + 1] = 3; }
    }
    for (w = 0; w < TWN; ++w) t_own[w] = t_base[w];
    t_screen(et);
    t_icons(et);
    cur = 0;
    t_arrow(3, cur, 0);
    t_stack(2, lp);
    t_stack(36, rp);
    stat("TIME 99", 0);
    pause(20);

    time = 0;
    sec = 99;
    rep = 0;
    ecool = 20 + (rnd() & 31);
    fired = 1;
    while (sec) {
        wait_frame();
        if (++time == 2) {
            time = 0;
            --sec;
            field(C_STAT + 5, 2, num(sec, 2));
        }

        if (demo) {
            /* autopilot: hold pulses back, then flip enemy cells late on */
            in_up = in_down = in_fire = 0;
            if (any_key()) { demo = 0; game_over = 1; }
            if (sec < 55 && lp) {
                for (w = 0; w < TWN; ++w)
                    if (t_lk[w] != 1 && t_lk[w] != 3 && !t_lp[w] && t_own[w]) break;
                if (w < TWN) {
                    if (w < cur) in_up = 1;
                    else if (w > cur) in_down = 1;
                    else in_fire = !fired && (frame & 3) == 0;
                }
            }
        } else {
            read_input();
            in_fire |= K_RETURN;
        }
        if (rep) --rep;
        if (!rep && in_up && cur > 0) {
            t_clear_col(3, cur, 0); --cur; t_arrow(3, cur, 0); rep = 3;
        }
        if (!rep && in_down && cur < TWN - 1) {
            t_clear_col(3, cur, 0); ++cur; t_arrow(3, cur, 0); rep = 3;
        }
        if (in_fire) {
            if (!fired && lp && !t_lp[cur] && t_lk[cur] != 3) {
                --lp; t_lp[cur] = 1; t_stack(2, lp); sfx_blip(60);
            }
            fired = 1;
        } else fired = 0;

        /* enemy AI: saves its pulses, keener as the clock runs down */
        if (ecool) --ecool;
        else if (rp && rnd() < 8 + et * 4 + ((99 - sec) >> 1)) {
            for (i = 0; i < 8; ++i) {
                w = rnd() % TWN;
                if ((t_rk[w] == 1 || t_rk[w] == 3) && rnd() > 24) continue;
                if (t_rk[w] == 3 || t_rp[w] || (t_own[w] && t_hold[w] > 25)) continue;
                if (t_own[w] && !t_hold[w] && rnd() > 60) continue;
                --rp; t_rp[w] = 1; t_stack(36, rp); sfx_blip(90);
                ecool = 30 - et * 2;
                break;
            }
        }

        /* pulses travel one column every other frame */
        for (w = 0; w < TWN; ++w) {
            if (frame & 1) {
                if (t_lp[w]) t_pulse(0, w);
                if (t_rp[w]) t_pulse(1, w);
            }
            if (t_hold[w] && !--t_hold[w] && t_own[w] != t_base[w]) {
                t_own[w] = t_base[w];
                t_cell(w);
            }
        }
        /* the wire behind a finished pulse goes dark again */
        if ((frame & 15) == 0)
            for (w = 0; w < TWN; ++w) {
                if (!t_lp[w] && !t_hold[w]) t_wire(w, 0);
                if (!t_rp[w] && !t_hold[w]) t_wire(w, 1);
            }
        if (game_over) return 0;
    }
    mine = theirs = 0;
    for (w = 0; w < TWN; ++w) {
        if (t_own[w]) ++theirs; else ++mine;
    }
    if (mine == theirs) {
        stat("DEADLOCK", 0);
        pause(40);
        goto again;
    }
    t_result_fx(mine > theirs);
    pause(40);
    if (mine > theirs) {
        frame_open();
        flogo(30);
        unit_line(64, et);
        ftext(76, 6, "SECURITY CLASS");
        ftext(88, 3, type_sec[et]);
        ftext(106, 2, "TRANSFER COMPLETE");
        pause(50);
    }
    return mine > theirs;
}

/* --------------------------------------------------------------- play -- */
static void boom(unsigned char x, unsigned char y, unsigned char z)
{
    unsigned char k;
    for (k = 0; k < MAXX; ++k)
        if (!x_on[k]) {
            x_on[k] = 12; x_x[k] = x; x_y[k] = y; x_z[k] = z;
            break;
        }
    sfx_boom();
}

static void fire(unsigned char x, unsigned char y, signed char dx, signed char dy,
                 unsigned char dmg, unsigned char own)
{
    unsigned char k;
    for (k = 0; k < MAXB; ++k)
        if (!b_on[k]) {
            b_on[k] = 1;
            b_x[k] = x + dx * 6;
            b_y[k] = y + dy * 6;
            b_z[k] = zat(x, y);
            b_dx[k] = dx * 4;
            b_dy[k] = dy * 4;
            b_life[k] = 24;
            b_dmg[k] = dmg;
            b_own[k] = own;
            if (own == 0) sfx_shot();
            else sfx_blip(200);
            return;
        }
}

static void check_cleared(void)
{
    unsigned char d;
    if (deck_alive[deck]) return;
    score += 50;
    for (d = 0; d < NDECKS; ++d)
        if (deck_alive[d]) {
            stat("CLEARED", 75);
            return;
        }
    won = 1;
    game_over = 1;
}

static void kill_droid(unsigned char a)
{
    eh[a] = 0;
    --deck_alive[deck];
    score += type_score[et[a]];
    boom(a_x[a], a_y[a], zat(a_x[a], a_y[a]));
    panel_update();
    check_cleared();
}

static void hurt_droid(unsigned char a, unsigned char dmg)
{
    if (eh[a] <= dmg) kill_droid(a);
    else eh[a] -= dmg;
}

static void hurt_player(unsigned char dmg)
{
    if (demo) dmg = (dmg + 1) >> 1;      /* keep the attract mode going */
    if (p_hp <= dmg) {
        boom(p_x, p_y, zat(p_x, p_y));
        if (p_type) {
            p_type = 0;
            p_hp = type_hp[0] / 2;
            stat("EJECTED", 60);
        } else {
            p_hp = 0;
            game_over = 1;
        }
    } else p_hp -= dmg;
    panel_update();
}

static signed char sgn(unsigned char a, unsigned char b, unsigned char dead)
{
    if (a > b + dead) return 1;
    if (b > a + dead) return -1;
    return 0;
}

static unsigned char close_to(unsigned char ax, unsigned char ay, unsigned char bx, unsigned char by, unsigned char r)
{
    return (unsigned char)(ax - bx + r) < (unsigned char)(r * 2) &&
           (unsigned char)(ay - by + r) < (unsigned char)(r * 2);
}

static signed char touching(unsigned char x, unsigned char y, unsigned char r)
{
    unsigned char a;
    for (a = 0; a < nd; ++a)
        if (eh[a] && close_to(x, y, a_x[a], a_y[a], r)) return a;
    return -1;
}

static unsigned char any_key(void)
{
    unsigned char r;
    for (r = 0; r < 8; ++r)
        if (keys[r]) return 1;
    return 0;
}

static void autopilot(void);

static void read_input(void)
{
    if (demo) {
        in_esc = any_key();
        autopilot();
        return;
    }
    in_dx = in_dy = 0;
    if (K_UP || K_Q)    { --in_dx; --in_dy; }
    if (K_DOWN || K_A)  { ++in_dx; ++in_dy; }
    if (K_LEFT || K_O)  { --in_dx; ++in_dy; }
    if (K_RIGHT || K_P) { ++in_dx; --in_dy; }
    if (in_dx > 1) in_dx = 1;
    if (in_dx < -1) in_dx = -1;
    if (in_dy > 1) in_dy = 1;
    if (in_dy < -1) in_dy = -1;
    in_fire = K_SPACE;
    in_grab = K_T || K_RETURN;
    in_lift = K_L;
    in_esc = K_ESC;
    in_up = K_UP || K_Q;
    in_down = K_DOWN || K_A;
}

static void ram(signed char a)
{
    if (p_ram) return;
    p_ram = 12;
    sfx_ram();
    hurt_droid(a, type_mass[p_type]);
    hurt_player(type_mass[et[a]]);
}

static void move_player(void)
{
    signed char dx = in_dx, dy = in_dy, a;
    unsigned char sp, nx, ny, k;

    if (dx || dy) { p_fx = dx; p_fy = dy; }
    sp = type_speed[p_type];
    for (k = 0; k < sp; ++k) {
        nx = p_x + dx;
        if (dx && can_go(p_x, p_y, nx, p_y)) {
            a = touching(nx, p_y, 11);
            if (a < 0) p_x = nx;
            else ram(a);
        }
        ny = p_y + dy;
        if (dy && can_go(p_x, p_y, p_x, ny)) {
            a = touching(p_x, ny, 11);
            if (a < 0) p_y = ny;
            else ram(a);
        }
    }
    if (p_ram) --p_ram;
}

static void update_droids(void)
{
    unsigned char a, t, nx, ny, k, sp;
    for (a = 0; a < nd; ++a) {
        if (!eh[a]) continue;
        /* droids far from the player doze */
        if (!close_to(a_x[a], a_y[a], p_x, p_y, 100)) continue;
        t = et[a];
        if (!--a_tm[a]) {
            a_tm[a] = 12 + (rnd() & 31);
            if (rnd() < 40 + t * 20) {
                a_dx[a] = sgn(p_x, a_x[a], 6);
                a_dy[a] = sgn(p_y, a_y[a], 6);
                if (t == 2) a_dx[a] = a_dy[a] = 0;   /* sentries hold still */
            } else {
                a_dx[a] = (rnd() % 3) - 1;
                a_dy[a] = (rnd() % 3) - 1;
            }
        }
        sp = ((frame & 1) || type_speed[t] > 1) ? 1 : 0;
        for (k = 0; k < sp; ++k) {
            nx = a_x[a] + a_dx[a];
            ny = a_y[a] + a_dy[a];
            if (!can_go(a_x[a], a_y[a], nx, ny) || close_to(nx, ny, p_x, p_y, 11)) {
                a_tm[a] = 1;
                break;
            }
            a_x[a] = nx;
            a_y[a] = ny;
        }
        if (type_dmg[t]) {
            if (a_cool[a]) --a_cool[a];
            else if (close_to(a_x[a], a_y[a], p_x, p_y, 70)) {
                signed char fx = sgn(p_x, a_x[a], 10), fy = sgn(p_y, a_y[a], 10);
                if (fx || fy) fire(a_x[a], a_y[a], fx, fy, type_dmg[t], 1);
                a_cool[a] = type_rate[t] + (rnd() & 15);
            }
        }
    }
}

static void update_bullets(void)
{
    unsigned char k, a, t;
    for (k = 0; k < MAXB; ++k) {
        if (!b_on[k]) continue;
        b_x[k] += b_dx[k];
        b_y[k] += b_dy[k];
        t = tile_at(b_x[k], b_y[k]);
        if (!--b_life[k] || !walkable[t >> 2] || (t & 3) * 12 > b_z[k]) {
            b_on[k] = 0;
            continue;
        }
        if (b_own[k] == 0) {
            for (a = 0; a < nd; ++a)
                if (eh[a] && close_to(b_x[k], b_y[k], a_x[a], a_y[a], 8)) {
                    b_on[k] = 0;
                    hurt_droid(a, b_dmg[k]);
                    break;
                }
        } else if (close_to(b_x[k], b_y[k], p_x, p_y, 7)) {
            b_on[k] = 0;
            hurt_player(b_dmg[k]);
        }
    }
}

/* -------------------------------------------------------------- render - */
static void render(void)
{
    unsigned char i, j, t, a, full, done;

    full = cam_follow(0) | need_full;
    need_full = 0;
    org_x = X0 + 12 - cam_x;
    org_y = Y0 + PF_TOP + 3 - cam_y;
    q_n = 0;
    for (a = 0; a < nd; ++a)
        if (eh[a] && close_to(a_x[a], a_y[a], p_x, p_y, 120))
            q_add(a_x[a], a_y[a], zat(a_x[a], a_y[a]), droid_spr[et[a]]);
    if (!game_over || p_hp) {
        /* the player always looks like the influence device, whatever it
         * has taken over; after a transfer it blinks for a moment */
        if (p_flash) {
            --p_flash;
            if (p_fkind == 1 && (frame & 1)) sfx_blip(12 + p_flash * 4);
        }
        if (!p_flash || (frame & 2)) q_add(p_x, p_y, zat(p_x, p_y), droid_spr[0]);
    }
    for (a = 0; a < MAXB; ++a)
        if (b_on[a]) q_add(b_x[a], b_y[a], b_z[a] + 8, spr_bullet);
    for (a = 0; a < MAXX; ++a)
        if (x_on[a]) {
            q_add(x_x[a], x_y[a], x_z[a], (x_on[a] & 4) ? spr_boom1 : spr_boom0);
            --x_on[a];
        }

    for (i = 0; i < q_n; ++i) q_ord[i] = i;
    for (i = 1; i < q_n; ++i)
        for (j = i; j && q_k[q_ord[j - 1]] > q_k[q_ord[j]]; --j) {
            t = q_ord[j]; q_ord[j] = q_ord[j - 1]; q_ord[j - 1] = t;
        }

    if (!full)
        for (i = 0; i < o_n; ++i) {
            rc_c = o_c[i]; rc_w = o_w[i]; rc_y = o_y[i]; rc_h = o_h[i];
            pf_rect();
        }
    /* After a scroll the playfield is redrawn top to bottom, and each
     * sprite goes back as soon as the rows under it are done - so nothing
     * is missing from the screen for long. */
    done = PF_TOP;
    rc_c = 2; rc_w = 37;
    n_n = 0;
    for (i = 0; i < q_n; ++i) {
        j = q_ord[i];
        if (full && q_k[j] > done) {
            rc_y = done; rc_h = q_k[j] - done;
            pf_rect();
            done = q_k[j];
            rc_c = 2; rc_w = 37;
        }
        ps_x = q_x[j]; ps_y = q_y[j]; ps_z = q_z[j]; spr_desc = q_d[j];
        /* the player always stays in view */
        if (ps_x == p_x && ps_y == p_y) spr_clip = PF_BOT;
        else set_clip(ps_x, ps_y, ps_z);
        put_sprite();
    }
    if (full && done < PF_BOT) {
        rc_c = 2; rc_w = 37;
        rc_y = done; rc_h = PF_BOT - done;
        pf_rect();
    }
    /* draw the player once more on top, so a droid standing in front of
     * it can never hide it */
    for (i = 0; i < q_n; ++i)
        if (q_x[i] == p_x && q_y[i] == p_y && q_d[i] != spr_bullet) {
            ps_x = p_x; ps_y = p_y; ps_z = q_z[i]; spr_desc = q_d[i];
            spr_clip = PF_BOT;
            put_sprite();
            break;
        }
    o_n = n_n;
}

/* ------------------------------------------------------------ autopilot */
/* Drives the player in demo mode: BFS over the deck's tiles. */
#pragma bss-name (push, "PAGE4")
static unsigned char ap_dist[256];
#pragma bss-name (pop)
#pragma bss-name (push, "HIBSS")
static unsigned char ap_q[256];
#pragma bss-name (pop)
static unsigned char ap_tt;
static unsigned char ap_lx, ap_ly, ap_still, ap_alt;
static signed char ap_ax, ap_ay;

static unsigned char tstep(unsigned char a, unsigned char b)
{
    unsigned char ta = TILES[a], tb = TILES[b];
    unsigned char la = ta & 3, lb = tb & 3;
    if (!walkable[tb >> 2]) return 0;
    if (la == lb) return 1;
    return (la + 1 == lb || lb + 1 == la) && ((ta >> 2) == K_PAD || (tb >> 2) == K_PAD);
}

/* tile index of the neighbour of c in direction k, or c itself if none */
static unsigned char nbr(unsigned char c, unsigned char k)
{
    unsigned char i = c & 15;
    if (k == 0) return i ? c - 1 : c;
    if (k == 1) return i < 15 ? c + 1 : c;
    if (k == 2) return c >= 16 ? c - 16 : c;
    return c < 240 ? c + 16 : c;
}

/* breadth-first distances to tile t (decks are 16 x 16 tiles) */
static void ap_bfs(unsigned char t)
{
    unsigned char h = 0, tl = 0, c, m, d, k;
    c = 0;
    do ap_dist[c] = 0xFF; while (++c);
    ap_dist[t] = 0;
    ap_q[tl++] = t;
    do {
        c = ap_q[h++];
        d = ap_dist[c] + 1;
        for (k = 0; k < 4; ++k) {
            m = nbr(c, k);
            if (m != c && ap_dist[m] == 0xFF && tstep(m, c)) {
                ap_dist[m] = d;
                ap_q[tl++] = m;
            }
        }
    } while (h != tl);
    ap_tt = t;
    ap_ok = 1;
}

static void ap_goto(unsigned char tx, unsigned char ty)
{
    unsigned char c, n, best, bd, k, m, cx, cy;
    n = (d12[ty] << 4) | d12[tx];
    if (n != ap_tt || !ap_ok) ap_bfs(n);
    c = (d12[p_y] << 4) | d12[p_x];
    in_dx = in_dy = 0;
    if (c == ap_tt || ap_dist[c] == 0xFF) {
        in_dx = sgn(tx, p_x, 1);
        in_dy = sgn(ty, p_y, 1);
        return;
    }
    best = c; bd = ap_dist[c];
    for (k = 0; k < 4; ++k) {
        m = nbr(c, k);
        if (ap_dist[m] < bd) { bd = ap_dist[m]; best = m; }
    }
    cx = (best & 15) * 12 + 6;
    cy = (best >> 4) * 12 + 6;
    /* centre on the cross axis first so corners don't snag */
    if ((best ^ c) < 16) {
        in_dy = sgn(cy, p_y, 1); in_dx = sgn(cx, p_x, 0);
    } else {
        in_dx = sgn(cx, p_x, 1); in_dy = sgn(cy, p_y, 0);
    }
}

static void autopilot(void)
{
    unsigned char a, best = 0xFF, bd = 0xFF, d, adx, ady, t;
    signed char sx, sy;

    in_fire = in_grab = in_lift = 0;
    if (ap_alt) {
        --ap_alt;
        in_dx = ap_ax;
        in_dy = ap_ay;
        return;
    }
    for (a = 0; a < nd; ++a)
        if (eh[a]) {
            adx = (a_x[a] > p_x) ? a_x[a] - p_x : p_x - a_x[a];
            ady = (a_y[a] > p_y) ? a_y[a] - p_y : p_y - a_y[a];
            d = (adx > ady) ? adx : ady;
            if (d < bd) { bd = d; best = a; }
        }
    if (best != 0xFF) {
        a = best;
        t = et[a];
        adx = (a_x[a] > p_x) ? a_x[a] - p_x : p_x - a_x[a];
        ady = (a_y[a] > p_y) ? a_y[a] - p_y : p_y - a_y[a];
        /* grapple droids that outclass our host */
        if (t > p_type && p_hp > 12 && (rnd() & 3) == 0) {
            if (bd < 15) { in_grab = 1; in_dx = in_dy = 0; return; }
            ap_goto(a_x[a], a_y[a]);
            return;
        }
        if (bd < 60 && zat(a_x[a], a_y[a]) == zat(p_x, p_y) &&
            (adx < 5 || ady < 5 || (adx > ady ? adx - ady : ady - adx) < 5)) {
            sx = (adx < 5) ? 0 : sgn(a_x[a], p_x, 0);
            sy = (ady < 5) ? 0 : sgn(a_y[a], p_y, 0);
            p_fx = sx; p_fy = sy;
            in_fire = 1;
            in_dx = in_dy = 0;
            if (bd < 20) { in_dx = -sx; in_dy = -sy; }   /* back off */
        } else ap_goto(a_x[a], a_y[a]);
    } else {
        /* deck clear: back to the lift */
        ap_goto(DHDR[10] * 12 + 6, DHDR[11] * 12 + 6);
        in_lift = ((tile_at(p_x, p_y) >> 2) == K_LIFT) && (frame & 1);
    }

    if ((in_dx || in_dy) && p_x == ap_lx && p_y == ap_ly) {
        if (++ap_still > 6) {
            ap_still = 0;
            ap_alt = 8 + (rnd() & 15);
            ap_ax = (rnd() % 3) - 1;
            ap_ay = (rnd() % 3) - 1;
        }
    } else ap_still = 0;
    ap_lx = p_x;
    ap_ly = p_y;
}

/* --------------------------------------------------------------- title - */
static void title(void)
{
    unsigned int k;
    snd_off();
    frame_open();
    draw_panel();
    stat("", 0);
    field(C_UNIT, 2, "  ");
    field(C_SCORE, 6, num(0, 6));
    flogo(28);
    ftext(54, 6, "ORIC ATMOS VERSION");
    ftext(66, 6, "AFTER THE GRAFTGOLD GAME");
    ftext(84, 2, "ARROWS OR QAOP  MOVE");
    ftext(94, 2, "SPACE  FIRE  T  GRAPPLE");
    ftext(104, 2, "L  LIFT    ESC  ABANDON");
    demo = 0;
    for (k = 0; k < 400; ++k) {
        wait_frame();
        rnd();
        if (K_SPACE) break;
        if ((frame & 15) == 0) ftext(120, 3, "PRESS SPACE TO PLAY");
        if ((frame & 15) == 8) ftext(120, 3, "                   ");
    }
    if (k == 400) demo = 1;          /* idle on the title: run the demo */
    while (K_SPACE) wait_frame();
}

static void end_screen(void)
{
    snd_off();
    frame_open();
    flogo(30);
    if (won) {
        ftext(64, 3, "THE SHIP IS SECURED");
        ftext(76, 6, "ALL DECKS CLEARED");
    } else {
        ftext(64, 3, "GAME OVER");
        ftext(76, 6, "INFLUENCE DEVICE DESTROYED");
    }
    ftext(98, 2, "SCORE");
    num(score, 5);
    nbuf[5] = '0'; nbuf[6] = 0;
    ftext(110, 2, nbuf);
    pause(150);
}

static void play(void)
{
    unsigned char k, keyt, t;
    signed char a;

    score = 0;
    game_over = won = 0;
    p_type = 0;
    p_hp = type_hp[0];
    p_fx = p_fy = 1;
    p_cool = p_ram = p_burn = 0;
    p_flash = p_grab = p_hold = 0;
    init_ship();
    draw_panel();
    enter_deck(0);
    kprev = 0xFF;

    while (!game_over) {
        wait_frame();
        read_input();
        keyt = 0;
        if (in_grab) keyt |= 1;
        if (in_lift) keyt |= 2;
        if (in_esc) keyt |= 4;
        k = keyt & ~kprev;
        kprev = keyt;
        if (k & 4) break;

        move_player();

        /* hold fire while standing still to grapple, as on the Spectrum;
         * then run into a droid to start the transfer */
        if (in_fire && !in_dx && !in_dy) {
            if (++p_hold == 12) { p_grab = 150; stat("GRAPPLE", 0); gbox(0x17); }
        } else p_hold = 0;
        if (p_grab && !--p_grab) { stat("MOBILE", 0); gbox(0x15); }
        if (p_grab) k |= 1;

        /* fire */
        if (p_cool) --p_cool;
        else if (in_fire && type_dmg[p_type] && !p_grab) {
            fire(p_x, p_y, p_fx, p_fy, type_dmg[p_type], 0);
            p_cool = type_rate[p_type];
        }

        t = tile_at(p_x, p_y) >> 2;
        /* lift / energiser */
        if (t == K_LIFT && (k & 2)) {
            stat("LIFT", 0);
            sfx_blip(60);
            pause(10);
            enter_deck(deck + 1 < NDECKS ? deck + 1 : 0);
            continue;
        }
        if (t == K_ENERG && (frame & 3) == 0 && p_hp < type_hp[p_type]) {
            ++p_hp;
            sfx_blip(40 + p_hp);
            if (!msg_time) stat("CHARGING", 10);
            panel_update();
        }

        /* host burnout */
        if (p_type && ++p_burn >= 75) {
            p_burn = 0;
            hurt_player(1);
        }

        /* grapple + transfer */
        if (k & 1) {
            a = touching(p_x, p_y, 16);
            if (a >= 0) {
                unsigned char ty = et[a];
                p_grab = p_hold = 0;
                stat("GRAPPLE", 0);
                gbox(0x17);
                pause(10);
                if (transfer(ty)) {
                    p_type = ty;
                    p_hp = eh[a];
                    if (p_hp < type_hp[ty] / 2) p_hp = type_hp[ty] / 2;
                    eh[a] = 0;
                    --deck_alive[deck];
                    score += type_score[ty] * 2;
                    p_flash = 30; p_fkind = 1;
                    play_screen();
                    o_n = 0;
                    panel_update();
                    stat("MOBILE", 0);
                    check_cleared();
                } else {
                    /* the droid throws you off: push it back a little */
                    for (t = 0; t < 14; ++t) {
                        unsigned char nx = a_x[a] + sgn(a_x[a], p_x, 0), ny = a_y[a] + sgn(a_y[a], p_y, 0);
                        if (!can_go(a_x[a], a_y[a], nx, ny)) break;
                        a_x[a] = nx; a_y[a] = ny;
                    }
                    a_tm[a] = 1;
                    play_screen();
                    o_n = 0;
                    boom(p_x, p_y, zat(p_x, p_y));
                    p_flash = 25; p_fkind = 2;
                    if (p_type) {
                        p_type = 0;
                        p_hp = type_hp[0] / 2;
                        panel_update();
                    } else {
                        hurt_player(type_hp[0] / 2);
                    }
                    stat("FAILED", 50);
                }
                gbox(0x15);
                if (game_over && !p_hp) break;
                continue;
            }
        }

        update_droids();
        update_bullets();
        render();
        if (msg_time && !--msg_time) stat(demo ? "DEMO" : "MOBILE", 0);
    }
    if (!game_over) return;          /* ESC, or a key pressed during the demo */
    if (!p_hp || won)
        for (k = 0; k < 25; ++k) {
            wait_frame();
            render();
        }
    end_screen();
}

void main(void)
{
    unsigned int k;
    hw_init();
    hires_on();
    snd_init();
    for (k = 0; k < 256; ++k) d12[k] = (unsigned char)(k / 12);
    for (;;) {
        title();
        play();
    }
}
