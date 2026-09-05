"""Nonvisual integration tests for the desktop math document workflow."""

import queue
import unittest
from unittest.mock import Mock, call, patch

from translator_lite.client import GoogleTranslateError, TranslationResult
from translator_lite.desktop.app import MAX_TEXT_LENGTH, TranslatorApp


class DesktopMathTests(unittest.TestCase):
    def _app(self) -> TranslatorApp:
        app = TranslatorApp.__new__(TranslatorApp)
        app.root = Mock()
        app.source_text = Mock()
        app.result_text = Mock()
        app._source_view = Mock()
        app._result_view = Mock()
        app._source_view.get_content.return_value = r"Compute \(x^2\)."
        app._result_view.get_content.return_value = r"计算 \(x^2\)。"
        # Tk.Text.get omits embedded images; these values detect accidental
        # bypasses of MathTextView without creating a real Tk window.
        app.source_text.get.return_value = "Compute ."
        app.result_text.get.return_value = "计算 。"
        app._placeholder_active = False
        app._math_preview = True
        app._math_dpi = 144.0
        app._rendered_math = {r"\(x^2\)": "png-base64"}
        app.math_mode_button = Mock()
        app.copy_button = Mock()
        app.footer_status = Mock()
        app.provider_meta = Mock()
        app.counter_label = Mock()
        app._closed = False
        app._request_id = 3
        app._results = queue.Queue()
        app._math_results = queue.Queue()
        app._set_busy = Mock()
        app._show_result = Mock()
        app._show_error = Mock()
        app._ready_status = Mock(return_value="翻译完成")
        return app

    def test_copy_source_includes_formula_latex(self) -> None:
        app = self._app()

        app.copy_source()

        app.root.clipboard_clear.assert_called_once_with()
        app.root.clipboard_append.assert_called_once_with(r"Compute \(x^2\).")
        app.source_text.get.assert_not_called()

    @patch("translator_lite.desktop.app.restyle_button")
    def test_copy_result_includes_formula_latex(self, _restyle) -> None:
        app = self._app()

        app.copy_result()

        app.root.clipboard_clear.assert_called_once_with()
        app.root.clipboard_append.assert_called_once_with(r"计算 \(x^2\)。")
        app.result_text.get.assert_not_called()

    def test_copy_empty_source_preserves_clipboard(self) -> None:
        app = self._app()
        app._placeholder_active = True

        app.copy_source()

        app.root.clipboard_clear.assert_not_called()
        app.root.clipboard_append.assert_not_called()

    def test_toggle_raw_and_rendered_views_preserves_both_documents(self) -> None:
        app = self._app()

        app.toggle_math_view()

        self.assertFalse(app._math_preview)
        app.math_mode_button.configure.assert_called_once_with(text="公式")
        app._source_view.set_content.assert_called_once_with(r"Compute \(x^2\).", {})
        app._result_view.set_content.assert_called_once_with(r"计算 \(x^2\)。", {})

        app.toggle_math_view()

        self.assertTrue(app._math_preview)
        self.assertEqual(app.math_mode_button.configure.call_args, call(text="LaTeX"))
        self.assertEqual(
            app._source_view.set_content.call_args,
            call(r"Compute \(x^2\).", app._rendered_math),
        )
        self.assertEqual(
            app._result_view.set_content.call_args,
            call(r"计算 \(x^2\)。", app._rendered_math),
        )

    def test_toggle_keeps_source_placeholder(self) -> None:
        app = self._app()
        app._placeholder_active = True

        app.toggle_math_view()

        app._source_view.set_content.assert_not_called()
        self.assertTrue(app._placeholder_active)

    def test_math_input_is_not_truncated_mid_formula(self) -> None:
        app = self._app()
        text = "A" * (MAX_TEXT_LENGTH - 2) + r" \(x^2\)"
        app._source_view.get_content.return_value = text

        app._set_input_text(text)

        app._source_view.set_content.assert_called_once_with(text, app._rendered_math)
        self.assertFalse(app._placeholder_active)
        self.assertEqual(
            app.counter_label.configure.call_args.kwargs["text"],
            f"{len(text):,} / {MAX_TEXT_LENGTH:,}",
        )

    def test_swap_languages_preserves_formula_documents(self) -> None:
        app = self._app()
        app.source_language = Mock()
        app.source_language.get.return_value = "English"
        app.target_language = Mock()
        app.target_language.get.return_value = "中文（简体）"
        app._set_input_text = Mock()

        app.swap_languages()

        app._set_input_text.assert_called_once_with(r"计算 \(x^2\)。")
        app._show_result.assert_called_once_with(r"Compute \(x^2\).")
        app.result_text.get.assert_not_called()

    @patch("translator_lite.desktop.app.translate_with_math")
    def test_translate_worker_uses_math_aware_client_and_preserves_result(self, translate) -> None:
        app = self._app()
        app._prepare_math = Mock()
        result = TranslationResult(r"计算 \(x^2\)。", "en", "zh-CN")
        translate.return_value = result

        app._translate_worker(3, r"Compute \(x^2\).", "en", "zh-CN")

        translate.assert_called_once_with(
            r"Compute \(x^2\).", source="en", target="zh-CN", timeout=15.0
        )
        app._prepare_math.assert_called_once_with(r"Compute \(x^2\).")
        self.assertEqual(app._results.get_nowait(), (3, result, None))

    @patch("translator_lite.desktop.app.translate_with_math")
    def test_translate_worker_reports_client_error_without_partial_result(self, translate) -> None:
        app = self._app()
        app._prepare_math = Mock()
        translate.side_effect = GoogleTranslateError("request failed")

        app._translate_worker(3, r"Compute \(x^2\).", "auto", "zh-CN")

        self.assertEqual(app._results.get_nowait(), (3, None, "request failed"))

    def test_result_polling_rerenders_current_source_and_keeps_formula_result(self) -> None:
        app = self._app()
        app._results.put((3, TranslationResult(r"计算 \(x^2\)。", "en", "zh-CN"), None))

        app._poll_results()

        app._source_view.set_content.assert_called_once_with(
            r"Compute \(x^2\).", app._rendered_math
        )
        app._show_result.assert_called_once_with(r"计算 \(x^2\)。")
        app._set_busy.assert_called_once_with(False)

    def test_result_polling_leaves_raw_view_and_plain_input_untouched(self) -> None:
        for preview, content in ((False, r"Compute \(x^2\)."), (True, "Plain input")):
            with self.subTest(preview=preview, content=content):
                app = self._app()
                app._math_preview = preview
                app._source_view.get_content.return_value = content
                app._results.put((3, TranslationResult("result", "en", "zh-CN"), None))

                app._poll_results()

                app._source_view.set_content.assert_not_called()
                app._show_result.assert_called_once_with("result")

    def test_stale_translation_does_not_replace_new_formula_document(self) -> None:
        app = self._app()
        app._results.put((2, TranslationResult(r"Old \(y\)", "en", "zh-CN"), None))

        app._poll_results()

        app._source_view.set_content.assert_not_called()
        app._show_result.assert_not_called()
        app._set_busy.assert_not_called()

    @patch("translator_lite.desktop.app.render_formulas", return_value={})
    def test_missing_optional_preview_preserves_current_math_cache(self, render) -> None:
        app = self._app()

        app._prepare_math(r"Missing \(y\)")

        self.assertEqual(app._rendered_math, {r"\(x^2\)": "png-base64"})
        self.assertEqual(render.call_args.args[0], r"\(y\)")

    @patch("translator_lite.desktop.app.render_formulas", return_value={r"\(y\)": "new-png"})
    def test_prepare_math_renders_only_uncached_unique_formulas(self, render) -> None:
        app = self._app()
        text = r"Use \(x^2\), \(y\) and \(y\)."

        app._prepare_math(text)
        app._prepare_math(text)

        self.assertEqual(render.call_count, 1)
        self.assertEqual(render.call_args.args[0], r"\(y\)")
        self.assertEqual(app._rendered_math[r"\(y\)"], "new-png")

    @patch("translator_lite.desktop.app.threading.Thread")
    def test_edited_latex_starts_background_preview_when_switching_back(self, thread) -> None:
        app = self._app()
        app._math_preview = False
        app._source_view.get_content.return_value = r"Edited \(y^3\)"

        app.toggle_math_view()

        self.assertTrue(app._math_preview)
        self.assertEqual(thread.call_args.kwargs["target"], app._math_preview_worker)
        self.assertEqual(
            thread.call_args.kwargs["args"], (r"Edited \(y^3\)", r"计算 \(x^2\)。")
        )
        thread.return_value.start.assert_called_once_with()

    @patch("translator_lite.desktop.app.threading.Thread")
    def test_cached_preview_does_not_start_another_renderer(self, thread) -> None:
        app = self._app()
        app._math_preview = False

        app.toggle_math_view()

        thread.assert_not_called()

    def test_preview_worker_queues_both_documents_without_touching_widgets(self) -> None:
        app = self._app()
        app._prepare_math = Mock()
        source, result = r"Original \(x\)", r"译文 \(x\)"

        app._math_preview_worker(source, result)

        self.assertEqual(app._prepare_math.call_args_list, [call(source), call(result)])
        self.assertEqual(app._math_results.get_nowait(), (source, result))
        app._source_view.set_content.assert_not_called()
        app._result_view.set_content.assert_not_called()

    def test_preview_result_does_not_replace_source_edited_after_render_started(self) -> None:
        app = self._app()
        app._math_results.put((r"Old source \(x\)", r"计算 \(x^2\)。"))

        app._poll_math_previews()

        app._source_view.set_content.assert_not_called()
        app._result_view.set_content.assert_called_once_with(
            r"计算 \(x^2\)。", app._rendered_math
        )

    def test_preview_result_does_not_replace_new_translation(self) -> None:
        app = self._app()
        app._math_results.put((r"Compute \(x^2\).", r"Old result \(x\)"))

        app._poll_math_previews()

        app._source_view.set_content.assert_called_once_with(
            r"Compute \(x^2\).", app._rendered_math
        )
        app._result_view.set_content.assert_not_called()

    def test_raw_view_ignores_late_preview_result(self) -> None:
        app = self._app()
        app._math_preview = False
        app._math_results.put((r"Compute \(x^2\).", r"计算 \(x^2\)。"))

        app._poll_math_previews()

        app._source_view.set_content.assert_not_called()
        app._result_view.set_content.assert_not_called()
        self.assertTrue(app._math_results.empty())

    @patch("translator_lite.desktop.app.close_helper")
    def test_exit_stops_formula_helper_after_destroying_desktop(self, close_helper) -> None:
        app = self._app()
        app._ocr_selector = Mock()
        app._hotkey_manager = Mock()
        app._ocr_hotkey_manager = Mock()
        app._mouse_monitor = Mock()
        app._tray = Mock()
        events = []
        app.root.destroy.side_effect = lambda: events.append("destroy")
        close_helper.side_effect = lambda: events.append("close_helper")

        app.exit_app()

        self.assertTrue(app._closed)
        self.assertIsNone(app._ocr_selector)
        app._hotkey_manager.stop.assert_called_once_with()
        app._ocr_hotkey_manager.stop.assert_called_once_with()
        self.assertEqual(events, ["destroy", "close_helper"])


if __name__ == "__main__":
    unittest.main()
