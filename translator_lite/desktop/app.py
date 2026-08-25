"""Lightweight native Windows translator built with the Python standard library."""

from __future__ import annotations

import argparse
import ctypes
import queue
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk

from ..client import GoogleTranslateError, TranslationResult, translate
from ..windows.hotkey import (
    DEFAULT_HOTKEY,
    GlobalHotkey,
    HotkeySpec,
    clipboard_sequence_number,
    cursor_position,
    send_copy_shortcut,
    work_area_for_point,
)
from ..windows.mouse import GlobalMouseClick, window_at_point_is_current_process
from ..windows.selection import get_selected_text_by_automation
from ..windows.tray import SystemTray
from ..windows.window import redraw_window, set_window_bounds, set_window_position
from .placement import clamp_window_position, resize_window_geometry
from .settings import AppSettings, load_settings, save_settings


@dataclass(frozen=True)
class Language:
    label: str
    code: str


SOURCE_LANGUAGES = (
    Language("自动检测", "auto"),
    Language("中文（简体）", "zh-CN"),
    Language("中文（繁体）", "zh-TW"),
    Language("English", "en"),
    Language("日本語", "ja"),
    Language("한국어", "ko"),
    Language("Français", "fr"),
    Language("Deutsch", "de"),
    Language("Español", "es"),
    Language("Русский", "ru"),
)
TARGET_LANGUAGES = SOURCE_LANGUAGES[1:]

COLORS = {
    "border": "#D9D9DD",
    "window": "#F3F3F4",
    "card": "#FFFFFF",
    "input": "#F7F7F8",
    "provider": "#E4E4E6",
    "text": "#151518",
    "muted": "#6F7077",
    "faint": "#A3A4AA",
    "blue": "#2563EB",
    "blue_hover": "#1D4ED8",
    "blue_soft": "#E7EEFF",
    "purple": "#7C3AED",
    "danger": "#B42318",
}

FONT = "Microsoft YaHei UI"
PLACEHOLDER = "输入要翻译的文本…"
HOTKEY_FALLBACKS = (
    HotkeySpec(("Alt", "Shift"), "W"),
    HotkeySpec(("Ctrl", "Alt"), "T"),
)


def resource_path(relative_path: str) -> Path:
    """Resolve a project asset both from source and a PyInstaller bundle."""
    source_root = Path(__file__).resolve().parents[1]
    bundle_root = Path(getattr(sys, "_MEIPASS", source_root))
    return bundle_root / relative_path


