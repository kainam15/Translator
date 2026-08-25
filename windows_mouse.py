"""Publish global Windows mouse clicks for click-outside dismissal."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import queue
import threading


WH_MOUSE_LL = 14
WM_QUIT = 0x0012
WM_LBUTTONDOWN = 0x0201
WM_RBUTTONDOWN = 0x0204
WM_MBUTTONDOWN = 0x0207
WM_XBUTTONDOWN = 0x020B
MOUSE_BUTTON_DOWN_MESSAGES = frozenset(
    (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN, WM_XBUTTONDOWN)
)

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
        ("lPrivate", wintypes.DWORD),
    ]


LOW_LEVEL_MOUSE_PROC = WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


def is_mouse_button_down_message(message: int) -> bool:
    return int(message) in MOUSE_BUTTON_DOWN_MESSAGES


def window_at_point_is_current_process(x: int, y: int) -> bool | None:
    """Return whether the window under a screen point belongs to this process."""
    if not hasattr(ctypes, "WinDLL"):
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.WindowFromPoint.argtypes = (POINT,)
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        )
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        target_window = user32.WindowFromPoint(POINT(x, y))
        if not target_window:
            return None
        process_id = wintypes.DWORD()
        if not user32.GetWindowThreadProcessId(
            target_window, ctypes.byref(process_id)
        ):
            return None
        return process_id.value == os.getpid()
    except (AttributeError, OSError):
        return None


class GlobalMouseClick:
    """Install a low-level mouse hook and publish button-down coordinates."""

    def __init__(self, events: queue.Queue[tuple[int, int]]) -> None:
        self.events = events
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._hook: int | None = None
        self._callback: object | None = None
        self._user32: object | None = None
        self._error: str | None = None

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._hook)

    def start(self, timeout: float = 2.0) -> tuple[bool, str | None]:
        self.stop()
        if not hasattr(ctypes, "WinDLL"):
            return False, "全局鼠标监听仅支持 Windows"

        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._message_loop,
            daemon=True,
            name="TranslatorGlobalMouseClick",
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            return False, "启动全局鼠标监听超时"
        return self.is_running, self._error

    def stop(self) -> None:
        thread = self._thread
        thread_id = self._thread_id
        if thread and thread.is_alive() and thread_id and hasattr(ctypes, "WinDLL"):
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostThreadMessageW.argtypes = (
                wintypes.DWORD,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            user32.PostThreadMessageW.restype = wintypes.BOOL
            user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = None
        self._hook = None
        self._callback = None
        self._user32 = None

    def _message_loop(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentThreadId.argtypes = ()
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        user32.SetWindowsHookExW.argtypes = (
            ctypes.c_int,
            LOW_LEVEL_MOUSE_PROC,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        )
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.CallNextHookEx.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = (wintypes.HANDLE,)
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = (
            ctypes.POINTER(MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        )
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)
        user32.DispatchMessageW.restype = LRESULT

        self._thread_id = int(kernel32.GetCurrentThreadId())
        self._user32 = user32
        self._callback = LOW_LEVEL_MOUSE_PROC(self._hook_proc)
        self._hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self._callback,
            kernel32.GetModuleHandleW(None),
            0,
        )
        if not self._hook:
            self._error = f"无法监听鼠标点击（Windows error {ctypes.get_last_error()}）"
            self._ready.set()
            return

        self._ready.set()
        message = MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def _hook_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0 and is_mouse_button_down_message(w_param):
            event = ctypes.cast(
                l_param, ctypes.POINTER(MSLLHOOKSTRUCT)
            ).contents
            self.events.put((int(event.pt.x), int(event.pt.y)))

        user32 = self._user32
        if user32 is None:
            return 0
        return int(user32.CallNextHookEx(self._hook, n_code, w_param, l_param))
