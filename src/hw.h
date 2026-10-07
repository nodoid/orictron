/* hw.h - interface to the assembly routines in oric.s and gfxdata.s */
#ifndef HW_H
#define HW_H

void hw_init(void);
void hires_on(void);
void spr_draw(void);
void kbd_scan(void);
void wait_tick(void);
void frame_sync(void);
void fill_rect(void);
void hchar(void);
void unpack(void);
void pf_all(void);
void pf_rect(void);
void put_sprite(void);
unsigned char __fastcall__ tile_xy(unsigned int xy);
#define tile_at(x, y) tile_xy(((unsigned int)(unsigned char)(y) << 8) | (unsigned char)(x))
void __fastcall__ ay_write(unsigned char reg, unsigned char val);

extern const unsigned char *spr_desc;
extern unsigned char spr_ph, spr_sx, spr_sy, spr_rows, spr_cols, spr_off;
extern unsigned char fr_col, fr_y, fr_w, fr_h, fr_val;
extern unsigned char hc_col, hc_y, hc_ch, hc_inv;
extern unsigned char keys[8];
extern unsigned char ticks;
extern unsigned char cam_c, cam_cr, cam_sub, mapw;
extern unsigned char rc_c, rc_w, rc_y, rc_h;
extern unsigned char ps_x, ps_y, ps_z, n_n, spr_clip;
extern int org_x, org_y;
extern unsigned char o_c[], o_w[], o_y[], o_h[];
extern unsigned char d12[256];
extern const unsigned char *lz_src;
extern unsigned char *lz_dst;

extern const unsigned char font[];
extern const unsigned char *const droid_spr[9];
extern const unsigned char spr_boom0[], spr_boom1[], spr_bullet[];
extern const unsigned char *const deck_data[6];
extern const unsigned char *const cset_data[2];
extern const unsigned char panel_lz[], frame_lz[], logo[];

/* keyboard matrix: keys[row] bit col */
#define KEYDOWN(r, b) (keys[r] & (1 << (b)))
#define K_SPACE  KEYDOWN(4, 0)
#define K_UP     KEYDOWN(4, 3)
#define K_LEFT   KEYDOWN(4, 5)
#define K_DOWN   KEYDOWN(4, 6)
#define K_RIGHT  KEYDOWN(4, 7)
#define K_Q      KEYDOWN(1, 6)
#define K_A      KEYDOWN(6, 5)
#define K_O      KEYDOWN(5, 2)
#define K_P      KEYDOWN(5, 3)
#define K_T      KEYDOWN(1, 1)
#define K_L      KEYDOWN(7, 1)
#define K_RETURN KEYDOWN(7, 5)
#define K_ESC    KEYDOWN(1, 5)

#define SCREEN ((unsigned char *)0xA000)

/* deck buffer, filled by unpack() */
#define CSETBUF  ((unsigned char *)0x8A00)
#define DECKBUF  ((unsigned char *)0x9000)
#define DHDR     ((unsigned char *)0x9100)
#define TILES    ((unsigned char *)0x9110)
#define MAPROWLO ((unsigned char *)0x9F00)
#define MAPROWHI ((unsigned char *)0x9F40)

#endif
