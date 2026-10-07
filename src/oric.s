; oric.s - low level Oric Atmos hardware routines
;
; The game takes the machine over completely: interrupts are disabled and
; the ROM is never called, so the keyboard, AY sound chip and VIA timer are
; all driven directly from here.
;
; The playfield is a scrolling window onto the current deck's cell map: each
; cell is one screen byte wide and 6 rows tall, and its bytes come from a
; planar character set (PL0..PL5, one page per cell row).

        .export _hw_init, _hires_on
        .export _spr_draw, _kbd_scan, _ay_write, _wait_tick
        .export _fill_rect, _hchar, _unpack
        .export _pf_rect, _pf_all
        .export _spr_desc, _spr_ph, _spr_sx, _spr_sy, _spr_rows, _spr_cols, _spr_off
        .export _fr_col, _fr_y, _fr_w, _fr_h, _fr_val
        .export _hc_col, _hc_y, _hc_ch, _hc_inv
        .export _keys, _ticks
        .export _cam_c, _cam_cr, _cam_sub, _mapw
        .export _rc_c, _rc_w, _rc_y, _rc_h
        .export _lz_src, _lz_dst
        .export _put_sprite, _tile_xy, _frame_sync
        .export _ps_x, _ps_y, _ps_z, _org_x, _org_y, _n_n, _spr_clip
        .export _o_c, _o_w, _o_y, _o_h

        .import _font, _rowlo, _rowhi, _d12
        .import popa

VIA_ORB  = $0300
VIA_DDRB = $0302
VIA_DDRA = $0303
VIA_T1CL = $0304
VIA_T1CH = $0305
VIA_T2CL = $0308
VIA_T2CH = $0309
VIA_ACR  = $030B
VIA_PCR  = $030C
VIA_IFR  = $030D
VIA_IER  = $030E
VIA_ORA  = $030F

HIRES    = $A000
TEXTLINES= $BF68

; deck buffer (filled by unpack): planar charset at $8A00, then leftfix,
; header, tiles and cell map from $9000
PL0      = $8A00
LEFTFIX  = $9000
MAPROWLO = $9F00            ; per map row: address of its first cell
MAPROWHI = $9F40

PF_TOP   = 8                ; first playfield row
PF_BOT   = 152              ; first row after the playfield
PF_C0    = 2                ; first playfield byte column (shows leftfix)
PF_C1    = 39               ; first column after the playfield

; zero page scratch (ROM workspace - unused since the ROM never runs)
zs   = $50      ; sprite data ptr / lz source
zm   = $52      ; sprite mask ptr
zd   = $54      ; screen ptr / lz dest
zmap = $56      ; map ptr
zt   = $58      ; temp ptr
rows = $5A
wid  = $5B
tmp  = $5C
kacc = $5E
krow = $5F
ry   = $60      ; current screen row
rsub = $61      ; current row within the map cell
rmr  = $62      ; current map row
rend = $63      ; last screen row + 1
rw1  = $64      ; rect width - 1
sxl  = $65      ; put_sprite scratch
sxh  = $66
syl  = $67
syh  = $68
vl   = $69
vh   = $6A
pcol = $6B
pskip= $6C
plsk = $6D
pcols= $6E
prow0= $6F
ph_h = $70
ph_xo= $71
prows= $72
lff  = $73      ; pf_rect covers the leftmost (attribute) column

TILES    = $9110
RMAX     = 23

        .bss
