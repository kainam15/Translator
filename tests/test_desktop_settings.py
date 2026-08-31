from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from translator_lite.desktop.settings import (
    AppSettings,
    load_settings,
    save_settings,
    settings_from_payload,
    settings_to_payload,
)
from translator_lite.windows.hotkey import (
    DEFAULT_HOTKEY,
    DEFAULT_OCR_HOTKEY,
    HotkeySpec,
)


class DesktopSettingsTests(unittest.TestCase):
    def test_old_hotkey_only_settings_remain_compatible(self) -> None:
        settings = settings_from_payload(
            {"hotkey": {"modifiers": ["Ctrl", "Alt"], "key": "T"}}
        )

        self.assertEqual(settings.hotkey.display, "Ctrl+Alt+T")
        self.assertEqual(settings.ocr_hotkey, DEFAULT_OCR_HOTKEY)
        self.assertFalse(settings.position_pinned)
        self.assertIsNone(settings.window_position)
        self.assertIsNone(settings.window_size)

    def test_position_pin_round_trip(self) -> None:
        original = AppSettings(
            HotkeySpec(("Alt",), "W"),
            position_pinned=True,
            window_position=(-720, 84),
            window_size=(880, 720),
            ocr_hotkey=HotkeySpec(("Ctrl", "Shift"), "Q"),
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

    def test_invalid_window_size_is_ignored(self) -> None:
        settings = settings_from_payload(
            {
                "hotkey": DEFAULT_HOTKEY.to_dict(),
                "window_size": {"width": True, "height": -1},
            }
        )

        self.assertIsNone(settings.window_size)

    def test_file_round_trip_uses_an_explicit_path(self) -> None:
        original = AppSettings(
            HotkeySpec(("Ctrl", "Alt"), "T"),
            position_pinned=True,
            window_position=(100, 200),
            window_size=(760, 680),
            ocr_hotkey=HotkeySpec(("Alt", "Shift"), "Q"),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "settings.json"

            save_settings(original, path)

            self.assertEqual(load_settings(path), original)

    def test_invalid_ocr_hotkey_falls_back_to_default(self) -> None:
        settings = settings_from_payload(
            {
                "hotkey": DEFAULT_HOTKEY.to_dict(),
                "ocr_hotkey": {"modifiers": [], "key": "Q"},
            }
        )

        self.assertEqual(settings.ocr_hotkey, DEFAULT_OCR_HOTKEY)

    def test_invalid_json_falls_back_to_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("not-json", encoding="utf-8")

            self.assertEqual(load_settings(path), AppSettings(DEFAULT_HOTKEY))


if __name__ == "__main__":
    unittest.main()
