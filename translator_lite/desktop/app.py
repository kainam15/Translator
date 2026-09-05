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

from ..client import GoogleTranslateError, TranslationResult
from ..math_translation import split_math_parts, translate_with_math
from ..ocr.service import close_helper, recognize_screen_region, render_formulas
from ..windows.hotkey import (
    OCR_HOTKEY_ID,
    GlobalHotkey,
    HotkeySpec,
    clipboard_sequence_number,
    cursor_position,
    send_copy_shortcut,
    work_area_for_point,
)
from ..windows.mouse import GlobalMouseClick, window_at_point_is_current_process
from ..windows.ocr import ScreenRegion, WindowsOcrError
from ..windows.selection import get_selected_text_by_automation
from ..windows.tray import SystemTray
from ..windows.window import redraw_window, set_window_bounds, set_window_position
from .placement import clamp_window_position, resize_window_geometry, scale_for_dpi
from .ocr_overlay import OcrRegionSelector
from .math_view import MathTextView
from .settings import AppSettings, load_settings, save_settings
from .theme import (
    COLORS,
    COMBOBOX_STYLE,
    FONTS,
    ICON_FONT,
    KEYCAP_FONT,
    MARQUEE_SPAN,
    advance_marquee,
    configure_ttk_styles,
    flat_button,
    restyle_button,
    scrolling_text,
    separator,
)


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

PLACEHOLDER = "输入要翻译的文本…"
MAX_TEXT_LENGTH = 5_000
COUNTER_WARNING_AT = 4_500
HOTKEY_FALLBACKS = (
    HotkeySpec(("Alt", "Shift"), "W"),
    HotkeySpec(("Ctrl", "Alt"), "T"),
)
OCR_HOTKEY_FALLBACKS = (
    HotkeySpec(("Alt", "Shift"), "Q"),
    HotkeySpec(("Ctrl", "Alt"), "O"),
)


def resource_path(relative_path: str) -> Path:
    """Resolve a project asset both from source and a PyInstaller bundle."""
    source_root = Path(__file__).resolve().parents[1]
    bundle_root = Path(getattr(sys, "_MEIPASS", source_root))
    return bundle_root / relative_path


