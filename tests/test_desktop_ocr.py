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
        app._prepare_math = Mock()
        return app

    @patch(
        "translator_lite.desktop.app.recognize_screen_region",
        return_value="sample text",
    )
    def test_worker_publishes_recognized_text(self, _recognize) -> None:
        app = self._polling_app()

        app._ocr_worker(ScreenRegion(10, 20, 300, 120))

        self.assertEqual(app._ocr_results.get_nowait(), ("sample text", None))
        _recognize.assert_called_once_with(
            ScreenRegion(10, 20, 300, 120), language="auto"
        )
        app._prepare_math.assert_called_once_with("sample text")

    @patch("translator_lite.desktop.app.threading.Thread")
    def test_capture_reads_source_language_before_starting_worker(self, thread) -> None:
        app = self._polling_app()
        app.source_language = Mock()
        app.source_language.get.return_value = "English"
        region = ScreenRegion(10, 20, 300, 120)

        app._start_ocr_recognition(region)

        self.assertEqual(thread.call_args.kwargs["args"], (region, "en"))
        thread.return_value.start.assert_called_once_with()

    @patch(
        "translator_lite.desktop.app.recognize_screen_region",
        return_value="sample text",
    )
    def test_worker_forwards_selected_source_language(self, recognize) -> None:
        app = self._polling_app()
        region = ScreenRegion(10, 20, 300, 120)

        app._ocr_worker(region, "en")

        recognize.assert_called_once_with(region, language="en")
        self.assertEqual(app._ocr_results.get_nowait(), ("sample text", None))

    @patch(
        "translator_lite.desktop.app.recognize_screen_region",
        side_effect=WindowsOcrError("OCR unavailable"),
    )
    def test_worker_publishes_native_error(self, _recognize) -> None:
        app = self._polling_app()

        app._ocr_worker(ScreenRegion(10, 20, 300, 120))

        self.assertEqual(app._ocr_results.get_nowait(), (None, "OCR unavailable"))
        app._prepare_math.assert_not_called()

    @patch(
        "translator_lite.desktop.app.recognize_screen_region",
        side_effect=RuntimeError("formula model failed"),
    )
    def test_worker_publishes_formula_runtime_error(self, _recognize) -> None:
        app = self._polling_app()

        app._ocr_worker(ScreenRegion(10, 20, 300, 120))

        self.assertEqual(
            app._ocr_results.get_nowait(), (None, "OCR 失败: formula model failed")
        )
        app._prepare_math.assert_not_called()

    @patch(
        "translator_lite.desktop.app.recognize_screen_region",
        return_value=r"Compute \(x^2\).",
    )
    def test_worker_keeps_formula_latex_when_preparing_preview(self, _recognize) -> None:
        app = self._polling_app()

        app._ocr_worker(ScreenRegion(10, 20, 300, 120))

        app._prepare_math.assert_called_once_with(r"Compute \(x^2\).")
        self.assertEqual(
            app._ocr_results.get_nowait(), (r"Compute \(x^2\).", None)
        )

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

    def test_polling_restores_window_and_reports_helper_error(self) -> None:
        app = self._polling_app()
        app._ocr_results.put((None, "本地 OCR 组件意外退出"))

        app._poll_ocr_results()

        self.assertFalse(app._ocr_pending)
        self.assertFalse(app._ocr_restore_on_cancel)
        app._show_near_cursor.assert_called_once_with()
        app._show_ocr_error.assert_called_once_with("本地 OCR 组件意外退出")
        app._accept_selected_text.assert_not_called()

    def test_ocr_error_uses_engine_neutral_label(self) -> None:
        app = self._polling_app()
        app._show_result = Mock()
        app.provider_meta = Mock()
        app.footer_status = Mock()
        app.ocr_hotkey_spec = Mock(display="Alt+E")

        TranslatorApp._show_ocr_error(app, "本地公式模型失败")

        self.assertEqual(app.provider_meta.configure.call_args.kwargs["text"], "OCR 失败")
        self.assertIn("Alt+E", app.footer_status.configure.call_args.kwargs["text"])
        self.assertEqual(app._show_result.call_args.args[0], "本地公式模型失败")

    def test_decorated_mode_exposes_non_sensitive_ocr_state(self) -> None:
        app = TranslatorApp.__new__(TranslatorApp)
        app._decorated = True
        app.root = Mock()

        app._set_automation_state("ocr-recognized")

        app.root.title.assert_called_once_with("Translator [ocr-recognized]")


if __name__ == "__main__":
    unittest.main()
