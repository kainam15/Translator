from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from translator_lite.desktop.app import TranslatorApp


class DesktopWindowDismissTests(unittest.TestCase):
    def _app(self) -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app.root = Mock()
        app._closed = False
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
    def test_resize_uses_native_bounds_without_tk_geometry(
        self, set_bounds: Mock
    ) -> None:
        app = self._app()

        app._resize_window(SimpleNamespace(x_root=180, y_root=160))

        set_bounds.assert_called_once_with(123, 40, 50, 800, 720)
        app.root.geometry.assert_not_called()

    @patch("translator_lite.desktop.app.redraw_window", return_value=True)
    def test_finishing_resize_forces_one_complete_repaint(
        self, redraw: Mock
    ) -> None:
        app = self._app()

        app._finish_resize()

        redraw.assert_called_once_with(123, immediate=True)
        app._persist_settings.assert_called_once_with()

if __name__ == "__main__":
    unittest.main()
