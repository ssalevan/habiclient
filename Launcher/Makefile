.PHONY: clean

all: launcher.s launcher.prg habitat.prg Habitat-A.d64

launcher.s: launcher.c
	cc65 -t c64 launcher.c

launcher.prg: launcher.s
	cl65 -v -o launcher.prg -C c64.cfg -m launcher.map launcher.s

habitat.prg: launcher.s
	64tass -o habitat.prg main.asm

Habitat-A.d64: habitat.prg
	cc1541 -f habitat -w habitat.prg Habitat-A.d64
	cc1541 -f ser-swlink -w c64-swlink.ser Habitat-A.d64
	cc1541 -f ser-up2400 -w c64-up2400.ser Habitat-A.d64
	cp Habitat-A.d64 ../Dist

clean:
	rm -f habitat.prg launcher.prg launcher.s
