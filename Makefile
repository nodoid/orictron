# Quazatron for the Oric Atmos - build with cc65 (brew install cc65)
CL65    = cl65
TARGET  = atmos
BUILD   = build
TAP     = $(BUILD)/quazatron.tap
CFLAGS  = -Or -Cl -g
# src/quazatron.cfg: program below $7800 ($7800-$97FF = background buffer),
# big arrays in HIBSS at $9C00, autorun tape.
CFG     = src/quazatron.cfg

SRCS = src/main.c src/oric.s $(BUILD)/gfxdata.s

all: $(TAP)

$(BUILD)/gfxdata.s: tools/mkgfx.py tools/deckgen.py tools/oricenc.py | $(BUILD)
	python3 tools/mkgfx.py $@

$(TAP): $(SRCS) src/hw.h $(CFG) Makefile | $(BUILD)
	$(CL65) -t $(TARGET) -C $(CFG) $(CFLAGS) -m $(BUILD)/quazatron.map -Ln $(BUILD)/quazatron.lbl -o $@ $(SRCS)

$(BUILD):
	mkdir -p $(BUILD)

run: $(TAP)
	open -a "$(HOME)/Downloads/Oric v1.8.3/Oric.app" $(TAP)

clean:
	rm -rf $(BUILD) src/*.o

.PHONY: all run clean
