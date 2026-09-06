"""Fast Win32 positioning and repaint helpers for Tk top-level windows."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
from functools import lru_cache


SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOSENDCHANGING = 0x0400
SWP_DEFERERASE = 0x2000

RDW_INVALIDATE = 0x0001
RDW_ERASE = 0x0004
RDW_ALLCHILDREN = 0x0080
RDW_UPDATENOW = 0x0100

MOVE_WINDOW_FLAGS = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
RESIZE_WINDOW_FLAGS = (
    SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOSENDCHANGING | SWP_DEFERERASE
)
REDRAW_WINDOW_FLAGS = RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN


@lru_cache(maxsize=1)
def _load_user32():
    if not hasattr(ctypes, "WinDLL"):
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except OSError:
        return None

    user32.GetParent.argtypes = (wintypes.HWND,)
    user32.GetParent.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = (
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    )
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.RedrawWindow.argtypes = (
        wintypes.HWND,
        ctypes.c_void_p,
        wintypes.HRGN,
        wintypes.UINT,
    )
    user32.RedrawWindow.restype = wintypes.BOOL
    return user32


def _toplevel_handle(user32, tk_window_id: int) -> int:
    parent = user32.GetParent(tk_window_id)
    return int(parent) if parent else tk_window_id


def set_window_position(tk_window_id: int, x: int, y: int) -> bool:
    """Move a Tk top-level through Win32 without asking Tk to relayout it."""
    user32 = _load_user32()
    if user32 is None:
        return False
    hwnd = _toplevel_handle(user32, tk_window_id)
    return bool(
        user32.SetWindowPos(
            hwnd,
            None,
            x,
            y,
            0,
            0,
            MOVE_WINDOW_FLAGS,
        )
    )


def set_window_bounds(
    tk_window_id: int,
    x: int,
    y: int,
    width: int,
    height: int,
) -> bool:
    """Resize a Tk top-level, leaving normal damage painting to Tk/Windows."""
    if width <= 0 or height <= 0:
        return False
    user32 = _load_user32()
    if user32 is None:
        return False
    hwnd = _toplevel_handle(user32, tk_window_id)
    return bool(
        user32.SetWindowPos(
            hwnd,
            None,
            x,
            y,
            width,
            height,
            RESIZE_WINDOW_FLAGS,
        )
    )


def redraw_window(tk_window_id: int, *, immediate: bool = False) -> bool:
    """Invalidate the full Tk top-level, optionally painting before returning."""
    user32 = _load_user32()
    if user32 is None:
        return False
    hwnd = _toplevel_handle(user32, tk_window_id)
    flags = REDRAW_WINDOW_FLAGS | (RDW_UPDATENOW if immediate else 0)
    return bool(user32.RedrawWindow(hwnd, None, None, flags))