_spr_desc: .res 2
_spr_ph:   .res 1
_spr_sx:   .res 1
_spr_sy:   .res 1
_spr_rows: .res 1
_spr_cols: .res 1
_spr_off:  .res 1
_fr_col: .res 1
_fr_y:   .res 1
_fr_w:   .res 1
_fr_h:   .res 1
_fr_val: .res 1
_hc_col: .res 1
_hc_y:   .res 1
_hc_ch:  .res 1
_hc_inv: .res 1
_keys:   .res 8
_ticks:  .res 1
_cam_c:  .res 1             ; map column shown in screen column PF_C0
_cam_cr: .res 1             ; map cell row at the top of the playfield
_cam_sub: .res 1            ; ... and the row within it
_mapw:   .res 1
_rc_c:   .res 1             ; rect for pf_rect: first column, width,
_rc_w:   .res 1
_rc_y:   .res 1             ; first row, height
_rc_h:   .res 1
_lz_src: .res 2
_lz_dst: .res 2
_ps_x:   .res 1
_ps_y:   .res 1
_ps_z:   .res 1
_org_x:  .res 2
_org_y:  .res 2
_n_n:    .res 1
_spr_clip: .res 1           ; rows from here down are hidden
_o_c:    .res RMAX
_o_w:    .res RMAX
_o_y:    .res RMAX
_o_h:    .res RMAX

        .code

; ---------------------------------------------------------------------------
; hw_init: disable interrupts, set up VIA ports and a 50Hz free running T1
_hw_init:
        sei
        cld
        lda #$7F
        sta VIA_IER         ; disable every VIA interrupt source
        lda #$F7
        sta VIA_DDRB        ; PB3 = keyboard sense input
        lda #$FF
        sta VIA_DDRA
        lda #$DD
        sta VIA_PCR         ; AY bus inactive
        lda #$40
        sta VIA_ACR         ; T1 continuous, PB7 untouched
        lda #<19998
        sta VIA_T1CL
        lda #>19998
        sta VIA_T1CH        ; load + start, 20ms period
        ; mixer: all channels off, port A = output (needed for keyboard)
        lda #7
        jsr ay_reg
        lda #$7F
        jsr ay_val
        ldx #8
@vol:   txa
        jsr ay_reg
        lda #0
        jsr ay_val
        inx
        cpx #11
        bne @vol
        rts

; ---------------------------------------------------------------------------
; AY access.  ay_reg: A = register number.  ay_val: A = value
ay_reg: sta VIA_ORA
        lda #$FF
        sta VIA_PCR
        lda #$DD
        sta VIA_PCR
        rts
ay_val: sta VIA_ORA
        lda #$FD
        sta VIA_PCR
        lda #$DD
        sta VIA_PCR
        rts

; void __fastcall__ ay_write(unsigned char reg, unsigned char val)
_ay_write:
        pha
        jsr popa
        jsr ay_reg
        pla
        jmp ay_val

; ---------------------------------------------------------------------------
; kbd_scan: read the full 8x8 key matrix into keys[row], bit = column
_kbd_scan:
        lda #14
        jsr ay_reg
        ldx #7
@row:   stx krow
        lda VIA_ORB
        and #$F8
        ora krow
        sta VIA_ORB
        lda #0
        sta kacc
        ldy #7
@col:   lda colmask,y
        sta VIA_ORA
        lda #$FD
        sta VIA_PCR
        lda #$DD
        sta VIA_PCR
        nop
        nop
        nop
        nop
        lda VIA_ORB
        and #$08
        cmp #$08            ; C = 1 when key down
        rol kacc
        dey
        bpl @col
        lda kacc
        sta _keys,x
        dex
        bpl @row
        rts

colmask: .byte $FE,$FD,$FB,$F7,$EF,$DF,$BF,$7F

; ---------------------------------------------------------------------------
; frame_sync: wait until at least 40ms (25 fps) have passed since the last
; call.  VIA timer 2 runs as a stopwatch: reloaded with $FFFF each frame, it
; counts down at 1MHz; its interrupt flag means more than 65ms went by.
_frame_sync:
@w:     lda VIA_IFR
        and #$20
        bne @go
        lda VIA_T2CH
        cmp #>($FFFF - 40000)
        bcs @w
@go:    lda #$FF
        sta VIA_T2CL
        sta VIA_T2CH        ; reload + clear the flag
        rts

; ---------------------------------------------------------------------------
; wait_tick: wait for the next 20ms timer tick
_wait_tick:
@w:     lda VIA_IFR
        and #$40
        beq @w
        lda VIA_T1CL        ; acknowledge
        inc _ticks
        rts

