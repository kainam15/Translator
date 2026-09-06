from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, call, patch

from translator_lite.desktop.app import TranslatorApp


class DesktopWindowDismissTests(unittest.TestCase):
    def _app(self) -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app.root = Mock()
        app._closed = False
        app._presentation_after_id = None
        app._presentation_hidden = False
        app.hide_window = Mock(return_value="break")
        app.root.state.return_value = "normal"
        return app

    @patch(
        "translator_lite.desktop.app.window_at_point_is_current_process",
        return_value=False,
    )
    def test_global_click_in_another_process_hides_visible_window(
        self, _target_check: Mock
    ) -> None:
        app = self._app()
        app._settings_dialog = None

        app._handle_global_mouse_click(120, 80)

        app.hide_window.assert_called_once_with()

    @patch(
        "translator_lite.desktop.app.window_at_point_is_current_process",
        return_value=True,
    )
    def test_global_click_in_translator_keeps_window_visible(
        self, _target_check: Mock
    ) -> None:
        app = self._app()
        app._settings_dialog = None

        app._handle_global_mouse_click(120, 80)

        app.hide_window.assert_not_called()

    @patch(
        "translator_lite.desktop.app.window_at_point_is_current_process",
        return_value=False,
    )
    def test_settings_dialog_disables_click_outside_dismissal(
        self, _target_check: Mock
    ) -> None:
        app = self._app()
        app._settings_dialog = Mock()
        app._settings_dialog.window.winfo_exists.return_value = True

        app._handle_global_mouse_click(120, 80)

        _target_check.assert_not_called()
        app.hide_window.assert_not_called()

    @patch(
        "translator_lite.desktop.app.window_at_point_is_current_process",
        return_value=False,
    )
    def test_global_click_is_ignored_when_window_is_already_hidden(
        self, _target_check: Mock
    ) -> None:
        app = self._app()
        app._settings_dialog = None
        app.root.state.return_value = "withdrawn"

        app._handle_global_mouse_click(120, 80)

        _target_check.assert_not_called()
        app.hide_window.assert_not_called()


