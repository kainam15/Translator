"""Dependency-free Windows notification-area icon for Translator."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import queue
import threading


WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_NULL = 0x0000
WM_USER = 0x0400
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_TRAYICON = WM_USER + 1

NIM_ADD = 0x00000000
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

IDI_APPLICATION = 32512
TRAY_ICON_ID = 1
MENU_SHOW = 1001
MENU_SETTINGS = 1002
MENU_EXIT = 1003

LRESULT = ctypes.c_ssize_t
UINT_PTR = ctypes.c_size_t
WINFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
WNDPROC = WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


def menu_action_for_command(command: int) -> str | None:
    return {
        MENU_SHOW: "show",
        MENU_SETTINGS: "settings",
        MENU_EXIT: "exit",
    }.get(command)


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
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


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


class _TimeoutOrVersion(ctypes.Union):
    _fields_ = [("uTimeout", wintypes.UINT), ("uVersion", wintypes.UINT)]


class NOTIFYICONDATAW(ctypes.Structure):
    _anonymous_ = ("timeout_or_version",)
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("timeout_or_version", _TimeoutOrVersion),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class NOTIFYICONIDENTIFIER(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("guidItem", GUID),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def running_tray_icon_rect() -> tuple[int, int, int, int] | None:
    """Return the live Translator tray icon rectangle for diagnostics."""
    if not hasattr(ctypes, "WinDLL"):
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    user32.FindWindowW.restype = wintypes.HWND
    shell32.Shell_NotifyIconGetRect.argtypes = (
        ctypes.POINTER(NOTIFYICONIDENTIFIER),
        ctypes.POINTER(RECT),
    )
    shell32.Shell_NotifyIconGetRect.restype = ctypes.c_long

    hwnd = user32.FindWindowW(None, "TranslatorLite.Tray")
    if not hwnd:
        return None
    identifier = NOTIFYICONIDENTIFIER(
        cbSize=ctypes.sizeof(NOTIFYICONIDENTIFIER),
        hWnd=hwnd,
        uID=TRAY_ICON_ID,
    )
    rect = RECT()
    result = int(shell32.Shell_NotifyIconGetRect(ctypes.byref(identifier), ctypes.byref(rect)))
    if ctypes.c_long(result).value < 0:
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


class SystemTray:
    """Own a Shell_NotifyIcon icon on a dedicated Win32 message-loop thread."""

    def __init__(self, events: queue.Queue[str]) -> None:
        self.events = events
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._hwnd: int | None = None
        self._error: str | None = None
        self._icon_added = False
        self._wndproc_callback: WNDPROC | None = None
        self._class_name = f"TranslatorLiteTray.{os.getpid()}.{id(self)}"
        self._hinstance: int | None = None
        self._nid: NOTIFYICONDATAW | None = None
        self._taskbar_created = 0

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._icon_added)

    def start(self, timeout: float = 2.0) -> tuple[bool, str | None]:
        if self.is_running:
            return True, None
        if not hasattr(ctypes, "WinDLL"):
            return False, "系统托盘仅支持 Windows"

        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._message_loop,
            daemon=True,
            name="TranslatorSystemTray",
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            return False, "创建系统托盘图标超时"
        return self.is_running, self._error

    def stop(self) -> None:
        thread = self._thread
        hwnd = self._hwnd
        if thread and thread.is_alive() and hwnd and hasattr(ctypes, "WinDLL"):
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostMessageW.argtypes = (
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            user32.PostMessageW.restype = wintypes.BOOL
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            thread.join(timeout=2.0)
        self._thread = None
        self._hwnd = None
        self._icon_added = False

    def _configure_apis(self) -> tuple[ctypes.WinDLL, ctypes.WinDLL, ctypes.WinDLL]:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
        user32.RegisterClassW.restype = wintypes.WORD
        user32.CreateWindowExW.argtypes = (
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        )
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = (
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.DefWindowProcW.restype = LRESULT
        user32.DestroyWindow.argtypes = (wintypes.HWND,)
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.LoadIconW.argtypes = (wintypes.HINSTANCE, ctypes.c_void_p)
        user32.LoadIconW.restype = wintypes.HICON
        user32.GetMessageW.argtypes = (
            ctypes.POINTER(MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        )
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
        user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)
        user32.PostQuitMessage.argtypes = (ctypes.c_int,)
        user32.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
        user32.RegisterWindowMessageW.restype = wintypes.UINT
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        shell32.Shell_NotifyIconW.argtypes = (
            wintypes.DWORD,
            ctypes.POINTER(NOTIFYICONDATAW),
        )
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL
        return user32, shell32, kernel32

    def _message_loop(self) -> None:
        user32: ctypes.WinDLL | None = None
        shell32: ctypes.WinDLL | None = None
        try:
            user32, shell32, kernel32 = self._configure_apis()
            self._hinstance = kernel32.GetModuleHandleW(None)
            self._wndproc_callback = WNDPROC(self._wndproc)
            window_class = WNDCLASSW(
                lpfnWndProc=self._wndproc_callback,
                hInstance=self._hinstance,
                lpszClassName=self._class_name,
            )
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())

            self._hwnd = user32.CreateWindowExW(
                0,
                self._class_name,
                "TranslatorLite.Tray",
                0,
                0,
                0,
                0,
                0,
                None,
                None,
                self._hinstance,
                None,
            )
            if not self._hwnd:
                raise ctypes.WinError(ctypes.get_last_error())

            self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
            if not self._add_icon(user32, shell32):
                raise ctypes.WinError(ctypes.get_last_error())

            self._ready.set()
            message = MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self._error = f"无法创建系统托盘: {exc}"
            self._ready.set()
        finally:
            if shell32 is not None:
                self._remove_icon(shell32)
            if user32 is not None and self._hwnd:
                user32.DestroyWindow(self._hwnd)
            if user32 is not None and self._hinstance:
                user32.UnregisterClassW(self._class_name, self._hinstance)
            self._hwnd = None
            self._icon_added = False

    def _add_icon(self, user32: ctypes.WinDLL, shell32: ctypes.WinDLL) -> bool:
        if not self._hwnd:
            return False
        icon = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        self._nid = NOTIFYICONDATAW(
            cbSize=ctypes.sizeof(NOTIFYICONDATAW),
            hWnd=self._hwnd,
            uID=TRAY_ICON_ID,
            uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP,
            uCallbackMessage=WM_TRAYICON,
            hIcon=icon,
            szTip="Translator · 划词翻译",
        )
        self._icon_added = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._nid)))
        return self._icon_added

    def _remove_icon(self, shell32: ctypes.WinDLL) -> None:
        if self._icon_added and self._nid is not None:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        self._icon_added = False

    def _wndproc(
        self, hwnd: int, message: int, w_param: int, l_param: int
    ) -> int:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if message == self._taskbar_created and self._taskbar_created:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            self._icon_added = False
            self._add_icon(user32, shell32)
            return 0
        if message == WM_TRAYICON:
            mouse_message = int(l_param) & 0xFFFF
            if mouse_message in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self.events.put("show")
            elif mouse_message in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._show_context_menu(hwnd)
            return 0
        if message == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            self._remove_icon(shell32)
            self._hwnd = None
            user32.PostQuitMessage(0)
            return 0
        user32.DefWindowProcW.argtypes = (
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.DefWindowProcW.restype = LRESULT
        return int(user32.DefWindowProcW(hwnd, message, w_param, l_param))

    def _show_context_menu(self, hwnd: int) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = (
            wintypes.HMENU,
            wintypes.UINT,
            UINT_PTR,
            wintypes.LPCWSTR,
        )
        user32.TrackPopupMenu.argtypes = (
            wintypes.HMENU,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.LPVOID,
        )
        user32.TrackPopupMenu.restype = wintypes.UINT
        user32.DestroyMenu.argtypes = (wintypes.HMENU,)

        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            user32.AppendMenuW(menu, MF_STRING, MENU_SHOW, "打开翻译器")
            user32.AppendMenuW(menu, MF_STRING, MENU_SETTINGS, "热键设置…")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_EXIT, "退出")
            point = POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetForegroundWindow(hwnd)
            command = int(
                user32.TrackPopupMenu(
                    menu,
                    TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                    point.x,
                    point.y,
                    0,
                    hwnd,
                    None,
                )
            )
            action = menu_action_for_command(command)
            if action:
                self.events.put(action)
            user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)
