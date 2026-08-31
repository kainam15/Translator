import tkinter as tk
import unittest

from translator_lite.desktop.app import HotkeySettingsDialog
from translator_lite.windows.hotkey import (
    DEFAULT_HOTKEY,
    DEFAULT_OCR_HOTKEY,
    HotkeySpec,
)


class _FakeApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.hotkey_spec = DEFAULT_HOTKEY
        self.ocr_hotkey_spec = DEFAULT_OCR_HOTKEY
        self._settings_dialog = None

    def apply_hotkeys(
        self,
        translation_spec: HotkeySpec,
        ocr_spec: HotkeySpec,
        *,
        persist: bool,
    ) -> tuple[bool, str | None]:
        self.hotkey_spec = translation_spec
        self.ocr_hotkey_spec = ocr_spec
        return True, None


def _descendants(widget: tk.Misc):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _bottom_inside(widget: tk.Misc, window: tk.Toplevel) -> int:
    bottom = widget.winfo_y() + widget.winfo_height()
    parent = widget.master
    while parent is not window:
        bottom += parent.winfo_y()
        parent = parent.master
    return bottom


class HotkeySettingsDialogLayoutTests(unittest.TestCase):
    def test_confirm_button_is_visible_at_high_dpi(self) -> None:
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        root.tk.call("tk", "scaling", 2.65)
        root.geometry("720x660+100+100")
        root.update()
        dialog = None
        try:
            dialog = HotkeySettingsDialog(_FakeApp(root))
            dialog.window.attributes("-alpha", 0.0)
            dialog.window.update()
            confirm = next(
                widget
                for widget in _descendants(dialog.window)
                if isinstance(widget, tk.Button) and widget.cget("text") == "确定"
            )

            self.assertGreater(confirm.winfo_width(), 1)
            self.assertLessEqual(
                _bottom_inside(confirm, dialog.window),
                dialog.window.winfo_height(),
            )
            labels = {
                str(widget.cget("text"))
                for widget in _descendants(dialog.window)
                if isinstance(widget, tk.Label)
            }
            self.assertIn("划词翻译", labels)
            self.assertIn("OCR 翻译", labels)
        finally:
            if dialog is not None and dialog.window.winfo_exists():
                dialog.window.destroy()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
