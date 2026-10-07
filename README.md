# Quazatron — Oric Atmos port

An Oric Atmos version of Graftgold's 1986 ZX Spectrum game *Quazatron*,
built to look and play as much like the Spectrum original as the Oric
allows. It is a ground-up reimplementation with new code (C + 6502 assembly
via cc65) and new graphics. None of the original Z80 code or Spectrum assets
are used.

What matches the Spectrum:

- **The deck:** a smooth-scrolling isometric deck seen through a red-bordered
  window. It has raised walkways with black riveted step faces, tall panelled
  or brick walls, dithered checker floors, ⤢ step pads, energiser pads, lift
  hatches and consoles. The deck edge hangs over a blue void.
- **Deck colours:** one ink per deck (white, cyan, blue, green, magenta,
  yellow) on black, as on the Spectrum. The blue deck sits over a black void.
- **Droids:** white cylinders with a floating striped lid and their class code
  on the body (M1, S2, W3, G4, B5, R6, B7, X9). Other droids pass behind
  walls and raised walkways. Your own droid is always drawn in full.
- **Status panel:** the red panel with three capsules. The yellow field shows
  the status word (MOBILE, GRAPPLE, TIME nn, COMPLETE, FAILED…) with an energy
  bar under it. The magenta and green boxes show the deck number and droids
  left. The white box shows your unit code and the cyan field the score.
- **Transfer battle:** your side is yellow (left) and the droid's is blue
  (right). 13 black wires feed a column of cells under a block that shows
  who is ahead. Pulses travel as arrowheads that leave dashed powered wire
  behind them. Some wires are dead ends and some are joined.
- **Text screens:** blue framed screens with the ORICTRON logo. They cover
  the title, "UNIT.. B5 BATTLE ROBOT / PREPARE TO ENGAGE / SECURITY DEVICE",
  "SECURITY CLASS …" and game over.

**Binary:** `build/quazatron.tap`. Load it in an Oric Atmos emulator, or on
real hardware with `CLOAD""`. It autoruns.

## Playing

You are an influence device on a ship overrun by rogue droids. Clear all six
decks.

| Key | Action |
| --- | --- |
| Arrows or Q A O P | Move (screen-relative) |
| SPACE | Fire |
| Hold SPACE (standing still) | GRAPPLE, as on the Spectrum: then run into a droid to start a transfer battle |
| T or RETURN | Grapple a droid you're touching straight away |
| L (on the lift hatch) | Ride the lift to the next deck |
| ESC | Abandon the game |

- **Levels:** you can only step up or down one level from a ⤢ pad.
- **Droids:** higher classes are faster, tougher and hit harder. You can ram
  them, shoot them or take them over.
- **Transfer:** use UP/DOWN to pick a wire and SPACE to fire a pulse down it.
  A pulse that reaches the centre turns its cell yellow for a few seconds.
  Hold more cells than the droid when TIME runs out and you take over its
  body. If you lose while hosting a droid, you lose that host. If you lose as
  the influence device, you lose half your energy.
- **Host burnout:** a captured host slowly loses energy. If it is destroyed,
  you're ejected as the influence device. If that is destroyed, the game is
  over.
- **Energiser** pads recharge you.
- **Demo:** leave the title screen idle and a demo plays itself.

## Building

```sh
brew install cc65
make            # -> build/quazatron.tap
make run        # opens it in ~/Downloads/Oric v1.8.3/Oric.app
```

Oric.app only autoloads a tape while BASIC is idle. If a game is already
running, use File > Reset first.

## How it works