def scaled_pixels(widget: tk.Misc, value: int) -> int:
    """Turn a 96-DPI design pixel into a physical pixel for a widget's display.

    Tk sizes fonts in points and scales them with the display, but geometry is
    raw pixels; anything measured in pixels has to be converted or it drifts out
    of proportion with its own text.
    """
    try:
        scaling = float(widget.tk.call("tk", "scaling"))
    except (tk.TclError, ValueError):
        return value
    return scale_for_dpi(value, scaling)


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
    """Compact recorder for selection-translate and screen-OCR shortcuts."""

    CTRL_MASK = 0x0004
    SHIFT_MASK = 0x0001
    ALT_MASK = 0x20000
    ALT_FALLBACK_MASK = 0x0008

    def __init__(self, app: "TranslatorApp") -> None:
        self.app = app
        self.candidates = {
            "translation": app.hotkey_spec,
            "ocr": app.ocr_hotkey_spec,
        }
        self.recording_kind: str | None = None
        self._instructions: dict[str, tk.Label] = {}
        self._hotkey_labels: dict[str, tk.Label] = {}
        self._record_buttons: dict[str, tk.Button] = {}
        self._finished = False

        self.window = tk.Toplevel(app.root)
        self.window.title("热键设置")
        self.window.configure(bg=COLORS["raised"])
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.bind("<KeyPress>", self._on_key_press)

        width = scaled_pixels(app.root, 480)
        app.root.update_idletasks()
        self._build()

        # Font metrics grow with Windows DPI scaling. Size the client area from
        # its real requested height so the bottom action row cannot be clipped.
        # The floor only guards against a collapsed layout; it must stay under
        # the natural content height or it pads the dialog with dead space.
        self.window.update_idletasks()
        height = max(scaled_pixels(app.root, 120), self.window.winfo_reqheight() + 4)
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
            bg=COLORS["raised"],
            fg=COLORS["text"],
            font=FONTS["heading"],
        ).pack(anchor="w", padx=20, pady=(18, 12))

        self._build_recorder_row("translation", "划词翻译")
        self._build_recorder_row("ocr", "OCR 翻译")

        self.error_label = tk.Label(
            self.window,
            text=(
                "OCR 使用 Windows 本地识别；识别文字与划词内容一样会发送给 "
                "Google Translate。"
            ),
            bg=COLORS["raised"],
            fg=COLORS["muted"],
            font=FONTS["caption"],
            anchor="w",
            wraplength=scaled_pixels(self.window, 430),
            justify="left",
        )
        self.error_label.pack(fill="x", padx=21, pady=(10, 0))

        actions = tk.Frame(self.window, bg=COLORS["raised"])
        actions.pack(side="bottom", fill="x", padx=20, pady=15)
        flat_button(
            actions, "确定", self.confirm, kind="primary", padx=18, pady=7
        ).pack(side="right")
        flat_button(
            actions,
            "取消",
            self.cancel,
            kind="ghost",
            bg=COLORS["raised"],
            padx=14,
            pady=7,
        ).pack(side="right", padx=(0, 8))

    def _build_recorder_row(self, kind: str, label: str) -> None:
        row = tk.Frame(self.window, bg=COLORS["sunken"])
        row.pack(fill="x", padx=20, pady=(0, 8))

        tk.Label(
            row,
            text=label,
            width=9,
            bg=COLORS["sunken"],
            fg=COLORS["text"],
            font=FONTS["label"],
            anchor="w",
        ).pack(side="left", padx=(16, 4), pady=22)

        recorder = tk.Frame(
            row,
            bg=COLORS["surface"],
            highlightthickness=1,
            highlightbackground=COLORS["line_strong"],
        )
        recorder.pack(side="right", fill="x", expand=True, padx=12, pady=12)

        labels = tk.Frame(recorder, bg=COLORS["surface"])
        labels.pack(side="left", fill="both", expand=True, padx=12, pady=7)
        instruction = tk.Label(
            labels,
            text="点击录制，然后按下新快捷键",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=FONTS["caption"],
            anchor="w",
        )
        instruction.pack(fill="x")
        hotkey_label = tk.Label(
            labels,
            text=self.candidates[kind].display,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            font=KEYCAP_FONT,
            anchor="w",
        )
        hotkey_label.pack(fill="x")

        record_button = flat_button(
            recorder,
            "录制",
            lambda selected_kind=kind: self.begin_recording(selected_kind),
            kind="quiet",
            bg=COLORS["surface"],
            padx=14,
            pady=8,
        )
        record_button.pack(side="right", padx=8, pady=8)
        self._instructions[kind] = instruction
        self._hotkey_labels[kind] = hotkey_label
        self._record_buttons[kind] = record_button

    def begin_recording(self, kind: str = "translation") -> None:
        if kind not in self.candidates:
            raise ValueError(f"未知快捷键类型: {kind}")
        previous_kind = self.recording_kind
        if previous_kind and previous_kind != kind:
            self._instructions[previous_kind].configure(
                text="点击录制，然后按下新快捷键", fg=COLORS["muted"]
            )
            self._hotkey_labels[previous_kind].configure(
                text=self.candidates[previous_kind].display
            )
            self._record_buttons[previous_kind].configure(
                text="录制", state="normal"
            )
        self.recording_kind = kind
        self._instructions[kind].configure(
            text="请按下组合键…", fg=COLORS["accent"]
        )
        self._hotkey_labels[kind].configure(text="等待按键")
        self._record_buttons[kind].configure(text="录制中…", state="disabled")
        self.error_label.configure(text="至少包含 Ctrl、Alt、Shift 之一。", fg=COLORS["muted"])
        self.window.focus_force()

    def _on_key_press(self, event: tk.Event[tk.Misc]) -> str | None:
        kind = self.recording_kind
        if kind is None:
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
            candidate = HotkeySpec(tuple(modifiers), keysym)
        except ValueError as exc:
            self.error_label.configure(text=str(exc), fg=COLORS["danger"])
            return "break"

        other_kind = "ocr" if kind == "translation" else "translation"
        if candidate == self.candidates[other_kind]:
            self.error_label.configure(
                text="划词翻译和 OCR 翻译不能使用相同快捷键",
                fg=COLORS["danger"],
            )
            return "break"

        self.candidates[kind] = candidate
        self.recording_kind = None
        self._instructions[kind].configure(text="新快捷键", fg=COLORS["muted"])
        self._hotkey_labels[kind].configure(text=candidate.display)
        self._record_buttons[kind].configure(text="重新录制", state="normal")
        self.error_label.configure(
            text="点击确定后立即生效。", fg=COLORS["muted"]
        )
        return "break"

    def confirm(self) -> None:
        success, message = self.app.apply_hotkeys(
            self.candidates["translation"],
            self.candidates["ocr"],
            persist=True,
        )
        if not success:
            self.error_label.configure(text=message or "快捷键设置失败", fg=COLORS["danger"])
            return
        self._finished = True
        self.window.destroy()
        self.app._settings_dialog = None

    def cancel(self) -> None:
        if self._finished:
            return
        self.app.apply_hotkeys(
            self.app.hotkey_spec,
            self.app.ocr_hotkey_spec,
            persist=False,
        )
        self._finished = True
        self.window.destroy()
        self.app._settings_dialog = None