def enable_dpi_awareness() -> None:
    """Keep Tk dimensions crisp on Windows high-DPI displays."""
    if not hasattr(ctypes, "windll"):
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class HotkeySettingsDialog:
    """Compact recorder for the global selection-translate shortcut."""

    CTRL_MASK = 0x0004
    SHIFT_MASK = 0x0001
    ALT_MASK = 0x20000
    ALT_FALLBACK_MASK = 0x0008

    def __init__(self, app: "TranslatorApp") -> None:
        self.app = app
        self.candidate = app.hotkey_spec
        self.recording = False
        self._finished = False

        self.window = tk.Toplevel(app.root)
        self.window.title("热键设置")
        self.window.configure(bg=COLORS["window"])
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<KeyPress>", self._on_key_press)

        width = 600
        app.root.update_idletasks()
        self._build()

        # Font metrics grow with Windows DPI scaling. Size the client area from
        # its real requested height so the bottom action row cannot be clipped.
        self.window.update_idletasks()
        height = max(300, self.window.winfo_reqheight() + 4)
        x = app.root.winfo_x() + max(0, (app.root.winfo_width() - width) // 2)
        y = app.root.winfo_y() + max(0, (app.root.winfo_height() - height) // 2)
        root_center_x = app.root.winfo_x() + app.root.winfo_width() // 2
        root_center_y = app.root.winfo_y() + app.root.winfo_height() // 2
        x, y = clamp_window_position(
            x,
            y,
            width,
            height,
            work_area_for_point(root_center_x, root_center_y),
        )
        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.window.after(30, self.window.focus_force)

    def _build(self) -> None:
        tk.Label(
            self.window,
            text="热键设置",
            bg=COLORS["window"],
            fg=COLORS["text"],
            font=(FONT, 16, "bold"),
        ).pack(anchor="w", padx=20, pady=(17, 11))

        row = tk.Frame(
            self.window,
            bg=COLORS["input"],
            highlightthickness=1,
            highlightbackground=COLORS["border"],
        )
        row.pack(fill="x", padx=20)

        tk.Label(
            row,
            text="划词翻译",
            bg=COLORS["input"],
            fg=COLORS["text"],
            font=(FONT, 12, "bold"),
        ).pack(side="left", padx=18, pady=24)

        recorder = tk.Frame(
            row,
            bg=COLORS["card"],
            highlightthickness=1,
            highlightbackground="#B8B8BD",
        )
        recorder.pack(side="right", fill="x", expand=True, padx=14, pady=12)

        labels = tk.Frame(recorder, bg=COLORS["card"])
        labels.pack(side="left", fill="both", expand=True, padx=13, pady=7)
        self.instruction = tk.Label(
            labels,
            text="点击录制，然后按下新快捷键",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=(FONT, 8),
            anchor="w",
        )
        self.instruction.pack(fill="x")
        self.hotkey_label = tk.Label(
            labels,
            text=self.candidate.display,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("Segoe UI", 13),
            anchor="w",
        )
        self.hotkey_label.pack(fill="x")

        self.record_button = tk.Button(
            recorder,
            text="录制",
            command=self.begin_recording,
            bd=0,
            relief="flat",
            bg="#D7D7DA",
            activebackground="#C9C9CD",
            fg=COLORS["text"],
            padx=15,
            pady=8,
            cursor="hand2",
            font=(FONT, 9, "bold"),
        )
        self.record_button.pack(side="right", padx=9, pady=9)

        self.error_label = tk.Label(
            self.window,
            text="划词内容会复制到剪贴板，并发送给 Google Translate。",
            bg=COLORS["window"],
            fg=COLORS["muted"],
            font=(FONT, 8),
            anchor="w",
        )
        self.error_label.pack(fill="x", padx=22, pady=(9, 0))

        actions = tk.Frame(self.window, bg=COLORS["window"])
        actions.pack(side="bottom", fill="x", padx=20, pady=15)
        tk.Button(
            actions,
            text="确定",
            command=self.confirm,
            bd=0,
            relief="flat",
            bg=COLORS["blue"],
            fg="#FFFFFF",
            activebackground=COLORS["blue_hover"],
            cursor="hand2",
            padx=18,
            pady=7,
            font=(FONT, 8, "bold"),
        ).pack(side="right")
        tk.Button(
            actions,
            text="取消",
            command=self.cancel,
            bd=0,
            relief="flat",
            bg=COLORS["window"],
            fg=COLORS["muted"],
            activebackground="#E7E7E9",
            cursor="hand2",
            padx=13,
            pady=7,
            font=(FONT, 8),
        ).pack(side="right", padx=(0, 7))

    def begin_recording(self) -> None:
        self.recording = True
        self.instruction.configure(text="请按下组合键…", fg=COLORS["blue"])
        self.hotkey_label.configure(text="等待按键")
        self.record_button.configure(text="录制中…", state="disabled")
        self.error_label.configure(text="至少包含 Ctrl、Alt、Shift 之一。", fg=COLORS["muted"])
        self.window.focus_force()

    def _on_key_press(self, event: tk.Event[tk.Misc]) -> str | None:
        if not self.recording:
            return None
        keysym = str(event.keysym)
        if keysym in {
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
            "Shift_L",
            "Shift_R",
        }:
            return "break"

        modifiers: list[str] = []
        if event.state & self.CTRL_MASK:
            modifiers.append("Ctrl")
        if event.state & (self.ALT_MASK | self.ALT_FALLBACK_MASK):
            modifiers.append("Alt")
        if event.state & self.SHIFT_MASK:
            modifiers.append("Shift")

        try:
            self.candidate = HotkeySpec(tuple(modifiers), keysym)
        except ValueError as exc:
            self.error_label.configure(text=str(exc), fg=COLORS["danger"])
            return "break"

        self.recording = False
        self.instruction.configure(text="新快捷键", fg=COLORS["muted"])
        self.hotkey_label.configure(text=self.candidate.display)
        self.record_button.configure(text="重新录制", state="normal")
        self.error_label.configure(
            text="点击确定后立即生效。", fg=COLORS["muted"]
        )
        return "break"

    def confirm(self) -> None:
        success, message = self.app.apply_hotkey(self.candidate, persist=True)
        if not success:
            self.error_label.configure(text=message or "快捷键设置失败", fg=COLORS["danger"])
            return
        self._finished = True
        self.window.destroy()
        self.app._settings_dialog = None

    def cancel(self) -> None:
        if self._finished:
            return
        self.app.apply_hotkey(self.app.hotkey_spec, persist=False)
        self._finished = True
        self.window.destroy()
        self.app._settings_dialog = None


class TranslatorApp:
    WIDTH = 720
    HEIGHT = 660
    MIN_WIDTH = 440
    MIN_HEIGHT = 500
    RESIZE_BORDER = 6
    RESIZE_CORNER = 8

    def __init__(self, root: tk.Tk, *, decorated: bool = False) -> None:
        self.root = root
        self._decorated = decorated
        self._drag_offset = (0, 0)
        self._resize_edge: str | None = None
        self._resize_start_pointer = (0, 0)
        self._resize_start_geometry = (0, 0, self.WIDTH, self.HEIGHT)
        self._resize_handles: dict[str, tk.Frame] = {}
        self._placeholder_active = True
        self._busy = False
        self._request_id = 0
        self._closed = False
        self._capture_pending = False
        self._clipboard_sequence = 0
        self._clipboard_deadline = 0.0
        settings = load_settings()
        self.hotkey_spec = settings.hotkey
        self._position_pinned = settings.position_pinned
        self._fixed_position = settings.window_position
        self._saved_window_size = settings.window_size
        self._icon_path = resource_path("assets/translator_icon.ico")
        self._hotkey_events: queue.Queue[str] = queue.Queue()
        self._hotkey_manager = GlobalHotkey(self._hotkey_events)
        self._mouse_events: queue.Queue[tuple[int, int]] = queue.Queue()
        self._mouse_monitor = GlobalMouseClick(self._mouse_events)
        self._tray_events: queue.Queue[str] = queue.Queue()
        self._tray = SystemTray(self._tray_events, icon_path=self._icon_path)
        self._settings_dialog: HotkeySettingsDialog | None = None
        self._results: queue.Queue[tuple[int, TranslationResult | None, str | None]] = (
            queue.Queue()
        )

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self._bind_shortcuts()
        self._set_placeholder()
        self._initialize_hotkey()
        self._initialize_tray()
        self._initialize_mouse_monitor()
        self._poll_results()
        self._poll_hotkey_events()
        self._poll_tray_events()
        self._poll_mouse_events()

    def _configure_window(self) -> None:
        self.root.title("Translator")
        if self._icon_path.is_file():
            try:
                self.root.iconbitmap(default=str(self._icon_path))
            except tk.TclError:
                pass
        self.root.overrideredirect(not self._decorated)
        self.root.configure(bg=COLORS["border"])
        self.root.attributes("-topmost", True)
        self.root.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)

        requested_width, requested_height = self._saved_window_size or (
            self.WIDTH,
            self.HEIGHT,
        )
        screen_width = self.root.winfo_screenwidth()
        if self._position_pinned and self._fixed_position is not None:
            reference_x, reference_y = self._fixed_position
        else:
            reference_x, reference_y = screen_width - 1, 54
        work_area = work_area_for_point(reference_x, reference_y)
        left, top, right, bottom = work_area
        width = max(self.MIN_WIDTH, min(requested_width, right - left))
        height = max(self.MIN_HEIGHT, min(requested_height, bottom - top))

        if self._position_pinned and self._fixed_position is not None:
            x, y = clamp_window_position(
                *self._fixed_position,
                width,
                height,
                work_area,
            )
        else:
            x, y = clamp_window_position(
                right - width - 42,
                top + 54,
                width,
                height,
                work_area,
            )
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        if not self._decorated:
            self.root.after(20, self._apply_windows_rounding)

    def _apply_windows_rounding(self) -> None:
        """Ask Windows 11 for rounded corners; safely ignored elsewhere."""
        if not hasattr(ctypes, "windll"):
            return
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            preference = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                33,
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
        except (AttributeError, OSError):
            pass

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Language.TCombobox",
            fieldbackground=COLORS["card"],
            background=COLORS["card"],
            foreground=COLORS["text"],
            bordercolor=COLORS["border"],
            lightcolor=COLORS["border"],
            darkcolor=COLORS["border"],
            arrowcolor=COLORS["muted"],
            padding=(8, 5),
            font=(FONT, 9),
        )
        style.map(
            "Language.TCombobox",
            fieldbackground=[("readonly", COLORS["card"])],
            selectbackground=[("readonly", COLORS["card"])],
            selectforeground=[("readonly", COLORS["text"])],
        )

    def _build_ui(self) -> None:
        self.surface = tk.Frame(self.root, bg=COLORS["window"])
        self.surface.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_titlebar()

        content = tk.Frame(self.surface, bg=COLORS["window"])
        content.pack(fill="both", expand=True, padx=14, pady=(4, 14))

        self._build_input_card(content)

        self.footer_status = tk.Label(
            content,
            text=f"就绪  ·  {self.hotkey_spec.display} 划词  ·  Ctrl+Enter 翻译",
            bg=COLORS["window"],
            fg=COLORS["muted"],
            font=(FONT, 8),
            anchor="w",
        )
        self.footer_status.pack(side="bottom", fill="x", pady=(8, 0))

        self._build_provider_card(content)
        self._build_resize_handles()

    def _build_resize_handles(self) -> None:
        """Overlay resize targets on every edge of the borderless window."""
        if self._decorated:
            return

        border = self.RESIZE_BORDER
        corner = self.RESIZE_CORNER
        inset = 1
        handle_specs: tuple[tuple[str, str, dict[str, float | int]], ...] = (
            (
                "n",
                "sb_v_double_arrow",
                {
                    "x": corner,
                    "y": inset,
                    "relwidth": 1.0,
                    "width": -2 * corner,
                    "height": border,
                },
            ),
            (
                "s",
                "sb_v_double_arrow",
                {
                    "x": corner,
                    "rely": 1.0,
                    "y": -(border + inset),
                    "relwidth": 1.0,
                    "width": -2 * corner,
                    "height": border,
                },
            ),
            (
                "w",
                "sb_h_double_arrow",
                {
                    "x": inset,
                    "y": corner,
                    "width": border,
                    "relheight": 1.0,
                    "height": -2 * corner,
                },
            ),
            (
                "e",
                "sb_h_double_arrow",
                {
                    "relx": 1.0,
                    "x": -(border + inset),
                    "y": corner,
                    "width": border,
                    "relheight": 1.0,
                    "height": -2 * corner,
                },
            ),
            (
                "nw",
                "size_nw_se",
                {
                    "x": inset,
                    "y": inset,
                    "width": corner,
                    "height": corner,
                },
            ),
            (
                "ne",
                "size_ne_sw",
                {
                    "relx": 1.0,
                    "x": -(corner + inset),
                    "y": inset,
                    "width": corner,
                    "height": corner,
                },
            ),
            (
                "sw",
                "size_ne_sw",
                {
                    "x": inset,
                    "rely": 1.0,
                    "y": -(corner + inset),
                    "width": corner,
                    "height": corner,
                },
            ),
            (
                "se",
                "size_nw_se",
                {
                    "relx": 1.0,
                    "rely": 1.0,
                    "x": -(corner + inset),
                    "y": -(corner + inset),
                    "width": corner,
                    "height": corner,
                },
            ),
        )

        for edge, cursor, placement in handle_specs:
            handle = tk.Frame(
                self.root,
                bg=COLORS["window"],
                cursor=cursor,
                bd=0,
                highlightthickness=0,
                takefocus=False,
            )
            handle.place(**placement)
            handle.bind(
                "<ButtonPress-1>",
                lambda event, resize_edge=edge: self._start_resize(
                    event, resize_edge
                ),
            )
            handle.bind("<B1-Motion>", self._resize_window)
            handle.bind("<ButtonRelease-1>", self._finish_resize)
            handle.lift()
            self._resize_handles[edge] = handle

    def _build_titlebar(self) -> None:
        titlebar = tk.Frame(self.surface, bg=COLORS["window"], height=38)
        titlebar.pack(fill="x", padx=8, pady=(4, 1))
        titlebar.pack_propagate(False)

        self.pin_button = self._flat_button(
            titlebar,
            "\ue718",
            self.toggle_position_pin,
            fg=COLORS["muted"],
            bg=COLORS["window"],
            active_bg=COLORS["blue_soft"],
            padx=0,
            width=3,
        )
        self.pin_button.configure(font=("Segoe MDL2 Assets", 11))
        self.pin_button.pack(side="left", padx=(0, 8), pady=4)
        self._update_position_pin_style()

        title = tk.Label(
            titlebar,
            text="Translator",
            bg=COLORS["window"],
            fg=COLORS["text"],
            font=(FONT, 10, "bold"),
        )
        title.pack(side="left", pady=7)

        close_button = self._flat_button(
            titlebar,
            "×",
            self.hide_window,
            fg=COLORS["muted"],
            bg=COLORS["window"],
            active_bg="#E6E6E8",
            width=3,
        )
        close_button.pack(side="right", pady=3)

        settings_button = self._flat_button(
            titlebar,
            "设置",
            self.open_settings,
            fg=COLORS["muted"],
            bg=COLORS["window"],
            active_bg="#E6E6E8",
            padx=8,
        )
        settings_button.pack(side="right", padx=(0, 3), pady=3)

        for widget in (titlebar, title):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag_window)
            widget.bind("<ButtonRelease-1>", self._finish_drag)

    def _build_input_card(self, parent: tk.Widget) -> None:
        card = tk.Frame(
            parent,
            bg=COLORS["input"],
            highlightthickness=1,
            highlightbackground="#EBEBED",
        )
        card.pack(fill="x")

        heading = tk.Frame(card, bg=COLORS["input"])
        heading.pack(fill="x", padx=14, pady=(9, 1))
        tk.Label(
            heading,
            text="原文",
            bg=COLORS["input"],
            fg=COLORS["muted"],
            font=(FONT, 8, "bold"),
        ).pack(side="left")
        self.counter_label = tk.Label(
            heading,
            text="0 / 5,000",
            bg=COLORS["input"],
            fg=COLORS["faint"],
            font=(FONT, 8),
        )
        self.counter_label.pack(side="right")

        self.source_text = tk.Text(
            card,
            height=4,
            wrap="word",
            undo=True,
            bd=0,
            highlightthickness=0,
            bg=COLORS["input"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground="#C8D8FF",
            padx=14,
            pady=6,
            font=(FONT, 14),
        )
        self.source_text.pack(fill="x")

        toolbar = tk.Frame(card, bg=COLORS["input"])
        toolbar.pack(fill="x", padx=12, pady=(2, 7))

        self._flat_button(
            toolbar,
            "粘贴",
            self.paste_and_translate,
            fg=COLORS["text"],
            bg=COLORS["card"],
            active_bg="#ECECEF",
            padx=10,
        ).pack(side="left", padx=(0, 6))
        self._flat_button(
            toolbar,
            "清空",
            self.clear,
            fg=COLORS["muted"],
            bg=COLORS["input"],
            active_bg="#E7E7E9",
            padx=8,
        ).pack(side="left")

        self.translate_button = self._flat_button(
            toolbar,
            "翻译",
            self.translate_now,
            fg="#FFFFFF",
            bg=COLORS["blue"],
            active_bg=COLORS["blue_hover"],
            padx=14,
        )
        self.translate_button.pack(side="right")

        language_row = tk.Frame(card, bg=COLORS["input"])
        language_row.pack(fill="x", padx=12, pady=(0, 9))

        source_labels = [language.label for language in SOURCE_LANGUAGES]
        target_labels = [language.label for language in TARGET_LANGUAGES]
        self.source_language = ttk.Combobox(
            language_row,
            values=source_labels,
            state="readonly",
            style="Language.TCombobox",
            width=15,
        )
        self.source_language.set(source_labels[0])
        self.source_language.pack(side="left")

        self._flat_button(
            language_row,
            "⇄",
            self.swap_languages,
            fg=COLORS["muted"],
            bg=COLORS["input"],
            active_bg="#E7E7E9",
            width=3,
        ).pack(side="left", padx=7)

        self.target_language = ttk.Combobox(
            language_row,
            values=target_labels,
            state="readonly",
            style="Language.TCombobox",
            width=15,
        )
        self.target_language.set("中文（简体）")
        self.target_language.pack(side="left")

        self.source_text.bind("<FocusIn>", self._remove_placeholder)
        self.source_text.bind("<FocusOut>", self._restore_placeholder_if_empty)
        self.source_text.bind("<KeyRelease>", self._update_counter)

    def _build_provider_card(self, parent: tk.Widget) -> None:
        self.provider_card = tk.Frame(
            parent,
            bg=COLORS["card"],
            highlightthickness=1,
            highlightbackground="#DEDEE1",
        )
        self.provider_card.pack(fill="both", expand=True, pady=(12, 0))

        header = tk.Frame(self.provider_card, bg=COLORS["provider"], height=40)
        header.pack(fill="x")
        header.pack_propagate(False)

        badge = tk.Label(
            header,
            text="G",
            width=2,
            bg="#4285F4",
            fg="#FFFFFF",
            font=("Segoe UI", 11, "bold"),
        )
        badge.pack(side="left", padx=(11, 9), pady=7)
        tk.Label(
            header,
            text="Google Translate",
            bg=COLORS["provider"],
            fg=COLORS["text"],
            font=(FONT, 10, "bold"),
        ).pack(side="left")
        self.provider_meta = tk.Label(
            header,
            text="等待输入",
            bg=COLORS["provider"],
            fg=COLORS["muted"],
            font=(FONT, 8),
        )
        self.provider_meta.pack(side="right", padx=(6, 12))

        self.result_body = tk.Frame(self.provider_card, bg=COLORS["card"])
        self.result_body.pack(fill="both", expand=True)

        self.result_text = tk.Text(
            self.result_body,
            height=2,
            wrap="word",
            bd=0,
            highlightthickness=0,
            bg=COLORS["card"],
            fg=COLORS["text"],
            selectbackground="#C8D8FF",
            padx=14,
            pady=10,
            font=(FONT, 12),
            state="disabled",
            cursor="arrow",
        )
        self.result_text.pack(fill="both", expand=True)

        result_actions = tk.Frame(self.result_body, bg=COLORS["card"])
        result_actions.pack(fill="x", padx=11, pady=(0, 10))
        self.copy_button = self._flat_button(
            result_actions,
            "复制译文",
            self.copy_result,
            fg=COLORS["blue"],
            bg=COLORS["blue_soft"],
            active_bg="#D9E5FF",
            padx=10,
        )
        self.copy_button.pack(side="right")
        self.copy_button.configure(state="disabled")

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-Return>", self.translate_now)
        self.root.bind_all("<Control-KP_Enter>", self.translate_now)
        self.root.bind_all("<Control-l>", self.focus_input)
        self.root.bind_all("<Escape>", lambda _event: self.hide_window())

    def _flat_button(
        self,
        parent: tk.Widget,
        text: str,
        command: object,
        *,
        fg: str,
        bg: str,
        active_bg: str | None = None,
        padx: int = 7,
        width: int = 0,
    ) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            fg=fg,
            bg=bg,
            activeforeground=fg,
            activebackground=active_bg or bg,
            disabledforeground=COLORS["faint"],
            bd=0,
            highlightthickness=0,
            relief="flat",
            cursor="hand2",
            padx=padx,
            width=width,
            font=(FONT, 8, "bold"),
        )

    def _start_drag(self, event: tk.Event[tk.Misc]) -> None:
        self._drag_offset = (
            event.x_root - self.root.winfo_x(),
            event.y_root - self.root.winfo_y(),
        )

    def _drag_window(self, event: tk.Event[tk.Misc]) -> None:
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self._place_window(x, y)

    def _start_resize(self, event: tk.Event[tk.Misc], edge: str) -> str:
        self.root.update_idletasks()
        self._resize_edge = edge
        self._resize_start_pointer = (event.x_root, event.y_root)
        self._resize_start_geometry = (
            self.root.winfo_x(),
            self.root.winfo_y(),
            self.root.winfo_width(),
            self.root.winfo_height(),
        )
        return "break"

    def _resize_window(self, event: tk.Event[tk.Misc]) -> str:
        if self._resize_edge is None:
            return "break"
        x, y, width, height = resize_window_geometry(
            self._resize_edge,
            self._resize_start_pointer,
            (event.x_root, event.y_root),
            self._resize_start_geometry,
            (self.MIN_WIDTH, self.MIN_HEIGHT),
        )
        if not set_window_bounds(
            self.root.winfo_id(),
            x,
            y,
            width,
            height,
        ):
            # Tk accepts "+-100" as an absolute negative virtual-screen coordinate.
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        return "break"

    def _finish_resize(
        self, _event: tk.Event[tk.Misc] | None = None
    ) -> str:
        if self._resize_edge is None:
            return "break"
        self._resize_edge = None
        self.root.update_idletasks()
        redraw_window(self.root.winfo_id(), immediate=True)

        if self._position_pinned:
            self._fixed_position = self._bounded_position(
                self.root.winfo_x(), self.root.winfo_y()
            )
            self._place_window(*self._fixed_position)

        try:
            self._persist_settings()
        except OSError as exc:
            self.footer_status.configure(
                text=f"窗口大小已生效，但设置无法保存: {exc}",
                fg=COLORS["danger"],
            )
        return "break"

    def _window_size(self) -> tuple[int, int]:
        self.root.update_idletasks()
        return (
            max(self.MIN_WIDTH, self.root.winfo_width()),
            max(self.MIN_HEIGHT, self.root.winfo_height()),
        )

    def _bounded_position(self, x: int, y: int) -> tuple[int, int]:
        width, height = self._window_size()
        return clamp_window_position(
            x,
            y,
            width,
            height,
            work_area_for_point(x, y),
        )

    def _place_window(self, x: int, y: int) -> None:
        if not set_window_position(self.root.winfo_id(), x, y):
            # Tk accepts "+-100" for a negative virtual-screen coordinate.
            self.root.geometry(f"+{x}+{y}")

    def _place_at_fixed_position(self) -> bool:
        if not self._position_pinned or self._fixed_position is None:
            return False
        self._place_window(*self._bounded_position(*self._fixed_position))
        return True

    def _current_settings(self) -> AppSettings:
        return AppSettings(
            self.hotkey_spec,
            self._position_pinned,
            self._fixed_position,
            self._window_size(),
        )

    def _persist_settings(self) -> None:
        save_settings(self._current_settings())

    def _update_position_pin_style(self) -> None:
        if self._position_pinned:
            self.pin_button.configure(
                fg=COLORS["blue"],
                bg=COLORS["blue_soft"],
                activeforeground=COLORS["blue"],
                activebackground="#D9E5FF",
            )
        else:
            self.pin_button.configure(
                fg=COLORS["muted"],
                bg=COLORS["window"],
                activeforeground=COLORS["blue"],
                activebackground=COLORS["blue_soft"],
            )

    def toggle_position_pin(self) -> None:
        self._position_pinned = not self._position_pinned
        if self._position_pinned:
            self._fixed_position = self._bounded_position(
                self.root.winfo_x(), self.root.winfo_y()
            )
            self._place_window(*self._fixed_position)
        self._update_position_pin_style()

        try:
            self._persist_settings()
        except OSError as exc:
            self.footer_status.configure(
                text=f"位置状态已生效，但设置无法保存: {exc}",
                fg=COLORS["danger"],
            )
            return

        message = (
            "窗口位置已固定；拖动后会自动更新"
            if self._position_pinned
            else "已取消位置固定；下次划词将跟随鼠标"
        )
        self.footer_status.configure(text=message, fg=COLORS["muted"])

    def _finish_drag(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if not self._position_pinned:
            return
        self._fixed_position = self._bounded_position(
            self.root.winfo_x(), self.root.winfo_y()
        )
        self._place_window(*self._fixed_position)
        try:
            self._persist_settings()
        except OSError as exc:
            self.footer_status.configure(
                text=f"新位置已生效，但设置无法保存: {exc}",
                fg=COLORS["danger"],
            )

    def apply_hotkey(
        self, spec: HotkeySpec, *, persist: bool
    ) -> tuple[bool, str | None]:
        previous = self.hotkey_spec
        success, error = self._hotkey_manager.start(spec)
        if not success:
            if spec != previous:
                self._hotkey_manager.start(previous)
            self.footer_status.configure(
                text=error or "全局快捷键注册失败", fg=COLORS["danger"]
            )
            return False, error

        self.hotkey_spec = spec
        warning: str | None = None
        if persist:
            try:
                self._persist_settings()
            except OSError as exc:
                warning = f"快捷键已生效，但设置无法保存: {exc}"

        self.footer_status.configure(
            text=f"就绪  ·  {spec.display} 划词  ·  Ctrl+Enter 翻译",
            fg=COLORS["muted"] if not warning else COLORS["danger"],
        )
        return True, warning

    def _initialize_hotkey(self) -> None:
        preferred = self.hotkey_spec
        last_error: str | None = None
        seen: set[HotkeySpec] = set()
        for candidate in (preferred, *HOTKEY_FALLBACKS):
            if candidate in seen:
                continue
            seen.add(candidate)
            success, error = self._hotkey_manager.start(candidate)
            if success:
                self.hotkey_spec = candidate
                if candidate == preferred:
                    self.footer_status.configure(
                        text=f"就绪  ·  {candidate.display} 划词  ·  Ctrl+Enter 翻译",
                        fg=COLORS["muted"],
                    )
                else:
                    self.footer_status.configure(
                        text=f"{preferred.display} 已占用，当前使用 {candidate.display}",
                        fg=COLORS["purple"],
                    )
                return
            last_error = error

        self.footer_status.configure(
            text=last_error or "没有可用的全局快捷键", fg=COLORS["danger"]
        )

    def open_settings(self) -> None:
        if self._settings_dialog and self._settings_dialog.window.winfo_exists():
            self._settings_dialog.window.deiconify()
            self._settings_dialog.window.lift()
            self._settings_dialog.window.focus_force()
            return
        self._hotkey_manager.stop()
        self._settings_dialog = HotkeySettingsDialog(self)

    def hide_window(self) -> str:
        self.root.withdraw()
        return "break"

    def show_window(self) -> None:
        self._place_at_fixed_position()
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.after(40, self.source_text.focus_set)

    def _initialize_tray(self) -> None:
        success, error = self._tray.start()
        if not success:
            self.footer_status.configure(
                text=error or "系统托盘启动失败", fg=COLORS["danger"]
            )

    def _initialize_mouse_monitor(self) -> None:
        success, error = self._mouse_monitor.start()
        if not success:
            self.footer_status.configure(
                text=error or "点击窗口外自动隐藏不可用",
                fg=COLORS["danger"],
            )

    def _settings_window_is_open(self) -> bool:
        dialog = self._settings_dialog
        if dialog is None:
            return False
        try:
            return bool(dialog.window.winfo_exists())
        except tk.TclError:
            return False

    def _handle_global_mouse_click(self, x: int, y: int) -> None:
        if self._closed or self._settings_window_is_open():
            return
        try:
            if self.root.state() == "withdrawn":
                return
        except tk.TclError:
            return
        if window_at_point_is_current_process(x, y) is False:
            self.hide_window()

    def _poll_mouse_events(self) -> None:
        if self._closed:
            return
        try:
            while True:
                self._handle_global_mouse_click(*self._mouse_events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(20, self._poll_mouse_events)

    def _discard_mouse_events(self) -> None:
        try:
            while True:
                self._mouse_events.get_nowait()
        except queue.Empty:
            pass

    def _poll_tray_events(self) -> None:
        if self._closed:
            return
        try:
            while True:
                event = self._tray_events.get_nowait()
                if event == "show":
                    self._discard_mouse_events()
                    self.show_window()
                elif event == "settings":
                    self._discard_mouse_events()
                    self.show_window()
                    self.open_settings()
                elif event == "exit":
                    self.exit_app()
                    return
        except queue.Empty:
            pass
        self.root.after(80, self._poll_tray_events)

    def _show_near_cursor(self) -> None:
        cursor_x, cursor_y = cursor_position()
        if not self._place_at_fixed_position():
            left, top, right, bottom = work_area_for_point(cursor_x, cursor_y)
            width, height = self._window_size()
            margin = 18
            x = cursor_x + margin
            y = cursor_y + margin
            if x + width > right:
                x = cursor_x - width - margin
            if y + height > bottom:
                y = cursor_y - height - margin
            x, y = clamp_window_position(
                x, y, width, height, (left, top, right, bottom)
            )
            self._place_window(x, y)
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.after(40, self.source_text.focus_set)

    def _poll_hotkey_events(self) -> None:
        if self._closed:
            return
        try:
            while True:
                event = self._hotkey_events.get_nowait()
                if event == "invoke" and not self._capture_pending:
                    self._capture_pending = True
                    self.root.after(80, self._begin_selection_capture)
        except queue.Empty:
            pass
        self.root.after(60, self._poll_hotkey_events)

    def _begin_selection_capture(self) -> None:
        selected_text = get_selected_text_by_automation()
        if selected_text:
            self._capture_pending = False
            self._accept_selected_text(selected_text)
            return

        self._clipboard_sequence = clipboard_sequence_number()
        if not send_copy_shortcut():
            self._capture_pending = False
            self._show_near_cursor()
            self._show_selection_error(
                "无法读取选中文本；若目标程序以管理员身份运行，请也以管理员身份运行 Translator"
            )
            return
        self._clipboard_deadline = time.monotonic() + 1.0
        self.root.after(35, self._poll_selection_capture)

    def _poll_selection_capture(self) -> None:
        if self._closed or not self._capture_pending:
            return
        changed = clipboard_sequence_number() != self._clipboard_sequence
        if changed or time.monotonic() >= self._clipboard_deadline:
            self._finish_selection_capture(changed)
            return
        self.root.after(35, self._poll_selection_capture)

    def _finish_selection_capture(self, changed: bool | None = None) -> None:
        self._capture_pending = False
        if changed is None:
            changed = clipboard_sequence_number() != self._clipboard_sequence
        try:
            selected_text = str(self.root.clipboard_get()).strip()
        except tk.TclError:
            selected_text = ""

        if not changed or not selected_text:
            self._show_near_cursor()
            self._show_selection_error(
                "没有读取到选中文本，请先划词选中后再按快捷键"
            )
            return

        self._accept_selected_text(selected_text)

    def _accept_selected_text(self, selected_text: str) -> None:
        self._show_near_cursor()
        self._set_input_text(selected_text[:5_000])
        self._show_result("")
        self.translate_now()

    def _set_placeholder(self) -> None:
        self._placeholder_active = True
        self.source_text.configure(fg=COLORS["faint"])
        self.source_text.delete("1.0", "end")
        self.source_text.insert("1.0", PLACEHOLDER)

    def _remove_placeholder(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if not self._placeholder_active:
            return
        self.source_text.delete("1.0", "end")
        self.source_text.configure(fg=COLORS["text"])
        self._placeholder_active = False
        self._update_counter()

    def _restore_placeholder_if_empty(
        self, _event: tk.Event[tk.Misc] | None = None
    ) -> None:
        if not self.source_text.get("1.0", "end-1c").strip():
            self._set_placeholder()
            self._update_counter()

    def _input_text(self) -> str:
        if self._placeholder_active:
            return ""
        return self.source_text.get("1.0", "end-1c").strip()

    def _set_input_text(self, text: str) -> None:
        self._placeholder_active = False
        self.source_text.configure(fg=COLORS["text"])
        self.source_text.delete("1.0", "end")
        self.source_text.insert("1.0", text[:5_000])
        self._update_counter()

    def _update_counter(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        length = len(self._input_text())
        self.counter_label.configure(text=f"{length:,} / 5,000")

    def _language_code(self, label: str, options: tuple[Language, ...]) -> str:
        return next(language.code for language in options if language.label == label)

    def _language_label(self, code: str) -> str:
        for language in SOURCE_LANGUAGES:
            if language.code == code:
                return language.label
        return code

    def swap_languages(self) -> None:
        source_label = self.source_language.get()
        target_label = self.target_language.get()
        if source_label == "自动检测":
            self.source_language.set(target_label)
            self.target_language.set(
                "中文（简体）" if target_label == "English" else "English"
            )
        else:
            self.source_language.set(target_label)
            self.target_language.set(source_label)

        result = self.result_text.get("1.0", "end-1c").strip()
        if result:
            original = self._input_text()
            self._set_input_text(result)
            self._show_result(original)
            self.provider_meta.configure(text="语言已交换", fg=COLORS["muted"])
        self.source_text.focus_set()

    def paste_and_translate(self) -> None:
        try:
            clipboard_text = self.root.clipboard_get()
        except tk.TclError:
            self._show_error("剪贴板中没有可用文本")
            return
        self._set_input_text(clipboard_text.strip())
        self.translate_now()

    def clear(self) -> None:
        self._set_placeholder()
        self._show_result("")
        self.provider_meta.configure(text="等待输入", fg=COLORS["muted"])
        self.footer_status.configure(
            text=f"就绪  ·  {self.hotkey_spec.display} 划词  ·  Ctrl+Enter 翻译",
            fg=COLORS["muted"],
        )
        self._update_counter()
        self.source_text.focus_set()

    def translate_now(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if self._busy:
            return "break"
        text = self._input_text()
        if not text:
            self._show_error("请输入要翻译的文本")
            self.source_text.focus_set()
            return "break"

        source = self._language_code(self.source_language.get(), SOURCE_LANGUAGES)
        target = self._language_code(self.target_language.get(), TARGET_LANGUAGES)
        self._request_id += 1
        request_id = self._request_id
        self._set_busy(True)

        thread = threading.Thread(
            target=self._translate_worker,
            args=(request_id, text, source, target),
            daemon=True,
        )
        thread.start()
        return "break"

    def _translate_worker(
        self, request_id: int, text: str, source: str, target: str
    ) -> None:
        try:
            result = translate(text, source=source, target=target, timeout=15.0)
        except (GoogleTranslateError, ValueError) as exc:
            self._results.put((request_id, None, str(exc)))
        except Exception as exc:  # Keep the UI alive on unexpected network errors.
            self._results.put((request_id, None, f"翻译失败: {exc}"))
        else:
            self._results.put((request_id, result, None))

    def _poll_results(self) -> None:
        if self._closed:
            return
        try:
            while True:
                request_id, result, error = self._results.get_nowait()
                if request_id != self._request_id:
                    continue
                self._set_busy(False)
                if error:
                    self._show_error(error)
                elif result:
                    self._show_result(result.text)
                    detected = self._language_label(
                        result.detected_source_language or "auto"
                    )
                    self.provider_meta.configure(
                        text=f"检测到 {detected}", fg=COLORS["purple"]
                    )
                    self.footer_status.configure(
                        text=f"翻译完成  ·  {self.hotkey_spec.display} 继续划词",
                        fg=COLORS["muted"],
                    )
        except queue.Empty:
            pass
        self.root.after(80, self._poll_results)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.translate_button.configure(
            text="翻译中…" if busy else "翻译",
            state="disabled" if busy else "normal",
        )
        if busy:
            self.provider_meta.configure(text="请求中…", fg=COLORS["blue"])
            self.footer_status.configure(text="正在调用 Google Translate…", fg=COLORS["blue"])

    def _show_result(self, text: str, *, color: str | None = None) -> None:
        self.result_text.configure(state="normal", fg=color or COLORS["text"])
        self.result_text.delete("1.0", "end")
        if text:
            self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")
        self.copy_button.configure(state="normal" if text else "disabled")

    def _show_error(self, message: str) -> None:
        self._show_result(message, color=COLORS["danger"])
        self.provider_meta.configure(text="请求失败", fg=COLORS["danger"])
        self.footer_status.configure(text="请检查网络后重试", fg=COLORS["danger"])

    def _show_selection_error(self, message: str) -> None:
        self._show_result(message, color=COLORS["danger"])
        self.provider_meta.configure(text="划词失败", fg=COLORS["danger"])
        self.footer_status.configure(
            text=f"请重新选中文本后按 {self.hotkey_spec.display}",
            fg=COLORS["danger"],
        )

    def copy_result(self) -> None:
        text = self.result_text.get("1.0", "end-1c").strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.copy_button.configure(text="已复制")
        self.root.after(1_200, lambda: self.copy_button.configure(text="复制译文"))

    def focus_input(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        self.show_window()
        return "break"

    def exit_app(self) -> None:
        self._closed = True
        self._hotkey_manager.stop()
        self._mouse_monitor.stop()
        self._tray.stop()
        self.root.destroy()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动轻量 Translator 桌面应用")
    parser.add_argument(
        "--decorated",
        action="store_true",
        help="保留系统标题栏，主要用于 UI Automation 测试",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    enable_dpi_awareness()
    root = tk.Tk()
    TranslatorApp(root, decorated=args.decorated)
    root.mainloop()


if __name__ == "__main__":
    main()