; ---------------------------------------------------------------------------
; hires_on: clear screen to black, blank the text lines, switch to HIRES
_hires_on:
        lda #<HIRES
        sta zd
        lda #>HIRES
        sta zd+1
        ldx #32
        lda #$40
        ldy #0
@ch:    sta (zd),y
        iny
        bne @ch
        inc zd+1
        dex
        bne @ch
        ; the three text lines under the HIRES picture: red paper attributes
        ldy #119
        lda #$11
@ct:    sta TEXTLINES,y
        dey
        bpl @ct
        lda #$1E            ; HIRES, 50Hz
        sta $BFDF
        rts

; ---------------------------------------------------------------------------
; unpack: LZ decompress lz_src -> lz_dst
;   token 1..127: literal run; 128..255: copy (t&127)+3 bytes from
;   distance d (2 bytes) back; 0: end
_unpack:
        lda _lz_src
        sta zs
        lda _lz_src+1
        sta zs+1
        lda _lz_dst
        sta zd
        lda _lz_dst+1
        sta zd+1
@tok:   ldy #0
        lda (zs),y
        bne @go
        rts
@go:    inc zs
        bne @n0
        inc zs+1
@n0:    tax
        bmi @match
        ; literal run of X bytes
        stx tmp
@lit:   lda (zs),y
        sta (zd),y
        iny
        dex
        bne @lit
        lda tmp
        jsr adv_s
        lda tmp
        jsr adv_d
        jmp @tok
@match: and #$7F
        clc
        adc #3
        sta tmp
        lda zd              ; zt = zd - distance
        sec
        sbc (zs),y
        sta zt
        iny
        lda zd+1
        sbc (zs),y
        sta zt+1
        lda #2
        jsr adv_s
        ldy #0
        ldx tmp
@cp:    lda (zt),y
        sta (zd),y
        iny
        dex
        bne @cp
        lda tmp
        jsr adv_d
        jmp @tok

adv_s:  clc
        adc zs
        sta zs
        bcc @n
        inc zs+1
@n:     rts
adv_d:  clc
        adc zd
        sta zd
        bcc @n
        inc zd+1
@n:     rts

; ---------------------------------------------------------------------------
; pf_all: redraw the whole playfield from the cell map
_pf_all:
        lda #PF_C0
        sta _rc_c
        lda #PF_C1-PF_C0
        sta _rc_w
        lda #PF_TOP
        sta _rc_y
        lda #PF_BOT-PF_TOP
        sta _rc_h
        ; fall through

; pf_rect: redraw screen columns rc_c..+rc_w, rows rc_y..+rc_h (already
; clipped to the playfield) from the cell map
_pf_rect:
        ; the leftmost column only ever gets its paper attribute (never a
        ; pixel byte first, which would flash the line red for a moment)
        lda #0
        sta lff
        lda _rc_c
        cmp #PF_C0
        bne @nlf
        inc lff
        inc _rc_c
        dec _rc_w
@nlf:   ldx _rc_w
        dex
        stx rw1
        lda _rc_y
        sta ry
        clc
        adc _rc_h
        sta rend
        ; map row and sub-row of the first screen row
        lda _rc_y
        sec
        sbc #PF_TOP
        clc
        adc _cam_sub        ; 0..148
        tax
        lda div6tab,x
        clc
        adc _cam_cr
        sta rmr
        lda mod6tab,x
        sta rsub
@next:  lda ry
        cmp rend
        bcc @more
        rts
@more:  ; zmap = start of map row + cam_c + (rc_c - PF_C0)
        ldx rmr
        lda _rc_c
        sec
        sbc #PF_C0
        clc
        adc _cam_c
        clc
        adc MAPROWLO,x
        sta zmap
        lda MAPROWHI,x
        adc #0
        sta zmap+1
        lda rsub
        bne @line
        lda ry
        clc
        adc #6
        cmp rend
        beq @band
        bcs @line
@band:  jsr band6
        lda ry
        clc
        adc #6
        sta ry
        inc rmr
        jmp @next
