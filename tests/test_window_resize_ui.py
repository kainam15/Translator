from types import SimpleNamespace
import tkinter as tk
import unittest

from translator_lite.desktop.app import TranslatorApp


class WindowResizeUiTests(unittest.TestCase):
    def _app(self, root: tk.Tk, *, decorated: bool) -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app.root = root
        app._decorated = decorated
        app._resize_edge = None
        app._resize_start_pointer = (0, 0)
        app._resize_start_geometry = (0, 0, app.WIDTH, app.HEIGHT)
        app._resize_handles = {}
        return app

    def test_borderless_window_has_eight_resize_handles(self) -> None:
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        root.geometry("720x660+100+100")
        root.update()
        try:
            app = self._app(root, decorated=False)

            app._build_resize_handles()
            root.update_idletasks()

            self.assertEqual(
                set(app._resize_handles),
                {"n", "ne", "e", "se", "s", "sw", "w", "nw"},
            )
            self.assertTrue(
                all(
                    handle.winfo_manager() == "place"
                    for handle in app._resize_handles.values()
                )
            )
            self.assertTrue(
                all(
                    handle.bind("<B1-Motion>")
                    for handle in app._resize_handles.values()
                )
            )
        finally:
            root.destroy()

    def test_southeast_drag_resizes_real_tk_window(self) -> None:
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-alpha", 0.0)
        root.minsize(440, 500)
        root.geometry("720x660+100+100")
        root.update()
        try:
            app = self._app(root, decorated=False)
            start = SimpleNamespace(x_root=820, y_root=760)
            current = SimpleNamespace(x_root=900, y_root=820)

            app._start_resize(start, "se")
            app._resize_window(current)
            root.update_idletasks()

            self.assertEqual((root.winfo_width(), root.winfo_height()), (800, 720))
            self.assertEqual((root.winfo_x(), root.winfo_y()), (100, 100))
        finally:
            root.destroy()

    def test_window_size_can_shrink_below_original_default(self) -> None:
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        root.minsize(440, 500)
        root.geometry("500x520+100+100")
        root.update()
        try:
            app = self._app(root, decorated=False)

            self.assertEqual(app._window_size(), (500, 520))
        finally:
            root.destroy()

    def test_decorated_window_uses_system_resize_frame(self) -> None:
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        try:
            app = self._app(root, decorated=True)

            app._build_resize_handles()

            self.assertEqual(app._resize_handles, {})
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
