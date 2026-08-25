import ctypes
import unittest

from translator_lite.windows.hotkey import DEFAULT_HOTKEY, INPUT, HotkeySpec


class HotkeySpecTests(unittest.TestCase):
    def test_input_structure_matches_windows_abi(self) -> None:
        expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(INPUT), expected_size)

    def test_default_hotkey(self) -> None:
        self.assertEqual(DEFAULT_HOTKEY.display, "Alt+W")

    def test_normalizes_order_and_key(self) -> None:
        spec = HotkeySpec(("Shift", "Ctrl"), "k")
        self.assertEqual(spec.display, "Ctrl+Shift+K")

    def test_round_trip_dict(self) -> None:
        spec = HotkeySpec.from_dict({"modifiers": ["Alt"], "key": "W"})
        self.assertEqual(spec.to_dict(), {"modifiers": ["Alt"], "key": "W"})

    def test_plain_letter_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            HotkeySpec((), "Q")


if __name__ == "__main__":
    unittest.main()