@line:  jsr line1
        inc ry
        inc rsub
        lda rsub
        cmp #6
        bne @next
        lda #0
        sta rsub
        inc rmr
        jmp @next

; one full cell row: screen rows ry..ry+5
band6:
        ldx ry
        lda _rowlo,x
        clc
        adc _rc_c
        sta b0+1
        lda _rowhi,x
        adc #0
        sta b0+2
        lda _rowlo+1,x
        clc
        adc _rc_c
        sta b1+1
        lda _rowhi+1,x
        adc #0
        sta b1+2
        lda _rowlo+2,x
        clc
        adc _rc_c
        sta b2+1
        lda _rowhi+2,x
        adc #0
        sta b2+2
        lda _rowlo+3,x
        clc
        adc _rc_c
        sta b3+1
        lda _rowhi+3,x
        adc #0
        sta b3+2
        lda _rowlo+4,x
        clc
        adc _rc_c
        sta b4+1
        lda _rowhi+4,x
        adc #0
        sta b4+2
        lda _rowlo+5,x
        clc
        adc _rc_c
        sta b5+1
        lda _rowhi+5,x
        adc #0
        sta b5+2
        lda _rc_w
        beq bandlf
        ldy rw1
bandl:  lda (zmap),y
        tax
        lda PL0,x
b0:     sta $FFFF,y
        lda PL0+$100,x
b1:     sta $FFFF,y
        lda PL0+$200,x
b2:     sta $FFFF,y
        lda PL0+$300,x
b3:     sta $FFFF,y
        lda PL0+$400,x
b4:     sta $FFFF,y
        lda PL0+$500,x
b5:     sta $FFFF,y
        dey
        bpl bandl
bandlf: lda lff
        beq banddone
        ; leftmost column: the paper attribute for the cell there
        jsr lfcell
        jmp lf6
banddone:
        rts

; A = leftfix attribute of the map cell just left of zmap
lfcell: lda zmap
        sec
        sbc #1
        sta zt
        lda zmap+1
        sbc #0
        sta zt+1
        ldy #0
        lda (zt),y
        tax
        lda LEFTFIX,x
        rts

; store A down six rows, one column left of the address patched into b0
lf6:    ldy b0+1
        sty zt
        ldy b0+2
        sty zt+1
        ldy zt
        bne @nb
        dec zt+1
@nb:    dec zt
        ldy #0
        sta (zt),y
        ldy #40
        sta (zt),y
        ldy #80
        sta (zt),y
        ldy #120
        sta (zt),y
        ldy #160
        sta (zt),y
        ldy #200
        sta (zt),y
        rts

; one screen row ry, cell row rsub
line1:
        ldx ry
        lda _rowlo,x
        clc
        adc _rc_c
        sta ls+1
        lda _rowhi,x
        adc #0
        sta ls+2
        lda rsub
        clc
        adc #>PL0
        sta lp+2
        lda _rc_w
        beq linelf
        ldy rw1
linel:  lda (zmap),y
        tax
lp:     lda PL0,x
ls:     sta $FFFF,y
        dey
        bpl linel
linelf: lda lff
        beq linedone
        jsr lfcell
        ldx ls+1
        stx zt
        ldx ls+2
        stx zt+1
        ldy zt
        bne @nb
        dec zt+1
@nb:    dec zt
        ldy #0
        sta (zt),y
linedone:
        rts

div6tab:
        .repeat 160, I
        .byte I / 6
        .endrepeat
mod6tab:
        .repeat 160, I
        .byte I .MOD 6
        .endrepeat