| File | Contents |
| --- | --- |
| `src/main.c` | Game logic: decks, droids, combat, camera, transfer battle, text screens, demo autopilot |
| `src/oric.s` | Hardware layer, never calls the ROM: keyboard, AY sound, frame pacing, LZ unpacker, playfield renderer, clipped masked sprite blitter, sprite projection |
| `tools/deckgen.py` | Lays out each deck as a 16×16 isometric tile grid with height levels, renders it Spectrum-style, and cuts the picture into cells |
| `tools/mkgfx.py` | Generates `build/gfxdata.s`: font, droid sprites, compressed decks and charsets, status panel, framed screen, logo |
| `tools/oricenc.py` | Oric HIRES encoder/decoder (attribute-aware), LZ compressor, PNG writer |
| `tools/harness.py` | Headless test rig: py65 6502 + VIA (T1/T2)/AY/keyboard model, renders the screen to PNG, scripted keys, memory pokes and watches by symbol, PC profiler |
| `tools/oricdemo.py` | Plays `demo/demo_script.txt` on the Oric in the harness and records it to MP4 |
| `tools/mkdemovideo.py` | Builds the side-by-side Spectrum vs Oric demo video with step captions |
| `tools/scr2png.py` | Converts Spectrum screen dumps to PNG (used when working out the demo script) |
| `tools/oricvideo.py`, `mkvideo*.py`, `retime.py` | Video tools from the previous version |

### Scrolling

Each deck is pre-rendered by `deckgen.py` into a map of cells. A cell is one
screen byte (6 pixels) wide and 6 rows tall. The bytes come from a planar
charset of at most 256 cells per style, with one page per cell row. The
renderer copies a whole cell row at a time with self-modified store
addresses, so a full 37×144-byte playfield redraw takes about 60 ms. The
camera moves in 6-pixel / 3-row steps.

### Colour

Colour uses serial attributes. Every playfield line starts with paper red
(the border) and then the deck's ink. Void cells carry their own paper
attributes, so the blue void shows its comb fringe in deck ink. The renderer
patches the leftmost visible column so the paper is right however the view
is scrolled. The sprite blitter never overwrites an attribute byte.

### Sprites

Sprites are pre-shifted into 2 phases (0 and 3 pixels). They are drawn in
order of their bottom screen row and clipped to the window. Each sprite
except the player's is also clipped at the top edge of any taller tile in
front of it. Erasing a sprite re-renders the cells underneath it, so no
background copy is needed. When the view scrolls, the playfield is redrawn
top to bottom and each sprite goes back as soon as the rows under it are
done, so sprites don't flicker out.

### Pacing

VIA timer 2 is a stopwatch that caps the game at 25 fps without wasting time
on slow frames. The game runs at about 19 fps standing still and 10–17 fps
while scrolling.

Memory map (`src/quazatron.cfg`):

| Range | Use |
| --- | --- |
| `$0200-$02FF`, `$0400-$04FF` | Tables in unused ROM workspace |
| `$0501-$867F` | Program, data and C stack |
| `$8680-$89FF` | `HIBSS`: game tables |
| `$8A00-$8FFF` | Planar cell charset of the current deck style (6 pages) |
| `$9000-$9EFF` | Current deck: leftfix table, header, tiles, cell map |
| `$9F00-$9F7F` | Cell map row addresses |
| `$A000-$BF3F` | HIRES screen |

## Demo script and video

`demo/demo_script.txt` is a timed list of steps taken from a real player's
session on the Spectrum original (the archive.org RZX recording):

1. title and start;
2. exploring the deck;
3. grappling and a transfer battle, three times;
4. shooting droids;
5. lift rides between decks.

`demo/spectrum_keys.txt` holds that player's actual key presses.

The Oric plays the same script:

- EXPLORE steps replay the Spectrum keys.
- The decks differ between the machines, so `oricdemo.py` steers the Oric
  droid to carry out HUNT, GRAPPLE and LIFT steps on its own deck.
- The game's own transfer AI plays the battles.

The Spectrum side is the recording itself, replayed in a patched Fuse.
Replaying the extracted keys into Fuse drifts within seconds: the game polls
the keyboard in timing-dependent loops and the recording came from an
emulator with slightly different timing.

```sh
python3 tools/oricdemo.py build/quazatron.tap oric_demo.mp4
python3 tools/mkdemovideo.py spectrum_demo.mp4 oric_demo.mp4 out.mp4
```

## Previous version

The first version of this port was a flip-screen, room-based remake with its
own colour scheme. Its source is kept in `backup_v1/`. The videos in `movie/`
were recorded from that version and don't show the current game.

## Licence

The code and tools in this repository are released under the GNU General
Public License, version 2 - see `LICENSE`.  Quazatron itself is (c) 1986
Graftgold / Hewson Consultants; this port contains none of its code or
graphics.
