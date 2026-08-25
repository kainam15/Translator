import ctypes
import queue
import unittest
from unittest.mock import Mock

from translator_lite.windows.mouse import (
    MOUSE_BUTTON_DOWN_MESSAGES,
    MSLLHOOKSTRUCT,
    POINT,
    GlobalMouseClick,
    WM_LBUTTONDOWN,
    is_mouse_button_down_message,
)


class WindowsMouseTests(unittest.TestCase):
    def test_low_level_hook_structure_matches_windows_abi(self) -> None:
        expected_size = 32 if ctypes.sizeof(ctypes.c_void_p) == 8 else 24

        self.assertEqual(ctypes.sizeof(MSLLHOOKSTRUCT), expected_size)

    def test_all_supported_button_down_messages_are_recognized(self) -> None:
        self.assertTrue(
            all(
                is_mouse_button_down_message(message)
                for message in MOUSE_BUTTON_DOWN_MESSAGES
            )
        )
        self.assertFalse(is_mouse_button_down_message(0x0202))

    def test_hook_publishes_button_down_coordinates(self) -> None:
        events: queue.Queue[tuple[int, int]] = queue.Queue()
        monitor = GlobalMouseClick(events)
        monitor._user32 = Mock()
        monitor._user32.CallNextHookEx.return_value = 0
        event = MSLLHOOKSTRUCT(pt=POINT(-120, 84))

        monitor._hook_proc(0, WM_LBUTTONDOWN, ctypes.addressof(event))

        self.assertEqual(events.get_nowait(), (-120, 84))


if __name__ == "__main__":
    unittest.main()
