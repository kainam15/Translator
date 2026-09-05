"""Editable Tk text with rendered formulas and lossless LaTeX extraction."""

from __future__ import annotations

from collections.abc import Mapping
import tkinter as tk

from ..math_translation import split_math_parts


class MathTextView:
    """Wrap a Text widget while retaining each embedded image's source LaTeX.

    Extraction uses the widget's current dump, so edited text, moved formula
    positions, selections, and deleted formulas are reflected immediately.
    Bind ``copy_selection`` to ``<<Copy>>`` (or Control-c) when integrating.
    """

    def __init__(self, widget: tk.Text) -> None:
        self.widget = widget
        self._image_latex: dict[str, str] = {}
        self._photos: dict[str, tk.PhotoImage] = {}

    def set_content(
        self, text: str, rendered: Mapping[str, str] | None = None
    ) -> None:
        """Replace the document, rendering supported formulas as inline images."""
        state = str(self.widget.cget("state"))
        if state != "normal":
            self.widget.configure(state="normal")
        try:
            self.widget.delete("1.0", "end")
            self._image_latex.clear()
            self._photos.clear()
            image_data = rendered or {}
            photo_cache: dict[str, tk.PhotoImage] = {}
            for is_math, part in split_math_parts(text):
                png = image_data.get(part) if is_math else None
                if isinstance(png, str) and png:
                    try:
                        photo = photo_cache.get(part)
                        if photo is None:
                            photo = tk.PhotoImage(
                                master=self.widget, data=png, format="png"
                            )
                            photo_cache[part] = photo
                        name = str(self.widget.image_create(
                            "end", image=photo, align="center"
                        ))
                        self._image_latex[name] = part
                        self._photos[name] = photo
                        continue
                    except (tk.TclError, ValueError, TypeError):
                        # Invalid / unavailable PNG support falls back to the
                        # exact LaTeX, preserving the user's editable content.
                        pass
                self.widget.insert("end", part)
            # Old undo records must not restore images whose references were
            # released when replacing the complete document.
            self.widget.edit_reset()
        finally:
            if state != "normal":
                self.widget.configure(state=state)

    def get_content(self, start: str = "1.0", end: str = "end-1c") -> str:
        """Read the current document or range, restoring formula LaTeX."""
        parts: list[str] = []
        for kind, value, _index in self.widget.dump(
            start, end, text=True, image=True
        ):
            if kind == "text":
                parts.append(value)
            elif kind == "image":
                parts.append(self._image_latex.get(value, "\ufffc"))
        return "".join(parts)

    def copy_selection(self, _event: tk.Event | None = None) -> str | None:
        """Copy the current selection with LaTeX and suppress Tk's image loss."""
        ranges = self.widget.tag_ranges("sel")
        if not ranges:
            return None
        text = "".join(
            self.get_content(str(start), str(end))
            for start, end in zip(ranges[::2], ranges[1::2])
        )
        self.widget.clipboard_clear()
        self.widget.clipboard_append(text)
        return "break"

    def cut_selection(self, _event: tk.Event | None = None) -> str | None:
        """Cut text and formulas without losing the formula in the clipboard."""
        if str(self.widget.cget("state")) != "normal":
            return "break"
        ranges = self.widget.tag_ranges("sel")
        if not ranges:
            return None
        self.copy_selection()
        self.widget.edit_separator()
        for start, end in reversed(list(zip(ranges[::2], ranges[1::2]))):
            self.widget.delete(str(start), str(end))
        self.widget.edit_separator()
        return "break"
