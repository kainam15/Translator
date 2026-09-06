import unittest
from unittest.mock import Mock, patch

from translator_lite.windows.window import (
    MOVE_WINDOW_FLAGS,
    RDW_UPDATENOW,
    REDRAW_WINDOW_FLAGS,
    RESIZE_WINDOW_FLAGS,
    redraw_window,
    set_window_bounds,
    set_window_position,
)


class WindowsWindowTests(unittest.TestCase):
    @patch("translator_lite.windows.window._load_user32")
    def test_positioning_moves_tk_toplevel_without_resizing(
        self, load_user32: Mock
    ) -> None:
        user32 = Mock()
        user32.GetParent.return_value = 456
        user32.SetWindowPos.return_value = 1
        load_user32.return_value = user32

        self.assertTrue(set_window_position(123, 240, -80))

        user32.SetWindowPos.assert_called_once_with(
            456,
            None,
            240,
            -80,
            0,
            0,
            MOVE_WINDOW_FLAGS,
        )

    @patch("translator_lite.windows.window._load_user32")
    def test_resizing_does_not_force_a_full_repaint_for_every_pointer_event(
        self, load_user32: Mock
    ) -> None:
        user32 = Mock()
        user32.GetParent.return_value = 456
        user32.SetWindowPos.return_value = 1
        user32.RedrawWindow.return_value = 1
        load_user32.return_value = user32

        self.assertTrue(set_window_bounds(123, 40, 50, 800, 720))

        user32.SetWindowPos.assert_called_once_with(
            456,
            None,
            40,
            50,
            800,
            720,
            RESIZE_WINDOW_FLAGS,
        )
        user32.RedrawWindow.assert_not_called()

    @patch("translator_lite.windows.window._load_user32")
    def test_immediate_redraw_paints_before_returning(
        self, load_user32: Mock
    ) -> None:
        user32 = Mock()
        user32.GetParent.return_value = 456
        user32.RedrawWindow.return_value = 1
        load_user32.return_value = user32

        self.assertTrue(redraw_window(123, immediate=True))

        user32.RedrawWindow.assert_called_once_with(
            456,
            None,
            None,
            REDRAW_WINDOW_FLAGS | RDW_UPDATENOW,
        )

    @patch("translator_lite.windows.window._load_user32", return_value=None)
    def test_positioning_falls_back_outside_windows(
        self, _load_user32: Mock
    ) -> None:
        self.assertFalse(set_window_position(123, 20, 30))


if __name__ == "__main__":
    unittest.main()
