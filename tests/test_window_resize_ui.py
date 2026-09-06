from types import SimpleNamespace
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from translator_lite.desktop.app import TranslatorApp


class WindowResizeUiTests(unittest.TestCase):
    def _real_app(self, root: tk.Tk) -> TranslatorApp:
        with (
            patch.object(TranslatorApp, "_initialize_hotkey"),
            patch.object(TranslatorApp, "_initialize_tray"),
            patch.object(TranslatorApp, "_initialize_mouse_monitor"),
        ):
            return TranslatorApp(root)

    def test_first_window_map_finishes_child_layout_before_reveal(self) -> None:
        root = tk.Tk()
        app = None
        try:
            app = self._real_app(root)

            self.assertEqual(float(root.attributes("-alpha")), 1.0)
            self.assertEqual(root.state(), "normal")
            self.assertTrue(app.source_text.winfo_viewable())
            self.assertTrue(app.result_text.winfo_viewable())
            self.assertEqual(app.surface.winfo_width(), root.winfo_width() - 2)
            self.assertGreater(app.result_text.winfo_height(), 1)
        finally:
            if app is not None:
                app.exit_app()
            else:
                root.destroy()

    def test_restore_from_tk_callback_maps_text_views_before_revealing(self) -> None:
        root = tk.Tk()
        app = None
        callback_error = []
        root.report_callback_exception = lambda *error: callback_error.append(error)
        try:
            app = self._real_app(root)
            app.hide_window()
            self.assertFalse(app.source_text.winfo_viewable())
            root.after(0, app.show_window)
            # mainloop processes Map events and the reveal idle normally. Its
            # bounded quit also works with the app's recurring queue pollers.
            root.after(500, root.quit)

            root.mainloop()

            self.assertEqual(callback_error, [])
            self.assertEqual(root.state(), "normal")
            self.assertTrue(app.source_text.winfo_viewable())
            self.assertTrue(app.result_text.winfo_viewable())
            self.assertIsNone(app._presentation_after_id)
            self.assertFalse(app._presentation_hidden)
            self.assertEqual(float(root.attributes("-alpha")), 1.0)
            self.assertEqual(app.surface.winfo_width(), root.winfo_width() - 2)
        finally:
            if app is not None:
                app.exit_app()
            else:
                root.destroy()

    def test_hide_before_restore_idle_keeps_the_window_hidden(self) -> None:
        root = tk.Tk()
        app = None
        callback_error = []
        root.report_callback_exception = lambda *error: callback_error.append(error)
        pending_reveal = []
        try:
            app = self._real_app(root)
            app.hide_window()

            def restore_then_hide() -> None:
                app.show_window()
                pending_reveal.append(app._presentation_after_id)
                app.hide_window()

            root.after(0, restore_then_hide)
            root.after(500, root.quit)

            root.mainloop()

            self.assertEqual(callback_error, [])
            self.assertEqual(len(pending_reveal), 1)
            self.assertIsNotNone(pending_reveal[0])
            self.assertEqual(root.state(), "withdrawn")
            self.assertFalse(app.source_text.winfo_viewable())
            self.assertFalse(app.result_text.winfo_viewable())
            self.assertIsNone(app._presentation_after_id)
            self.assertFalse(app._presentation_hidden)
            self.assertEqual(float(root.attributes("-alpha")), 1.0)
        finally:
            if app is not None:
                app.exit_app()
            else:
                root.destroy()

    def _app(self, root: tk.Tk, *, decorated: bool) -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app.root = root
        app._decorated = decorated
        app._resize_edge = None
        app._resize_start_pointer = (0, 0)
        app._resize_start_geometry = (0, 0, app.WIDTH, app.HEIGHT)
        app._resize_handles = {}
        app._resize_after_id = None
        app._resize_layout_after_id = None
        app._pending_resize_pointer = None
        app._presentation_after_id = None
        app._presentation_hidden = False
        app._position_pinned = False
        app._persist_settings = Mock()
        return app

    def _wait_for_resize(self, root: tk.Tk, app: TranslatorApp) -> None:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            root.update()
            if (
                app._resize_after_id is None
                and app._resize_layout_after_id is None
                and app._pending_resize_pointer is None
            ):
                root.update_idletasks()
                return
            time.sleep(0.005)
        self.fail("Resize did not finish its timer and layout callbacks")

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
            self._wait_for_resize(root, app)

            self.assertEqual((root.winfo_width(), root.winfo_height()), (800, 720))
            self.assertEqual((root.winfo_x(), root.winfo_y()), (100, 100))
        finally:
            root.destroy()

    def test_resize_updates_nested_frame_and_text_before_the_next_gesture(self) -> None:
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-alpha", 0.0)
        root.geometry("720x660+100+100")
        outer = tk.Frame(root, borderwidth=0, highlightthickness=0)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, borderwidth=0, highlightthickness=0)
        inner.pack(fill="both", expand=True)
        text = tk.Text(inner, borderwidth=0, highlightthickness=0)
        text.insert("1.0", "Synthetic resize regression content\n" * 8)
        text.pack(fill="both", expand=True)
        root.update()
        try:
            app = self._app(root, decorated=False)
            app._start_resize(SimpleNamespace(x_root=820, y_root=760), "se")
            for x, y in ((860, 790), (900, 820), (980, 880)):
                app._resize_window(SimpleNamespace(x_root=x, y_root=y))

            self._wait_for_resize(root, app)

            for widget in (root, outer, inner, text):
                with self.subTest(widget=widget.winfo_class()):
                    self.assertEqual(
                        (widget.winfo_width(), widget.winfo_height()), (880, 780)
                    )
            app._finish_resize()
            app._persist_settings.assert_called_once_with()
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
