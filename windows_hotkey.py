"""Small Windows-only global-hotkey and selection-copy helpers."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import queue
import threading
from dataclasses import dataclass
from typing import Any


WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 0x5452

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

MODIFIER_ORDER = ("Ctrl", "Alt", "Shift")
MODIFIER_VALUES = {"Ctrl": MOD_CONTROL, "Alt": MOD_ALT, "Shift": MOD_SHIFT}


def _virtual_key(key: str) -> int:
    normalized = key.upper()
    if len(normalized) == 1 and normalized.isascii() and normalized.isalnum():
        return ord(normalized)
    if normalized.startswith("F") and normalized[1:].isdigit():
        number = int(normalized[1:])
        if 1 <= number <= 12:
            return 0x70 + number - 1
    raise ValueError("快捷键仅支持 A-Z、0-9 或 F1-F12")


@dataclass(frozen=True)
class HotkeySpec:
    modifiers: tuple[str, ...]
    key: str

    def __post_init__(self) -> None:
        normalized_modifiers = tuple(
            modifier for modifier in MODIFIER_ORDER if modifier in set(self.modifiers)
        )
        normalized_key = self.key.upper()
        _virtual_key(normalized_key)
        if not normalized_modifiers and not normalized_key.startswith("F"):
            raise ValueError("字母或数字快捷键至少需要 Ctrl、Alt 或 Shift")
        object.__setattr__(self, "modifiers", normalized_modifiers)
        object.__setattr__(self, "key", normalized_key)

    @property
    def display(self) -> str:
        return "+".join((*self.modifiers, self.key))

    def registration_values(self) -> tuple[int, int]:
        modifier_value = MOD_NOREPEAT
        for modifier in self.modifiers:
            modifier_value |= MODIFIER_VALUES[modifier]
        return modifier_value, _virtual_key(self.key)

    def to_dict(self) -> dict[str, Any]:
        return {"modifiers": list(self.modifiers), "key": self.key}

    @classmethod
    def from_dict(cls, value: object) -> "HotkeySpec":
        if not isinstance(value, dict):
            raise ValueError("hotkey 配置必须是 object")
        modifiers = value.get("modifiers")
        key = value.get("key")
        if not isinstance(modifiers, list) or not all(
            isinstance(item, str) for item in modifiers
        ):
            raise ValueError("hotkey.modifiers 格式无效")
        if not isinstance(key, str):
            raise ValueError("hotkey.key 格式无效")
        unknown = set(modifiers) - set(MODIFIER_ORDER)
        if unknown:
            raise ValueError(f"未知修饰键: {', '.join(sorted(unknown))}")
        return cls(tuple(modifiers), key)


DEFAULT_HOTKEY = HotkeySpec(("Alt",), "W")


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


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


ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else wintypes.DWORD


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    # INPUT's ABI size is determined by its largest union member (MOUSEINPUT).
    # Omitting it makes INPUT 32 bytes instead of 40 on 64-bit Windows, causing
    # SendInput to fail with ERROR_INVALID_PARAMETER.
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class GlobalHotkey:
    """Register one global hotkey and publish invocations to a queue."""

    def __init__(self, events: queue.Queue[str]) -> None:
        self.events = events
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._registered = False
        self._error: str | None = None

    def start(self, spec: HotkeySpec, timeout: float = 2.0) -> tuple[bool, str | None]:
        self.stop()
        if not hasattr(ctypes, "WinDLL"):
            return False, "全局快捷键仅支持 Windows"

        self._ready.clear()
        self._registered = False
        self._error = None
        self._thread = threading.Thread(
            target=self._message_loop,
            args=(spec,),
            daemon=True,
            name="TranslatorGlobalHotkey",
        )
        self._thread.start()
        if not self._ready.wait(timeout):
            return False, "注册快捷键超时"
        return self._registered, self._error

    def stop(self) -> None:
        thread = self._thread
        thread_id = self._thread_id
        if thread and thread.is_alive() and thread_id and hasattr(ctypes, "WinDLL"):
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
            thread.join(timeout=1.0)
        self._thread = None
        self._thread_id = None
        self._registered = False

    def _message_loop(self, spec: HotkeySpec) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._thread_id = kernel32.GetCurrentThreadId()
        modifiers, key = spec.registration_values()

        if not user32.RegisterHotKey(None, HOTKEY_ID, modifiers, key):
            error_code = ctypes.get_last_error()
            self._error = (
                f"无法注册 {spec.display}（Windows error {error_code}），"
                "可能已被其他程序占用"
            )
            self._ready.set()
            return

        self._registered = True
        self._ready.set()
        message = MSG()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    break
                if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                    self.events.put("invoke")
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False


def clipboard_sequence_number() -> int:
    if not hasattr(ctypes, "WinDLL"):
        return 0
    return int(ctypes.WinDLL("user32").GetClipboardSequenceNumber())


def send_copy_shortcut() -> bool:
    """Release hotkey modifiers, then send Ctrl+C to the foreground app."""
    if not hasattr(ctypes, "WinDLL"):
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    # WM_HOTKEY can arrive while the user is still physically holding Alt,
    # Ctrl or Shift. Pot's Windows fallback explicitly releases modifiers
    # before copying for the same reason.
    inputs = (INPUT * 7)(
        INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, 0)),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(VK_MENU, 0, KEYEVENTF_KEYUP, 0, 0)),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0, 0)),
        ),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(VK_CONTROL, 0, 0, 0, 0))),
        INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=KEYBDINPUT(VK_C, 0, 0, 0, 0))),
        INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(VK_C, 0, KEYEVENTF_KEYUP, 0, 0)),
        ),
        INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(ki=KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, 0)),
        ),
    )
    sent = user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
    return sent == len(inputs)


def cursor_position() -> tuple[int, int]:
    point = POINT()
    if hasattr(ctypes, "WinDLL") and ctypes.WinDLL("user32").GetCursorPos(
        ctypes.byref(point)
    ):
        return int(point.x), int(point.y)
    return 0, 0


def work_area_for_point(x: int, y: int) -> tuple[int, int, int, int]:
    """Return the work area of the monitor nearest a screen point."""
    if hasattr(ctypes, "WinDLL"):
        user32 = ctypes.WinDLL("user32")
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        monitor = user32.MonitorFromPoint(POINT(x, y), 2)
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            rect = info.rcWork
            return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    return 0, 0, 1920, 1080
