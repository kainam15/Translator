import queue
import unittest
from unittest.mock import Mock, patch

from translator_lite.desktop.app import TranslatorApp
from translator_lite.windows.ocr import ScreenRegion, WindowsOcrError


class DesktopOcrFlowTests(unittest.TestCase):
    def _polling_app(self) -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app._closed = False
        app._decorated = False
        app._ocr_pending = True
        app._ocr_restore_on_cancel = True
        app._ocr_results = queue.Queue()
        app.root = Mock()
        app._discard_mouse_events = Mock()
        app._show_near_cursor = Mock()
        app._show_ocr_error = Mock()
        app._accept_selected_text = Mock()
        return app

    @patch(
        "translator_lite.desktop.app.recognize_screen_region",
        return_value="sample text",
    )
    def test_worker_publishes_recognized_text(self, _recognize) -> None:
        app = self._polling_app()

        app._ocr_worker(ScreenRegion(10, 20, 300, 120))

        self.assertEqual(app._ocr_results.get_nowait(), ("sample text", None))

    @patch(
        "translator_lite.desktop.app.recognize_screen_region",
        side_effect=WindowsOcrError("OCR unavailable"),
    )
    def test_worker_publishes_native_error(self, _recognize) -> None:
        app = self._polling_app()

        app._ocr_worker(ScreenRegion(10, 20, 300, 120))

        self.assertEqual(app._ocr_results.get_nowait(), (None, "OCR unavailable"))

    def test_polling_accepts_non_empty_ocr_text(self) -> None:
        app = self._polling_app()
        app._ocr_results.put(("  recognized text  ", None))

        app._poll_ocr_results()

        self.assertFalse(app._ocr_pending)
        app._accept_selected_text.assert_called_once_with("recognized text")
        app._show_ocr_error.assert_not_called()
        app.root.after.assert_called_once_with(60, app._poll_ocr_results)

    def test_polling_shows_empty_result_as_ocr_error(self) -> None:
        app = self._polling_app()
        app._ocr_results.put(("  ", None))

        app._poll_ocr_results()

        app._show_near_cursor.assert_called_once_with()
        app._show_ocr_error.assert_called_once()
        app._accept_selected_text.assert_not_called()

    def test_decorated_mode_exposes_non_sensitive_ocr_state(self) -> None:
        app = TranslatorApp.__new__(TranslatorApp)
        app._decorated = True
        app.root = Mock()

        app._set_automation_state("ocr-recognized")

        app.root.title.assert_called_once_with("Translator [ocr-recognized]")


if __name__ == "__main__":
    unittest.main()
