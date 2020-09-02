#ifndef _GLOBAL
#define _GLOBAL

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <assert.h>

#ifndef TRUE
#define TRUE 1
#endif

#ifndef FALSE
#define FALSE 0
#endif

/* Application parameters. */
#ifndef TITLE
#define TITLE           "TaskID"
#endif

#ifndef VERSION
#define VERSION         "1.0"
#endif

#ifndef bool
#define bool BOOL
#endif

#ifndef inline
#define inline _inline
#endif

#define SYS_OK          0
#define SYS_ERROR       1

#define MAX_LINE_LEN    1024

#endif /* _GLOBAL */
