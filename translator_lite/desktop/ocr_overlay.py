"""Tkinter screen-region selector used by the OCR global shortcut."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from ..windows.ocr import ScreenRegion, virtual_screen_bounds


MINIMUM_SELECTION_SIZE = 8


def normalize_screen_region(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    minimum_size: int = MINIMUM_SELECTION_SIZE,
) -> ScreenRegion | None:
    """Normalize a drag in screen coordinates, rejecting accidental clicks."""
    left, right = sorted((start[0], end[0]))
    top, bottom = sorted((start[1], end[1]))
    width = right - left
    height = bottom - top
    if width < minimum_size or height < minimum_size:
        return None
    return ScreenRegion(left, top, width, height)


class OcrRegionSelector:
    """A transient virtual-desktop overlay for choosing an OCR rectangle."""

    def __init__(
        self,
        root: tk.Tk,
        on_selected: Callable[[ScreenRegion], None],
        on_cancelled: Callable[[str | None], None],
        *,
        decorated: bool = False,
    ) -> None:
        self.root = root
        self.on_selected = on_selected
        self.on_cancelled = on_cancelled
        self.bounds = virtual_screen_bounds()
        self._start: tuple[int, int] | None = None
        self._rectangle: int | None = None
        self._size_label: int | None = None
        self._finished = False
        self._grabbed = False

        self.window = tk.Toplevel(root)
        self.window.title("Translator OCR")
        self.window.overrideredirect(not decorated)
        self.window.configure(bg="#000000", cursor="crosshair")
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.30)
        self.window.geometry(
            f"{self.bounds.width}x{self.bounds.height}"
            f"{self.bounds.left:+d}{self.bounds.top:+d}"
        )

        self.canvas = tk.Canvas(
            self.window,
            bg="#000000",
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)
        self._instruction = self.canvas.create_text(
            self.bounds.width // 2,
            max(42, self.bounds.height // 8),
            text="拖动选择 OCR 区域  ·  Esc 或右键取消",
            fill="#FFFFFF",
            font=("Microsoft YaHei UI", 13, "bold"),
        )

        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._finish_drag)
        self.window.bind("<Escape>", self.cancel)
        self.window.bind("<ButtonPress-3>", self.cancel)
        self.window.bind("<FocusOut>", self._restore_focus)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.window.update_idletasks()
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        try:
            self.window.grab_set_global()
            self._grabbed = True
        except tk.TclError:
            self.close()
            root.after(0, lambda: on_cancelled("无法接管鼠标以选择 OCR 区域"))

    def _restore_focus(self, _event: tk.Event[tk.Misc]) -> None:
        if not self._finished:
            self.window.after(0, self.window.focus_force)

    def _screen_point(self, event: tk.Event[tk.Misc]) -> tuple[int, int]:
        x = max(self.bounds.left, min(int(event.x_root), self.bounds.right - 1))
        y = max(self.bounds.top, min(int(event.y_root), self.bounds.bottom - 1))
        return x, y

    def _canvas_point(self, point: tuple[int, int]) -> tuple[int, int]:
        return point[0] - self.bounds.left, point[1] - self.bounds.top

    def _start_drag(self, event: tk.Event[tk.Misc]) -> str:
        self._start = self._screen_point(event)
        self.canvas.itemconfigure(self._instruction, state="hidden")
        if self._rectangle is not None:
            self.canvas.delete(self._rectangle)
        if self._size_label is not None:
            self.canvas.delete(self._size_label)
        start_x, start_y = self._canvas_point(self._start)
        self._rectangle = self.canvas.create_rectangle(
            start_x,
            start_y,
            start_x,
            start_y,
            outline="#65B8FF",
            fill="#1877C9",
            stipple="gray25",
            width=3,
        )
        self._size_label = self.canvas.create_text(
            start_x + 8,
            start_y + 8,
            text="",
            anchor="nw",
            fill="#FFFFFF",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        return "break"

    def _drag(self, event: tk.Event[tk.Misc]) -> str:
        if self._start is None or self._rectangle is None:
            return "break"
        current = self._screen_point(event)
        start_x, start_y = self._canvas_point(self._start)
        current_x, current_y = self._canvas_point(current)
        self.canvas.coords(
            self._rectangle,
            start_x,
            start_y,
            current_x,
            current_y,
        )
        if self._size_label is not None:
            width = abs(current[0] - self._start[0])
            height = abs(current[1] - self._start[1])
            label_x = min(start_x, current_x) + 8
            label_y = min(start_y, current_y) + 8
            self.canvas.coords(self._size_label, label_x, label_y)
            self.canvas.itemconfigure(
                self._size_label, text=f"{width} × {height}"
            )
        return "break"

    def _finish_drag(self, event: tk.Event[tk.Misc]) -> str:
        if self._start is None:
            return "break"
        region = normalize_screen_region(self._start, self._screen_point(event))
        if region is None:
            self._start = None
            self.canvas.itemconfigure(self._instruction, state="normal")
            if self._rectangle is not None:
                self.canvas.delete(self._rectangle)
                self._rectangle = None
            if self._size_label is not None:
                self.canvas.delete(self._size_label)
                self._size_label = None
            return "break"

        self.close()
        # Let DWM remove the translucent overlay before BitBlt captures pixels.
        self.root.after(120, lambda: self.on_selected(region))
        return "break"

    def cancel(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if self._finished:
            return "break"
        self.close()
        self.root.after(0, lambda: self.on_cancelled(None))
        return "break"

    def close(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._grabbed:
            try:
                self.window.grab_release()
            except tk.TclError:
                pass
            self._grabbed = False
        try:
            self.window.destroy()
        except tk.TclError:
            pass
