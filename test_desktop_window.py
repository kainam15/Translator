import tkinter as tk
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

    def test_focus_out_waits_until_windows_assigns_new_focus(self) -> None:
        app = self._app()

        app._on_window_focus_out()

        app.root.after.assert_called_once_with(20, app._hide_if_window_inactive)

    @patch("desktop_app._foreground_window_is_current_process", return_value=False)
    def test_window_hides_when_another_process_is_foreground(
        self, _foreground_check: Mock
    ) -> None:
        app = self._app()
        # Tk can retain the last focused widget after Windows changes focus.
        app.root.focus_get.return_value = Mock(spec=tk.Misc)

        app._hide_if_window_inactive()

        app.hide_window.assert_called_once_with()

    @patch("desktop_app._foreground_window_is_current_process", return_value=True)
    def test_window_stays_visible_when_own_process_is_foreground(
        self, _foreground_check: Mock
    ) -> None:
        app = self._app()

        app._hide_if_window_inactive()

        app.root.focus_get.assert_not_called()
        app.hide_window.assert_not_called()

    @patch("desktop_app._foreground_window_is_current_process", return_value=None)
    def test_tk_focus_is_used_when_foreground_check_is_unavailable(
        self, _foreground_check: Mock
    ) -> None:
        app = self._app()
        app.root.focus_get.return_value = Mock(spec=tk.Misc)

        app._hide_if_window_inactive()

        app.hide_window.assert_not_called()

    def test_already_hidden_window_is_ignored(self) -> None:
        app = self._app()
        app.root.state.return_value = "withdrawn"

        app._hide_if_window_inactive()

        app.root.focus_get.assert_not_called()
        app.hide_window.assert_not_called()


if __name__ == "__main__":
    unittest.main()
