.PHONY: behaviors clean charset disks diska diskb jmuddle muddle tools cart

all: diska diskb

clean:
	rm -rf *.out *.prg dist/*
	rm -f Actions/*.bin
	rm -f Images/Heads/*.bin
	rm -f Images/Props/*.bin
	$(MAKE) -C Behaviors clean
	$(MAKE) -C Launcher clean
	$(MAKE) -C Main clean
	$(MAKE) -C Sounds clean
	$(MAKE) -C Tools/a65toprg clean
	$(MAKE) -C Tools/filldisk clean
	$(MAKE) -C Tools/habdiska clean
	$(MAKE) -C Tools/macross clean
	$(MAKE) -C Tools/mcmgtrim clean
	$(MAKE) -C Tools/mtobin clean
	$(MAKE) -C Tools/muddle clean
	$(MAKE) -C Tools/slinky clean

tools:
	$(MAKE) -C Tools/a65toprg
	$(MAKE) -C Tools/filldisk
	$(MAKE) -C Tools/habdiska
	$(MAKE) -C Tools/macross macross
	$(MAKE) -C Tools/mcmgtrim
	$(MAKE) -C Tools/mtobin
	$(MAKE) -C Tools/muddle all
	$(MAKE) -C Tools/slinky

behaviors: tools
	$(MAKE) -C Behaviors

images: tools
	$(MAKE) -C Images/Heads props
	$(MAKE) -C Images/Props props

sounds: tools
	$(MAKE) -C Sounds sounds

main: tools
	$(MAKE) -C Main

mkdist:
	mkdir -p Dist

diska: mkdist launcher

launcher: main
	$(MAKE) -C Launcher

jmuddle: tools
	echo jmuddle: beta.mud
	./Tools/muddle/jmuddle < beta.mud > beta.jlist || true

muddle: tools
	echo muddle: beta.mud
	./Tools/muddle/muddle < beta.mud > beta.list || true

charset: tools
	echo making on_disk_charset.bin
	./Tools/macross/macross -c -p -o on_disk_charset.obj on_disk_charset.m
	./Tools/mtobin/mtobin on_disk_charset.obj on_disk_charset.dat

cart: diska diskb
	python3 build_crt.py Launcher/habitat.prg mcmg.prg Dist/Habitat-B.d64 Dist/Habitat.crt
	rm -rf Dist/Habitat-U64
	mkdir -p Dist/Habitat-U64
	cp Dist/Habitat.crt Dist/Habitat-U64/Habitat.crt
	cp Dist/habitat-u64.cfg Dist/Habitat-U64/habitat-u64.cfg
	cp Dist/README.txt Dist/Habitat-U64/README.txt
	cd Dist && zip -r Habitat-U64.zip Habitat-U64/

diskb: mkdist behaviors images sounds muddle jmuddle charset
	dd if=image.dat of=image1.dat bs=30720 count=1        # block size 30720 == 0x7800
	dd if=image.dat of=image2.dat bs=30720 count=1 skip=1 # add conv=sync if padding with zeros needed
	dd if=head.dat of=head1.dat bs=30720 count=1
	dd if=head.dat of=head2.dat bs=30720 count=1 skip=1
	./Tools/filldisk/filldisk class_equates.m Dist/Habitat-B.d64
