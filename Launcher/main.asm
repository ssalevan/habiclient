;--------------------------------------------------------
*=$0801 ; start of BASIC
        .word (+), 2005  ;pointer, line number
        .null $9e, format("%d", start);will be sys 4096
+	.word 0          ;basic line end

;--------------------------------------------------------
*=$080E
.binary "mcmg.exo", 15 ; skip exomizer header

*=$5F00
.binary "raster.prg", 2 ; skip 2-byte prg header

*=$6000
start .binary "launcher.prg", 2 ; skip 2-byte prg header

*=$8800
.binary "title_screen8800.prg", 2 ; skip 2-byte prg header

*=$8C00
.binary "title_colorD800.prg", 2 ; skip 2-byte prg header

*=$A000
.binary "title_bitmapA000.prg", 2 ; skip 2-byte prg header
