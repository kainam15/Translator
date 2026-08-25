import unittest
from unittest.mock import Mock, patch

from desktop_app import TranslatorApp


class DesktopWindowDismissTests(unittest.TestCase):
    def _app(self) -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app.root = Mock()
        app._closed = False
        app.hide_window = Mock(return_value="break")
        app.root.state.return_value = "normal"
        return app

    @patch("desktop_app.window_at_point_is_current_process", return_value=False)
    def test_global_click_in_another_process_hides_visible_window(
        self, _target_check: Mock
    ) -> None:
        app = self._app()
        app._settings_dialog = None

        app._handle_global_mouse_click(120, 80)

        app.hide_window.assert_called_once_with()

    @patch("desktop_app.window_at_point_is_current_process", return_value=True)
    def test_global_click_in_translator_keeps_window_visible(
        self, _target_check: Mock
    ) -> None:
        app = self._app()
        app._settings_dialog = None

        app._handle_global_mouse_click(120, 80)

        app.hide_window.assert_not_called()

    @patch("desktop_app.window_at_point_is_current_process", return_value=False)
    def test_settings_dialog_disables_click_outside_dismissal(
        self, _target_check: Mock
    ) -> None:
        app = self._app()
        app._settings_dialog = Mock()
        app._settings_dialog.window.winfo_exists.return_value = True

        app._handle_global_mouse_click(120, 80)

        _target_check.assert_not_called()
        app.hide_window.assert_not_called()

    @patch("desktop_app.window_at_point_is_current_process", return_value=False)
    def test_global_click_is_ignored_when_window_is_already_hidden(
        self, _target_check: Mock
    ) -> None:
        app = self._app()
        app._settings_dialog = None
        app.root.state.return_value = "withdrawn"

        app._handle_global_mouse_click(120, 80)

        _target_check.assert_not_called()
        app.hide_window.assert_not_called()


if __name__ == "__main__":
    unittest.main()