class TranslatorApp:
    WIDTH = 560
    HEIGHT = 540
    MIN_WIDTH = 400
    MIN_HEIGHT = 420
    RESIZE_BORDER = 6
    RESIZE_CORNER = 8
    PROGRESS_INTERVAL_MS = 16

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
        self._ocr_pending = False
        self._ocr_restore_on_cancel = False
        self._ocr_selector: OcrRegionSelector | None = None
        self._clipboard_sequence = 0
        self._clipboard_deadline = 0.0
        self._progress_offset = -MARQUEE_SPAN
        self._progress_running = False
        self._math_preview = True
        self._rendered_math: dict[str, str] = {}
        self._math_results: queue.Queue[tuple[str, str]] = queue.Queue()
        self._math_dpi = float(root.winfo_fpixels("1i"))
        settings = load_settings()
        self.hotkey_spec = settings.hotkey
        self.ocr_hotkey_spec = settings.ocr_hotkey
        self._position_pinned = settings.position_pinned
        self._fixed_position = settings.window_position
        self._saved_window_size = settings.window_size
        self._icon_path = resource_path("assets/translator_icon.ico")
        self._hotkey_events: queue.Queue[str] = queue.Queue()
        self._hotkey_manager = GlobalHotkey(
            self._hotkey_events,
            event_name="translate",
            thread_name="TranslatorSelectionHotkey",
        )
        self._ocr_hotkey_manager = GlobalHotkey(
            self._hotkey_events,
            event_name="ocr",
            hotkey_id=OCR_HOTKEY_ID,
            thread_name="TranslatorOcrHotkey",
        )
        self._mouse_events: queue.Queue[tuple[int, int]] = queue.Queue()
        self._mouse_monitor = GlobalMouseClick(self._mouse_events)
        self._tray_events: queue.Queue[str] = queue.Queue()
        self._tray = SystemTray(self._tray_events, icon_path=self._icon_path)
        self._settings_dialog: HotkeySettingsDialog | None = None
        self._results: queue.Queue[tuple[int, TranslationResult | None, str | None]] = (
            queue.Queue()
        )
        self._ocr_results: queue.Queue[tuple[str | None, str | None]] = queue.Queue()

        self._configure_window()
        self._configure_styles()
        self._build_ui()
        self._bind_shortcuts()
        self._set_placeholder()
        self._initialize_hotkey()
        self._initialize_tray()
        self._initialize_mouse_monitor()
        self._poll_results()
        self._poll_ocr_results()
        self._poll_hotkey_events()
        self._poll_tray_events()
        self._poll_mouse_events()

    def _scale(self, value: int) -> int:
        return scaled_pixels(self.root, value)

    def _configure_window(self) -> None:
        self.root.title("Translator")
        if self._icon_path.is_file():
            try:
                self.root.iconbitmap(default=str(self._icon_path))
            except tk.TclError:
                pass
        self.root.overrideredirect(not self._decorated)
        self.root.configure(bg=COLORS["line_strong"])
        self.root.attributes("-topmost", True)

        # Shadow the class-level design pixels with physical ones so every
        # later geometry check (minimum size, resize clamping) speaks the same
        # units as the window itself.
        self.MIN_WIDTH = self._scale(TranslatorApp.MIN_WIDTH)
        self.MIN_HEIGHT = self._scale(TranslatorApp.MIN_HEIGHT)
        self.root.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)

        requested_width, requested_height = self._saved_window_size or (
            self._scale(TranslatorApp.WIDTH),
            self._scale(TranslatorApp.HEIGHT),
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

    def _set_automation_state(self, state: str) -> None:
        """Expose non-sensitive OCR state only in decorated UI test mode."""
        if self._decorated:
            self.root.title(f"Translator [{state}]")

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
        configure_ttk_styles(self.root)

    def _build_ui(self) -> None:
        self.surface = tk.Frame(self.root, bg=COLORS["raised"])
        self.surface.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_progress_bar()
        self._build_titlebar()
        separator(self.surface).pack(fill="x")
        self._build_input_section()

        self.footer_status = tk.Label(
            self.surface,
            text=self._ready_status(),
            bg=COLORS["raised"],
            fg=COLORS["muted"],
            font=FONTS["caption"],
            anchor="w",
        )
        self.footer_status.pack(side="bottom", fill="x", padx=14, pady=(5, 8))
        separator(self.surface).pack(side="bottom", fill="x")

        self._build_result_section()
        self._build_resize_handles()

    def _build_progress_bar(self) -> None:
        """A two-pixel marquee that only exists while a request is in flight."""
        self.progress_track = tk.Frame(
            self.surface, height=self._scale(2), bg=COLORS["raised"], bd=0,
            highlightthickness=0
        )
        self.progress_track.pack(fill="x")
        self.progress_track.pack_propagate(False)
        self.progress_thumb = tk.Frame(self.progress_track, bg=COLORS["accent"], bd=0)

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
                bg=COLORS["raised"],
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
        titlebar = tk.Frame(self.surface, bg=COLORS["raised"], height=self._scale(34))
        titlebar.pack(fill="x", padx=8, pady=(3, 2))
        titlebar.pack_propagate(False)

        self.pin_button = flat_button(
            titlebar,
            "\ue718",
            self.toggle_position_pin,
            kind="ghost",
            bg=COLORS["raised"],
            padx=0,
            pady=4,
            width=3,
        )
        self.pin_button.configure(font=ICON_FONT)
        self.pin_button.pack(side="left", padx=(0, 8), pady=3)
        self._update_position_pin_style()

        title = tk.Label(
            titlebar,
            text="Translator",
            bg=COLORS["raised"],
            fg=COLORS["text"],
            font=FONTS["title"],
        )
        title.pack(side="left", pady=6)

        flat_button(
            titlebar,
            "×",
            self.hide_window,
            kind="ghost",
            bg=COLORS["raised"],
            padx=0,
            pady=4,
            width=3,
        ).pack(side="right", pady=3)

        flat_button(
            titlebar,
            "设置",
            self.open_settings,
            kind="ghost",
            bg=COLORS["raised"],
            padx=9,
            pady=4,
        ).pack(side="right", padx=(0, 4), pady=3)

        for widget in (titlebar, title):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag_window)
            widget.bind("<ButtonRelease-1>", self._finish_drag)

    def _build_input_section(self) -> None:
        section = tk.Frame(self.surface, bg=COLORS["sunken"])
        section.pack(fill="x")

        heading = tk.Frame(section, bg=COLORS["sunken"])
        heading.pack(fill="x", padx=13, pady=(8, 0))
        tk.Label(
            heading,
            text="原文",
            bg=COLORS["sunken"],
            fg=COLORS["muted"],
            font=FONTS["label"],
        ).pack(side="left")

        # The heading's dead middle carries the two low-stakes text actions, so
        # the control row below stays legible at the minimum window width.
        flat_button(
            heading,
            "粘贴",
            self.paste_and_translate,
            kind="quiet",
            padx=7,
            pady=2,
        ).pack(side="left", padx=(12, 0))
        flat_button(
            heading, "清空", self.clear, kind="quiet", padx=7, pady=2
        ).pack(side="left", padx=(2, 0))
        flat_button(
            heading, "复制", self.copy_source, kind="quiet", padx=7, pady=2
        ).pack(side="left", padx=(2, 0))
        self.math_mode_button = flat_button(
            heading, "LaTeX", self.toggle_math_view, kind="quiet", padx=7, pady=2
        )
        self.math_mode_button.pack(side="left", padx=(2, 0))

        self.counter_label = tk.Label(
            heading,
            text=f"0 / {MAX_TEXT_LENGTH:,}",
            bg=COLORS["sunken"],
            fg=COLORS["faint"],
            font=FONTS["caption"],
        )
        self.counter_label.pack(side="right")

        source_area = scrolling_text(
            section,
            font_role="content",
            height=3,
            background=COLORS["sunken"],
            padx=13,
            pady=6,
            focus_ring=True,
            undo=True,
        )
        source_area.container.pack(fill="x", padx=1)
        self.source_text = source_area.text
        self._source_view = MathTextView(self.source_text)
        self.source_text.bind("<<Copy>>", self._source_view.copy_selection)
        self.source_text.bind("<<Cut>>", self._source_view.cut_selection)

        controls = tk.Frame(section, bg=COLORS["sunken"])
        controls.pack(fill="x", padx=13, pady=(4, 9))

        source_labels = [language.label for language in SOURCE_LANGUAGES]
        target_labels = [language.label for language in TARGET_LANGUAGES]
        self.source_language = ttk.Combobox(
            controls,
            values=source_labels,
            state="readonly",
            style=COMBOBOX_STYLE,
            width=12,
        )
        self.source_language.set(source_labels[0])
        self.source_language.pack(side="left")

        flat_button(
            controls, "⇄", self.swap_languages, kind="quiet", padx=0, width=3
        ).pack(side="left", padx=5)

        self.target_language = ttk.Combobox(
            controls,
            values=target_labels,
            state="readonly",
            style=COMBOBOX_STYLE,
            width=12,
        )
        self.target_language.set("中文（简体）")
        self.target_language.pack(side="left")

        self.translate_button = flat_button(
            controls, "翻译", self.translate_now, kind="primary", padx=15, pady=6
        )
        self.translate_button.pack(side="right")

        self.source_text.bind("<FocusIn>", self._remove_placeholder)
        self.source_text.bind("<FocusOut>", self._restore_placeholder_if_empty)
        self.source_text.bind("<KeyRelease>", self._update_counter)

    def _build_result_section(self) -> None:
        separator(self.surface).pack(fill="x")
        section = tk.Frame(self.surface, bg=COLORS["surface"])
        section.pack(fill="both", expand=True)

        meta_row = tk.Frame(section, bg=COLORS["surface"])
        meta_row.pack(fill="x", padx=13, pady=(8, 0))
        tk.Label(
            meta_row,
            text="Google Translate",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=FONTS["label"],
        ).pack(side="left")
        self.provider_meta = tk.Label(
            meta_row,
            text="等待输入",
            bg=COLORS["surface"],
            fg=COLORS["faint"],
            font=FONTS["caption"],
        )
        self.provider_meta.pack(side="left", padx=(8, 0))

        self.copy_button = flat_button(
            meta_row, "复制译文", self.copy_result, kind="accent", padx=10, pady=3
        )
        self.copy_button.pack(side="right")
        self.copy_button.configure(state="disabled")

        result_area = scrolling_text(
            section,
            font_role="result",
            height=2,
            background=COLORS["surface"],
            padx=13,
            pady=8,
            state="disabled",
            cursor="arrow",
        )
        result_area.container.pack(fill="both", expand=True)
        self.result_text = result_area.text
        self._result_view = MathTextView(self.result_text)
        self.result_text.bind("<<Copy>>", self._result_view.copy_selection)

    def _bind_shortcuts(self) -> None:
        self.root.bind_all("<Control-Return>", self.translate_now)
        self.root.bind_all("<Control-KP_Enter>", self.translate_now)
        self.root.bind_all("<Control-l>", self.focus_input)
        self.root.bind_all("<Escape>", lambda _event: self.hide_window())

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
            self.ocr_hotkey_spec,
        )

    def _ready_status(self, prefix: str = "就绪") -> str:
        return (
            f"{prefix}  ·  {self.hotkey_spec.display} 划词  ·  "
            f"{self.ocr_hotkey_spec.display} OCR  ·  Ctrl+Enter 翻译"
        )

    def _persist_settings(self) -> None:
        save_settings(self._current_settings())

    def _update_position_pin_style(self) -> None:
        if self._position_pinned:
            restyle_button(self.pin_button, "accent")
        else:
            restyle_button(self.pin_button, "ghost", bg=COLORS["raised"])

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
        """Backward-compatible wrapper for changing only the selection hotkey."""
        return self.apply_hotkeys(spec, self.ocr_hotkey_spec, persist=persist)

    def _start_hotkey_pair(
        self,
        translation_spec: HotkeySpec,
        ocr_spec: HotkeySpec,
    ) -> tuple[bool, str | None]:
        self._hotkey_manager.stop()
        self._ocr_hotkey_manager.stop()
        success, error = self._hotkey_manager.start(translation_spec)
        if not success:
            return False, error
        success, error = self._ocr_hotkey_manager.start(ocr_spec)
        if not success:
            self._hotkey_manager.stop()
            return False, error
        return True, None

    def apply_hotkeys(
        self,
        translation_spec: HotkeySpec,
        ocr_spec: HotkeySpec,
        *,
        persist: bool,
    ) -> tuple[bool, str | None]:
        if translation_spec == ocr_spec:
            message = "划词翻译和 OCR 翻译不能使用相同快捷键"
            self.footer_status.configure(text=message, fg=COLORS["danger"])
            return False, message

        previous_translation = self.hotkey_spec
        previous_ocr = self.ocr_hotkey_spec
        success, error = self._start_hotkey_pair(translation_spec, ocr_spec)
        if not success:
            restored, restore_error = self._start_hotkey_pair(
                previous_translation, previous_ocr
            )
            message = error or "全局快捷键注册失败"
            if not restored:
                message = (
                    f"{message}；原快捷键也未能恢复: "
                    f"{restore_error or '未知错误'}"
                )
            self.footer_status.configure(text=message, fg=COLORS["danger"])
            return False, message

        self.hotkey_spec = translation_spec
        self.ocr_hotkey_spec = ocr_spec
        warning: str | None = None
        if persist:
            try:
                self._persist_settings()
            except OSError as exc:
                warning = f"快捷键已生效，但设置无法保存: {exc}"

        self.footer_status.configure(
            text=self._ready_status(),
            fg=COLORS["muted"] if not warning else COLORS["danger"],
        )
        return True, warning

    @staticmethod
    def _start_available_hotkey(
        manager: GlobalHotkey,
        preferred: HotkeySpec,
        fallbacks: tuple[HotkeySpec, ...],
        *,
        excluded: set[HotkeySpec] | None = None,
    ) -> tuple[HotkeySpec | None, str | None]:
        last_error: str | None = None
        seen: set[HotkeySpec] = set(excluded or ())
        for candidate in (preferred, *fallbacks):
            if candidate in seen:
                continue
            seen.add(candidate)
            success, error = manager.start(candidate)
            if success:
                return candidate, None
            last_error = error
        return None, last_error

    def _initialize_hotkey(self) -> None:
        preferred_translation = self.hotkey_spec
        preferred_ocr = self.ocr_hotkey_spec
        translation, translation_error = self._start_available_hotkey(
            self._hotkey_manager,
            preferred_translation,
            HOTKEY_FALLBACKS,
        )
        if translation is not None:
            self.hotkey_spec = translation

        ocr, ocr_error = self._start_available_hotkey(
            self._ocr_hotkey_manager,
            preferred_ocr,
            OCR_HOTKEY_FALLBACKS,
            excluded={translation} if translation is not None else None,
        )
        if ocr is not None:
            self.ocr_hotkey_spec = ocr

        errors: list[str] = []
        if translation is None:
            errors.append(translation_error or "没有可用的划词快捷键")
        if ocr is None:
            errors.append(ocr_error or "没有可用的 OCR 快捷键")
        if errors:
            self.footer_status.configure(
                text="；".join(errors), fg=COLORS["danger"]
            )
            return

        fallbacks: list[str] = []
        if translation != preferred_translation:
            fallbacks.append(
                f"{preferred_translation.display} 已占用，划词改用 {translation.display}"
            )
        if ocr != preferred_ocr:
            fallbacks.append(
                f"{preferred_ocr.display} 已占用，OCR 改用 {ocr.display}"
            )
        self.footer_status.configure(
            text="；".join(fallbacks) if fallbacks else self._ready_status(),
            fg=COLORS["accent"] if fallbacks else COLORS["muted"],
        )

    def open_settings(self) -> None:
        if self._settings_dialog and self._settings_dialog.window.winfo_exists():
            self._settings_dialog.window.deiconify()
            self._settings_dialog.window.lift()
            self._settings_dialog.window.focus_force()
            return
        self._hotkey_manager.stop()
        self._ocr_hotkey_manager.stop()
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
                if (
                    event == "translate"
                    and not self._capture_pending
                    and not self._ocr_pending
                ):
                    self._capture_pending = True
                    self.root.after(80, self._begin_selection_capture)
                elif (
                    event == "ocr"
                    and not self._capture_pending
                    and not self._ocr_pending
                ):
                    self._ocr_pending = True
                    self.root.after(80, self._begin_ocr_capture)
        except queue.Empty:
            pass
        self.root.after(60, self._poll_hotkey_events)

    def _begin_ocr_capture(self) -> None:
        if self._closed or not self._ocr_pending:
            return
        self._set_automation_state("ocr-selecting")
        self._ocr_restore_on_cancel = self.root.state() != "withdrawn"
        self.root.withdraw()
        self.root.update_idletasks()
        self._discard_mouse_events()
        self.root.after(100, self._show_ocr_selector)

    def _show_ocr_selector(self) -> None:
        if self._closed or not self._ocr_pending:
            return
        try:
            self._ocr_selector = OcrRegionSelector(
                self.root,
                self._start_ocr_recognition,
                self._cancel_ocr_capture,
                decorated=self._decorated,
            )
        except (OSError, tk.TclError, ValueError) as exc:
            self._cancel_ocr_capture(f"无法打开 OCR 选区: {exc}")

    def _start_ocr_recognition(self, region: ScreenRegion) -> None:
        self._ocr_selector = None
        if self._closed or not self._ocr_pending:
            return
        self._set_automation_state("ocr-recognizing")
        language = self._language_code(self.source_language.get(), SOURCE_LANGUAGES)
        thread = threading.Thread(
            target=self._ocr_worker,
            args=(region, language),
            daemon=True,
            name="TranslatorWindowsOcr",
        )
        thread.start()

    def _cancel_ocr_capture(self, error: str | None) -> None:
        restore_window = self._ocr_restore_on_cancel
        self._ocr_pending = False
        self._ocr_restore_on_cancel = False
        self._ocr_selector = None
        self._discard_mouse_events()
        if self._closed:
            return
        if error:
            self._show_near_cursor()
            self._show_ocr_error(error)
        elif restore_window:
            self.show_window()

    def _ocr_worker(self, region: ScreenRegion, language: str = "auto") -> None:
        try:
            text = recognize_screen_region(region, language=language)
            self._prepare_math(text)
        except WindowsOcrError as exc:
            self._ocr_results.put((None, str(exc)))
        except Exception as exc:  # Keep the UI alive on native/runtime failures.
            self._ocr_results.put((None, f"OCR 失败: {exc}"))
        else:
            self._ocr_results.put((text, None))

    def _poll_ocr_results(self) -> None:
        if self._closed:
            return
        try:
            while True:
                text, error = self._ocr_results.get_nowait()
                if not self._ocr_pending:
                    continue
                self._ocr_pending = False
                self._ocr_restore_on_cancel = False
                self._discard_mouse_events()
                if error:
                    self._set_automation_state("ocr-error")
                    self._show_near_cursor()
                    self._show_ocr_error(error)
                elif not text or not text.strip():
                    self._set_automation_state("ocr-empty")
                    self._show_near_cursor()
                    self._show_ocr_error("选区内没有识别到文字，请框选更清晰的文字区域")
                else:
                    self._set_automation_state("ocr-recognized")
                    self._accept_selected_text(text.strip())
        except queue.Empty:
            pass
        self.root.after(60, self._poll_ocr_results)

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
        self._set_input_text(selected_text)
        self._show_result("")
        if self._busy:
            # A new global capture supersedes an older in-flight translation.
            # translate_now increments the request id, so the old result is ignored.
            self._set_busy(False)
        self.translate_now()

    def _set_placeholder(self) -> None:
        self._placeholder_active = True
        self.source_text.configure(fg=COLORS["faint"])
        self._source_view.set_content(PLACEHOLDER)

    def _remove_placeholder(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if not self._placeholder_active:
            return
        self._source_view.set_content("")
        self.source_text.configure(fg=COLORS["text"])
        self._placeholder_active = False
        self._update_counter()

    def _restore_placeholder_if_empty(
        self, _event: tk.Event[tk.Misc] | None = None
    ) -> None:
        if not self._placeholder_active and not self._source_view.get_content().strip():
            self._set_placeholder()
            self._update_counter()

    def _input_text(self) -> str:
        if self._placeholder_active:
            return ""
        return self._source_view.get_content().strip()

    def _set_input_text(self, text: str) -> None:
        self._placeholder_active = False
        self.source_text.configure(fg=COLORS["text"])
        # Never cut halfway through LaTeX. The client reports an over-limit
        # document so the user can shorten it without losing a formula.
        if not any(is_math for is_math, _part in split_math_parts(text)):
            text = text[:MAX_TEXT_LENGTH]
        self._source_view.set_content(text, self._math_images())
        self._update_counter()

    def _math_images(self) -> dict[str, str]:
        return self._rendered_math if self._math_preview else {}

    def _prepare_math(self, text: str) -> None:
        """Prepare image bytes off the Tk thread; LaTeX remains authoritative."""
        if len(text) > MAX_TEXT_LENGTH:
            return
        cached = getattr(self, "_rendered_math", {})
        missing = list(dict.fromkeys(
            part for is_math, part in split_math_parts(text)
            if is_math and part not in cached
        ))
        if not missing:
            return
        images = render_formulas(
            "\n".join(missing), dpi=getattr(self, "_math_dpi", 144),
            font_size=FONTS["content"][1],
        )
        if not images:
            return
        if not hasattr(self, "_rendered_math"):
            self._rendered_math = {}
        self._rendered_math.update(images)
        while len(self._rendered_math) > 96:
            del self._rendered_math[next(iter(self._rendered_math))]

    def toggle_math_view(self) -> None:
        source = self._input_text()
        result = self._result_view.get_content()
        self._math_preview = not self._math_preview
        self.math_mode_button.configure(text="LaTeX" if self._math_preview else "公式")
        if not self._placeholder_active:
            self._source_view.set_content(source, self._math_images())
        self._result_view.set_content(result, self._math_images())
        if self._math_preview and any(
            is_math and part not in self._rendered_math
            for is_math, part in split_math_parts(source + "\n" + result)
        ):
            threading.Thread(
                target=self._math_preview_worker, args=(source, result),
                daemon=True, name="TranslatorMathPreview",
            ).start()

    def _math_preview_worker(self, source: str, result: str) -> None:
        self._prepare_math(source)
        self._prepare_math(result)
        self._math_results.put((source, result))

    def _poll_math_previews(self) -> None:
        try:
            while True:
                source, result = self._math_results.get_nowait()
                if self._math_preview:
                    if not self._placeholder_active and source == self._input_text():
                        self._source_view.set_content(source, self._math_images())
                    if result == self._result_view.get_content():
                        self._result_view.set_content(result, self._math_images())
        except queue.Empty:
            pass

    def copy_source(self) -> None:
        text = self._input_text()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.footer_status.configure(
            text="已复制原文（公式保留 LaTeX）", fg=COLORS["muted"]
        )

    def _update_counter(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        length = len(self._input_text())
        self.counter_label.configure(
            text=f"{length:,} / {MAX_TEXT_LENGTH:,}",
            fg=COLORS["warning"] if length >= COUNTER_WARNING_AT else COLORS["faint"],
        )

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

        result = self._result_view.get_content().strip()
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
            text=self._ready_status(),
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
            self._prepare_math(text)
            result = translate_with_math(text, source=source, target=target, timeout=15.0)
        except (GoogleTranslateError, ValueError) as exc:
            self._results.put((request_id, None, str(exc)))
        except Exception as exc:  # Keep the UI alive on unexpected network errors.
            self._results.put((request_id, None, f"翻译失败: {exc}"))
        else:
            self._results.put((request_id, result, None))

    def _poll_results(self) -> None:
        if self._closed:
            return
        self._poll_math_previews()
        try:
            while True:
                request_id, result, error = self._results.get_nowait()
                if request_id != self._request_id:
                    continue
                self._set_busy(False)
                if error:
                    self._show_error(error)
                elif result:
                    current_text = self._input_text()
                    if self._math_preview and any(
                        is_math for is_math, _part in split_math_parts(current_text)
                    ):
                        self._source_view.set_content(current_text, self._math_images())
                    self._show_result(result.text)
                    detected = self._language_label(
                        result.detected_source_language or "auto"
                    )
                    self.provider_meta.configure(
                        text=f"检测到 {detected}", fg=COLORS["accent"]
                    )
                    self.footer_status.configure(
                        text=self._ready_status("翻译完成"),
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
        self._set_progress_running(busy)
        if busy:
            self.provider_meta.configure(text="请求中…", fg=COLORS["accent"])
            self.footer_status.configure(
                text="正在调用 Google Translate…", fg=COLORS["accent"]
            )

    def _set_progress_running(self, running: bool) -> None:
        if running == self._progress_running:
            return
        self._progress_running = running
        if not running:
            self.progress_thumb.place_forget()
            return
        self._progress_offset = -MARQUEE_SPAN
        self.progress_thumb.place(
            relx=self._progress_offset, rely=0, relwidth=MARQUEE_SPAN, relheight=1
        )
        self._tick_progress()

    def _tick_progress(self) -> None:
        if self._closed or not self._progress_running:
            return
        self._progress_offset = advance_marquee(self._progress_offset)
        self.progress_thumb.place_configure(relx=self._progress_offset)
        self.root.after(self.PROGRESS_INTERVAL_MS, self._tick_progress)

    def _show_result(self, text: str, *, color: str | None = None) -> None:
        self.result_text.configure(state="normal", fg=color or COLORS["text"])
        self._result_view.set_content(text, self._math_images())
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

    def _show_ocr_error(self, message: str) -> None:
        self._show_result(message, color=COLORS["danger"])
        self.provider_meta.configure(text="OCR 失败", fg=COLORS["danger"])
        self.footer_status.configure(
            text=f"请按 {self.ocr_hotkey_spec.display} 重新框选文字",
            fg=COLORS["danger"],
        )

    def copy_result(self) -> None:
        text = self._result_view.get_content().strip()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update_idletasks()
        self.copy_button.configure(text="已复制")
        restyle_button(self.copy_button, "success")
        self.root.after(1_200, self._reset_copy_button)

    def _reset_copy_button(self) -> None:
        if self._closed:
            return
        self.copy_button.configure(text="复制译文")
        restyle_button(self.copy_button, "accent")

    def focus_input(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        self.show_window()
        return "break"

    def exit_app(self) -> None:
        self._closed = True
        if self._ocr_selector is not None:
            self._ocr_selector.close()
            self._ocr_selector = None
        self._hotkey_manager.stop()
        self._ocr_hotkey_manager.stop()
        self._mouse_monitor.stop()
        self._tray.stop()
        self.root.destroy()
        close_helper()


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