; ---------------------------------------------------------------------------
; spr_draw: masked, clipped draw.  The C side has already clipped:
;   spr_desc  descriptor (h, w, h*w, 3 phase pointers)
;   spr_ph    phase 0..2
;   spr_sx    first screen column, spr_sy first screen row
;   spr_rows, spr_cols  visible size; spr_off = offset of the first visible
;   byte in the sprite data (skipped rows * w + skipped columns)
; Bytes on screen that are serial attributes are left alone, so sprites
; never break the paper colour of the void.
_spr_draw:
        lda _spr_desc
        sta zt
        lda _spr_desc+1
        sta zt+1
        ldy #1
        lda (zt),y
        sta wid
        lda _spr_ph
        asl a
        clc
        adc #3
        tay
        lda (zt),y
        clc
        adc _spr_off
        sta zs
        iny
        lda (zt),y
        adc #0
        sta zs+1
        ldy #2              ; mask = data + h*w
        lda (zt),y
        clc
        adc zs
        sta zm
        lda zs+1
        adc #0
        sta zm+1
        ; (h*w < 256 for every sprite - checked by mkgfx.py)
        ldx _spr_sy
        lda _rowlo,x
        clc
        adc _spr_sx
        sta zd
        lda _rowhi,x
        adc #0
        sta zd+1
        lda _spr_rows
        sta rows
        ldx _spr_cols
        dex
        stx tmp
@row:   ldy tmp
@b:     lda (zd),y
        cmp #$40
        bcc @skip           ; attribute: leave it
        and (zm),y
        ora (zs),y
        sta (zd),y
@skip:  dey
        bpl @b
        lda zs
        clc
        adc wid
        sta zs
        bcc @n2
        inc zs+1
@n2:    lda zm
        clc
        adc wid
        sta zm
        bcc @n3
        inc zm+1
@n3:    lda zd
        clc
        adc #40
        sta zd
        bcc @n4
        inc zd+1
@n4:    dec rows
        bne @row
        rts

; ---------------------------------------------------------------------------
; fill_rect: fill fr_w bytes x fr_h rows at byte column fr_col, row fr_y
_fill_rect:
        ldx _fr_y
        lda _fr_col
        clc
        adc _rowlo,x
        sta zd
        lda _rowhi,x
        adc #0
        sta zd+1
        ldx _fr_h
@r:     ldy _fr_w
        dey
        lda _fr_val
@b:     sta (zd),y
        dey
        bpl @b
        lda zd
        clc
        adc #40
        sta zd
        bcc @n
        inc zd+1
@n:     dex
        bne @r
        rts

; ---------------------------------------------------------------------------
; hchar: draw font glyph hc_ch at byte column hc_col, row hc_y (8 rows).
; hc_inv is ORed in: $80 = inverse video
_hchar:
        lda _hc_ch
        sec
        sbc #32
        sta zs
        lda #0
        asl zs
        rol a
        asl zs
        rol a
        asl zs
        rol a
        sta zs+1
        lda zs
        clc
        adc #<_font
        sta zs
        lda zs+1
        adc #>_font
        sta zs+1
        ldx _hc_y
        ldy #0
@r:     lda _rowlo,x
        clc
        adc _hc_col
        sta zd
        lda _rowhi,x
        adc #0
        sta zd+1
        lda (zs),y
        ora #$40
        ora _hc_inv
        sty tmp
        ldy #0
        sta (zd),y
        ldy tmp
        inx
        iny
        cpy #8
        bne @r
        rts

; ---------------------------------------------------------------------------
; unsigned char __fastcall__ tile_xy(unsigned int xy): A = world x, X = world y
; returns the deck tile there (0 = void off the 16 x 16 map)
_tile_xy:
        tay
        lda _d12,x
        cmp #16
        bcs @void
        asl a
        asl a
        asl a
        asl a
        sta tmp
        lda _d12,y
        cmp #16
        bcs @void
        ora tmp
        tax
        lda TILES,x
        ldx #0
        rts
@void:  lda #0
        tax
        rts

