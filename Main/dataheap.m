	include	"ronmacros2.m"

; ----------------------------------------------------------------------
; Heap storage
; ----------------------------------------------------------------------
object_table_hi::	block	256
object_table_lo::	block	256

sound_table_hi::	block	256
sound_table_lo::	block	256

image_table_hi::	block	256
image_table_lo::	block	256

action_table_hi::	block	256
action_table_lo::	block	256

class_table_ref::	block	256
sound_table_ref::	block	256
image_table_ref::	block	256
action_table_ref::	block	256

end_of_tables::				; end of dataheap tables
static_end_of_heap::			; heap starts here (sfx relocated to $4800)

