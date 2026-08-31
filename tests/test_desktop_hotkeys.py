import unittest
from unittest.mock import Mock

from translator_lite.desktop.app import TranslatorApp
from translator_lite.windows.hotkey import (
    DEFAULT_HOTKEY,
    DEFAULT_OCR_HOTKEY,
    HotkeySpec,
)


class DesktopHotkeyPairTests(unittest.TestCase):
    def _app(self) -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app.hotkey_spec = DEFAULT_HOTKEY
        app.ocr_hotkey_spec = DEFAULT_OCR_HOTKEY
        app._hotkey_manager = Mock()
        app._ocr_hotkey_manager = Mock()
        app.footer_status = Mock()
        app._persist_settings = Mock()
        return app

    def test_applies_both_hotkeys_before_persisting(self) -> None:
        app = self._app()
        app._hotkey_manager.start.return_value = (True, None)
        app._ocr_hotkey_manager.start.return_value = (True, None)
        translation = HotkeySpec(("Ctrl", "Alt"), "T")
        ocr = HotkeySpec(("Ctrl", "Alt"), "O")

        success, error = app.apply_hotkeys(translation, ocr, persist=True)

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(app.hotkey_spec, translation)
        self.assertEqual(app.ocr_hotkey_spec, ocr)
        app._persist_settings.assert_called_once_with()

    def test_rejects_identical_hotkeys_without_stopping_current_pair(self) -> None:
        app = self._app()

        success, error = app.apply_hotkeys(
            DEFAULT_HOTKEY, DEFAULT_HOTKEY, persist=True
        )

        self.assertFalse(success)
        self.assertIn("不能使用相同快捷键", error or "")
        app._hotkey_manager.stop.assert_not_called()
        app._ocr_hotkey_manager.stop.assert_not_called()

    def test_failed_ocr_registration_restores_previous_pair(self) -> None:
        app = self._app()
        app._hotkey_manager.start.side_effect = [(True, None), (True, None)]
        app._ocr_hotkey_manager.start.side_effect = [
            (False, "OCR 快捷键已占用"),
            (True, None),
        ]

        success, error = app.apply_hotkeys(
            HotkeySpec(("Ctrl", "Alt"), "T"),
            HotkeySpec(("Ctrl", "Alt"), "O"),
            persist=True,
        )

        self.assertFalse(success)
        self.assertIn("OCR 快捷键已占用", error or "")
        self.assertEqual(app.hotkey_spec, DEFAULT_HOTKEY)
        self.assertEqual(app.ocr_hotkey_spec, DEFAULT_OCR_HOTKEY)
        self.assertEqual(app._hotkey_manager.start.call_count, 2)
        self.assertEqual(app._ocr_hotkey_manager.start.call_count, 2)
        app._persist_settings.assert_not_called()


if __name__ == "__main__":
    unittest.main()