; ---------------------------------------------------------------------------
; put_sprite: draw spr_desc with its bottom centre at world (ps_x, ps_y),
; ps_z rows up, clipped to the playfield.  The screen rectangle it covered
; goes in o_c/o_w/o_y/o_h[n_n] so it can be restored next frame.
;   screen x = org_x + ps_x - ps_y - xoff
;   screen y = org_y + (ps_x + ps_y) / 2 - ps_z - h
_put_sprite:
        lda _spr_desc
        sta zt
        lda _spr_desc+1
        sta zt+1
        ldy #0
        lda (zt),y
        sta ph_h
        iny
        lda (zt),y
        sta wid
        ldy #7
        lda (zt),y
        sta ph_xo
        ; x
        lda _org_x
        clc
        adc _ps_x
        sta sxl
        lda _org_x+1
        adc #0
        sta sxh
        lda sxl
        sec
        sbc _ps_y
        sta sxl
        lda sxh
        sbc #0
        sta sxh
        lda sxl
        sec
        sbc ph_xo
        sta sxl
        lda sxh
        sbc #0
        sta sxh
        ; y
        lda _ps_x
        clc
        adc _ps_y
        ror a
        clc
        adc _org_y
        sta syl
        lda _org_y+1
        adc #0
        sta syh
        lda syl
        sec
        sbc _ps_z
        sta syl
        lda syh
        sbc #0
        sta syh
        lda syl
        sec
        sbc ph_h
        sta syl
        lda syh
        sbc #0
        sta syh
        ; vertical clip: t = sy - PF_TOP
        lda syl
        sec
        sbc #PF_TOP
        tax
        lda syh
        sbc #0
        bmi @above
        bne @ret
        cpx #PF_BOT-PF_TOP
        bcs @ret
        lda #0
        sta pskip
        lda syl
        sta prow0
        jmp @vdone
@ret:   rts
@above: cmp #$FF
        bne @ret
        txa
        beq @ret
        eor #$FF
        clc
        adc #1              ; skip = -t
        cmp ph_h
        bcs @ret
        sta pskip
        lda #PF_TOP
        sta prow0
@vdone: lda ph_h
        sec
        sbc pskip
        sta prows
        clc
        adc prow0
        cmp #PF_BOT+1
        bcc @vok
        lda #PF_BOT
        sec
        sbc prow0
        sta prows
@vok:   lda prow0           ; hidden behind something in front?
        cmp _spr_clip
        bcs @ret3
        clc
        adc prows
        cmp _spr_clip
        bcc @vok2
        lda _spr_clip
        sec
        sbc prow0
        sta prows
@vok2:   ; horizontal: v = sx + 60, column = v / 6 - 10
        lda sxl
        clc
        adc #60
        sta vl
        lda sxh
        adc #0
        sta vh
        bmi @ret
        ldx #0
@div:   lda vh
        bne @sub
        lda vl
        cmp #48
        bcc @divd
@sub:   lda vl
        sec
        sbc #48
        sta vl
        lda vh
        sbc #0
        sta vh
        txa
        clc
        adc #8
        tax
        jmp @div
@divd:  ldy vl
        txa
        clc
        adc div6tab,y
        sec
        sbc #10
        sta pcol
        lda mod6tab,y
        cmp #3
        lda #0
        rol a
        sta _spr_ph
        lda pcol
        clc
        adc wid
        bmi @ret2
        cmp #PF_C0+1
        bcc @ret2
        lda pcol
        bmi @lclip
        cmp #PF_C1
        bcs @ret2
        cmp #PF_C0
        bcs @nolc
@lclip: lda #PF_C0
        sec
        sbc pcol
        sta plsk
        lda #PF_C0
        sta pcol
        jmp @hc
@ret2:  rts
@ret3:  rts
@nolc:  lda #0
        sta plsk
@hc:    lda wid
        sec
        sbc plsk
        sta pcols
        clc
        adc pcol
        cmp #PF_C1+1
        bcc @hok
        lda #PF_C1
        sec
        sbc pcol
        sta pcols
@hok:   lda plsk
        ldx pskip
        beq @o2
@o1:    clc
        adc wid
        dex
        bne @o1
@o2:    sta _spr_off
        lda pcol
        sta _spr_sx
        lda prow0
        sta _spr_sy
        lda prows
        sta _spr_rows
        lda pcols
        sta _spr_cols
        jsr _spr_draw
        ldx _n_n
        lda pcol
        sta _o_c,x
        lda pcols
        sta _o_w,x
        lda prow0
        sta _o_y,x
        lda prows
        sta _o_h,x
        inc _n_n
        rts
