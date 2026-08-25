import unittest

from desktop_app import (
    AppSettings,
    clamp_window_position,
    settings_from_payload,
    settings_to_payload,
)
from windows_hotkey import DEFAULT_HOTKEY, HotkeySpec


class DesktopSettingsTests(unittest.TestCase):
    def test_old_hotkey_only_settings_remain_compatible(self) -> None:
        settings = settings_from_payload(
            {"hotkey": {"modifiers": ["Ctrl", "Alt"], "key": "T"}}
        )

        self.assertEqual(settings.hotkey.display, "Ctrl+Alt+T")
        self.assertFalse(settings.position_pinned)
        self.assertIsNone(settings.window_position)

    def test_position_pin_round_trip(self) -> None:
        original = AppSettings(
            HotkeySpec(("Alt",), "W"),
            position_pinned=True,
            window_position=(-720, 84),
        )

        restored = settings_from_payload(settings_to_payload(original))

        self.assertEqual(restored, original)

    def test_invalid_pinned_position_is_disabled(self) -> None:
        settings = settings_from_payload(
            {
                "hotkey": DEFAULT_HOTKEY.to_dict(),
                "position_pinned": True,
                "window_position": {"x": True, "y": "54"},
            }
        )

        self.assertFalse(settings.position_pinned)
        self.assertIsNone(settings.window_position)

    def test_clamp_keeps_window_inside_positive_work_area(self) -> None:
        self.assertEqual(
            clamp_window_position(1800, -20, 720, 660, (0, 0, 1920, 1040)),
            (1200, 0),
        )

    def test_clamp_supports_negative_monitor_coordinates(self) -> None:
        self.assertEqual(
            clamp_window_position(-2500, 500, 720, 660, (-1920, 0, 0, 1080)),
            (-1920, 420),
        )


if __name__ == "__main__":
    unittest.main()