class DesktopWindowMotionTests(unittest.TestCase):
    def _app(self) -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app.root = Mock()
        app.root.winfo_id.return_value = 123
        app._drag_offset = (20, 30)
        app._resize_edge = "se"
        app._resize_start_pointer = (100, 100)
        app._resize_start_geometry = (40, 50, 720, 660)
        app._resize_after_id = None
        app._resize_layout_after_id = None
        app._pending_resize_pointer = None
        app._presentation_after_id = None
        app._presentation_hidden = False
        app.root.after.return_value = "resize-frame"
        app.root.after_idle.return_value = "resize-layout"
        app._position_pinned = False
        app._persist_settings = Mock()
        return app

    @patch(
        "translator_lite.desktop.app.set_window_position",
        return_value=True,
    )
    def test_drag_uses_native_positioning_without_tk_geometry(
        self, set_position: Mock
    ) -> None:
        app = self._app()

        app._drag_window(SimpleNamespace(x_root=220, y_root=330))

        set_position.assert_called_once_with(123, 200, 300)
        app.root.geometry.assert_not_called()

    @patch(
        "translator_lite.desktop.app.set_window_position",
        return_value=False,
    )
    def test_drag_falls_back_to_tk_geometry(
        self, set_position: Mock
    ) -> None:
        app = self._app()

        app._drag_window(SimpleNamespace(x_root=220, y_root=330))

        set_position.assert_called_once_with(123, 200, 300)
        app.root.geometry.assert_called_once_with("+200+300")

    @patch(
        "translator_lite.desktop.app.set_window_bounds",
        return_value=True,
    )
    def test_resize_queues_native_bounds_without_tk_geometry(
        self, set_bounds: Mock
    ) -> None:
        app = self._app()

        app._resize_window(SimpleNamespace(x_root=180, y_root=160))

        set_bounds.assert_not_called()
        self.assertEqual(app._pending_resize_pointer, (180, 160))
        app.root.after.call_args.args[1]()

        set_bounds.assert_called_once_with(123, 40, 50, 800, 720)
        app.root.geometry.assert_not_called()
        app.root.update_idletasks.assert_not_called()

    @patch("translator_lite.desktop.app.set_window_bounds", return_value=True)
    def test_pointer_burst_commits_only_the_last_requested_geometry(
        self, set_bounds: Mock
    ) -> None:
        app = self._app()

        for x, y in ((120, 120), (150, 140), (180, 160)):
            app._resize_window(SimpleNamespace(x_root=x, y_root=y))

        app.root.after.assert_called_once()
        app.root.after.call_args.args[1]()

        set_bounds.assert_called_once_with(123, 40, 50, 800, 720)
        self.assertIsNone(app._pending_resize_pointer)

    @patch("translator_lite.desktop.app.set_window_bounds", return_value=True)
    def test_next_resize_waits_for_the_previous_layout_idle(
        self, set_bounds: Mock
    ) -> None:
        app = self._app()
        app._resize_window(SimpleNamespace(x_root=140, y_root=130))
        app.root.after.call_args.args[1]()

        app._resize_window(SimpleNamespace(x_root=160, y_root=145))
        app._resize_window(SimpleNamespace(x_root=180, y_root=160))

        self.assertEqual(app.root.after.call_count, 1)
        self.assertEqual(set_bounds.call_count, 1)
        app.root.after_idle.call_args.args[0]()
        self.assertEqual(app.root.after.call_count, 2)
        app.root.after.call_args.args[1]()
        self.assertEqual(set_bounds.call_args, call(123, 40, 50, 800, 720))

    @patch("translator_lite.desktop.app.redraw_window", return_value=True)
    @patch("translator_lite.desktop.app.set_window_bounds", return_value=True)
    def test_release_coordinate_wins_over_the_last_queued_motion(
        self, set_bounds: Mock, _redraw: Mock
    ) -> None:
        app = self._app()
        app._resize_window(SimpleNamespace(x_root=140, y_root=130))

        app._finish_resize(SimpleNamespace(x_root=180, y_root=160))

        set_bounds.assert_called_once_with(123, 40, 50, 800, 720)
        app._persist_settings.assert_called_once_with()

    @patch("translator_lite.desktop.app.redraw_window", return_value=True)
    @patch("translator_lite.desktop.app.set_window_bounds", return_value=True)
    def test_finish_commits_pending_geometry_before_saving_settings(
        self, set_bounds: Mock, _redraw: Mock
    ) -> None:
        app = self._app()
        order = Mock()
        order.attach_mock(set_bounds, "bounds")
        order.attach_mock(app._persist_settings, "save")
        app._resize_window(SimpleNamespace(x_root=180, y_root=160))

        app._finish_resize()

        self.assertEqual(order.mock_calls, [
            call.bounds(123, 40, 50, 800, 720), call.save()
        ])
        app.root.after_cancel.assert_called_once_with("resize-frame")
        self.assertIsNone(app._pending_resize_pointer)
        self.assertIsNone(app._resize_after_id)
        self.assertIsNone(app._resize_edge)

    @patch("translator_lite.desktop.app.redraw_window", return_value=True)
    @patch("translator_lite.desktop.app.set_window_bounds", return_value=True)
    def test_finish_cancels_layout_wait_and_commits_latest_pointer(
        self, set_bounds: Mock, _redraw: Mock
    ) -> None:
        app = self._app()
        app._resize_window(SimpleNamespace(x_root=140, y_root=130))
        app.root.after.call_args.args[1]()
        app._resize_window(SimpleNamespace(x_root=180, y_root=160))

        app._finish_resize()

        app.root.after_cancel.assert_called_once_with("resize-layout")
        self.assertEqual(set_bounds.call_args, call(123, 40, 50, 800, 720))
        self.assertIsNone(app._resize_layout_after_id)

    @patch("translator_lite.desktop.app.set_window_bounds", return_value=False)
    def test_queued_resize_retains_the_tk_geometry_fallback(
        self, _set_bounds: Mock
    ) -> None:
        app = self._app()
        app._resize_window(SimpleNamespace(x_root=180, y_root=160))

        app.root.after.call_args.args[1]()

        app.root.geometry.assert_called_once_with("800x720+40+50")

    @patch("translator_lite.desktop.app.set_window_bounds", return_value=True)
    def test_hide_cancels_pending_resize_and_late_callback_is_harmless(
        self, set_bounds: Mock
    ) -> None:
        app = self._app()
        app._resize_window(SimpleNamespace(x_root=180, y_root=160))
        queued_callback = app.root.after.call_args.args[1]

        app.hide_window()
        queued_callback()

        app.root.after_cancel.assert_called_once_with("resize-frame")
        app.root.withdraw.assert_called_once_with()
        set_bounds.assert_not_called()
        self.assertIsNone(app._pending_resize_pointer)
        self.assertIsNone(app._resize_edge)

    @patch("translator_lite.desktop.app.set_window_bounds", return_value=True)
    def test_hide_cancels_layout_callback_without_scheduling_another_frame(
        self, set_bounds: Mock
    ) -> None:
        app = self._app()
        app._resize_window(SimpleNamespace(x_root=140, y_root=130))
        app.root.after.call_args.args[1]()
        layout_callback = app.root.after_idle.call_args.args[0]
        app._resize_window(SimpleNamespace(x_root=180, y_root=160))

        app.hide_window()
        layout_callback()

        app.root.after_cancel.assert_called_once_with("resize-layout")
        self.assertEqual(app.root.after.call_count, 1)
        self.assertEqual(set_bounds.call_count, 1)

    @patch("translator_lite.desktop.app.redraw_window", return_value=True)
    def test_finishing_resize_forces_one_complete_repaint(
        self, redraw: Mock
    ) -> None:
        app = self._app()

        app._finish_resize()

        redraw.assert_called_once_with(123, immediate=True)
        app._persist_settings.assert_called_once_with()


class DesktopWindowPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        redraw = patch("translator_lite.desktop.app.redraw_window", return_value=True)
        self.redraw_window = redraw.start()
        self.addCleanup(redraw.stop)

    def _app(self, state: str = "withdrawn") -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app.root = Mock()
        app.root.state.return_value = state
        app.root.winfo_id.return_value = 123
        app._closed = False
        app._decorated = True
        app._resize_after_id = None
        app._resize_layout_after_id = None
        app._presentation_after_id = None
        app._presentation_hidden = False
        app.root.after_idle.return_value = "presentation-frame"
        return app

    def test_hidden_window_is_revealed_only_after_mapping_and_complete_layout(self) -> None:
        app = self._app()
        order = Mock()
        order.attach_mock(app.root, "root")

        app._present_window()

        app.root.update.assert_not_called()
        app.root.update_idletasks.assert_not_called()
        self.redraw_window.assert_not_called()
        self.assertNotIn(call("-alpha", 1.0), app.root.attributes.call_args_list)
        self.assertEqual(app._presentation_after_id, "presentation-frame")
        self.assertTrue(app._presentation_hidden)
        app.root.after_idle.call_args.args[0]()

        events = order.mock_calls
        hide_index = events.index(call.root.attributes("-alpha", 0.0))
        map_index = events.index(call.root.deiconify())
        layout_index = events.index(call.root.update_idletasks())
        reveal_index = events.index(call.root.attributes("-alpha", 1.0))
        self.assertLess(hide_index, map_index)
        self.assertLess(map_index, layout_index)
        self.assertLess(layout_index, reveal_index)
        app.root.update_idletasks.assert_called_once_with()
        self.redraw_window.assert_not_called()
        self.assertIsNone(app._presentation_after_id)
        self.assertFalse(app._presentation_hidden)

    def test_layout_failure_does_not_leave_the_window_transparent(self) -> None:
        app = self._app()
        app.root.update_idletasks.side_effect = tk.TclError("layout failed")

        app._present_window()
        with self.assertRaises(tk.TclError):
            app.root.after_idle.call_args.args[0]()

        self.assertEqual(app.root.attributes.call_args, call("-alpha", 1.0))
        self.assertIsNone(app._presentation_after_id)
        self.assertFalse(app._presentation_hidden)

    def test_visible_window_restore_does_not_change_its_opacity(self) -> None:
        app = self._app(state="normal")

        app._present_window()

        self.assertNotIn(call("-alpha", 0.0), app.root.attributes.call_args_list)
        self.assertNotIn(call("-alpha", 1.0), app.root.attributes.call_args_list)
        app.root.update_idletasks.assert_not_called()
        self.redraw_window.assert_not_called()
        app.root.lift.assert_called_once_with()
        app.root.after_idle.assert_not_called()

    def test_mapping_failure_restores_the_window_opacity(self) -> None:
        app = self._app()
        app.root.deiconify.side_effect = tk.TclError("mapping failed")

        with self.assertRaises(tk.TclError):
            app._present_window()

        self.assertEqual(app.root.attributes.call_args, call("-alpha", 1.0))
        self.assertFalse(app._presentation_hidden)

    def test_hide_cancels_pending_reveal_before_restoring_opacity(self) -> None:
        app = self._app()
        app._present_window()
        order = Mock()
        order.attach_mock(app.root, "root")

        app.hide_window()

        app.root.after_cancel.assert_called_once_with("presentation-frame")
        self.assertLess(
            order.mock_calls.index(call.root.withdraw()),
            order.mock_calls.index(call.root.attributes("-alpha", 1.0)),
        )
        self.assertIsNone(app._presentation_after_id)
        self.assertFalse(app._presentation_hidden)
        self.redraw_window.assert_not_called()

    def test_repeated_show_keeps_one_pending_reveal(self) -> None:
        app = self._app()
        app._present_window()
        app.root.state.return_value = "normal"

        app._present_window()

        app.root.after_idle.assert_called_once()
        self.assertEqual(app.root.attributes.call_args_list.count(call("-alpha", 0.0)), 1)
        self.assertNotIn(call("-alpha", 1.0), app.root.attributes.call_args_list)
        self.assertEqual(app._presentation_after_id, "presentation-frame")


if __name__ == "__main__":
    unittest.main()
