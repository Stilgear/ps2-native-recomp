#pragma once
// Minimal X11 ABI definitions for SDL_syswm.h on SteamOS where /usr/include/X11 is stripped from the base image.
typedef struct _XDisplay Display;
typedef unsigned long XID;
typedef XID Window;
typedef unsigned long Atom;
typedef union _XEvent {
    int type;
    long pad[24];
} XEvent;
