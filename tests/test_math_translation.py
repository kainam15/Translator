import unittest
from unittest.mock import Mock, patch

from translator_lite.client import GoogleTranslateError, TranslationResult
from translator_lite.math_translation import split_math_parts, translate_with_math


class MathTranslationTests(unittest.TestCase):
    def test_shared_splitter_preserves_every_character_and_delimiter(self) -> None:
        text = "Leading \t" + r"\(x^2\)" + "\n\n" + r"\[\frac{1}{2}\]" + " trailing "

        parts = split_math_parts(text)

        self.assertEqual("".join(part for _is_math, part in parts), text)
        self.assertEqual(
            [part for is_math, part in parts if is_math],
            [r"\(x^2\)", r"\[\frac{1}{2}\]"],
        )
        self.assertEqual(split_math_parts(""), [])

    def _translator(self, translations: dict[str, str]) -> Mock:
        def translate(text: str, **kwargs) -> TranslationResult:
            # Any formula sent to this fake would be visibly damaged.
            translated = translations.get(text, text)
            translated = translated.replace("x", "WRONG").replace("O", "o")
            return TranslationResult(translated, "en", kwargs["target"])

        return Mock(side_effect=translate)

    @patch("translator_lite.math_translation.translate")
    def test_plain_text_uses_existing_translation_unchanged(self, translate) -> None:
        expected = TranslationResult("译文", "en", "zh-CN")
        translate.return_value = expected

        result = translate_with_math("Text without math.", timeout=7.0)

        self.assertIs(result, expected)
        translate.assert_called_once_with(
            "Text without math.", source="auto", target="zh-CN", timeout=7.0
        )

    def test_inline_formula_never_enters_translation_request(self) -> None:
        translate = self._translator({"Evaluate": "计算", "at": "在"})
        text = r"Evaluate \(P(x) = 2x^4 + 3x^3 - 3x^2 + 5x - 1\) at \(x=1/2\)."

        with patch("translator_lite.math_translation.translate", translate):
            result = translate_with_math(text)

        self.assertEqual(
            result.text,
            r"计算 \(P(x) = 2x^4 + 3x^3 - 3x^2 + 5x - 1\) 在 \(x=1/2\).",
        )
        self.assertEqual([call.args[0] for call in translate.call_args_list], ["Evaluate", "at"])
        self.assertEqual(result.detected_source_language, "en")

    def test_display_and_inline_math_keep_exact_order_case_and_whitespace(self) -> None:
        translate = self._translator({"The bounds are": "界限为", "and": "和"})
        text = "The bounds are\n\n" + r"\[O(x^2)\]" + "\n\tand " + r"\(o(x^2)\)" + "  \n"

        with patch("translator_lite.math_translation.translate", translate):
            result = translate_with_math(text, source="en", target="zh-TW")

        self.assertEqual(result.text, "界限为\n\n" + r"\[O(x^2)\]" + "\n\t和 " + r"\(o(x^2)\)" + "  \n")
        self.assertEqual(result.target_language, "zh-TW")
        self.assertEqual([call.args[0] for call in translate.call_args_list], ["The bounds are", "and"])
        for call in translate.call_args_list:
            self.assertEqual(call.kwargs["source"], "en")
            self.assertEqual(call.kwargs["target"], "zh-TW")

    @patch("translator_lite.math_translation.translate")
    def test_only_formulas_and_separators_need_no_network(self, translate) -> None:
        text = " \t" + r"\(x=1/2\), \[O(x) \ne o(x)\]" + "\n"

        result = translate_with_math(text)

        self.assertEqual(result.text, text)
        self.assertIsNone(result.detected_source_language)
        self.assertEqual(result.target_language, "zh-CN")
        translate.assert_not_called()

    @patch("translator_lite.math_translation.translate")
    def test_only_formula_retains_explicit_source_language(self, translate) -> None:
        result = translate_with_math(r"\[x^2\]", source="en")

        self.assertEqual(result.detected_source_language, "en")
        translate.assert_not_called()

    @patch("translator_lite.math_translation.translate")
    def test_empty_mismatched_and_escaped_delimiters_are_plain_text(self, translate) -> None:
        for text in (
            r"Empty \(\) body.",
            "Whitespace \\[ \t \\] body.",
            r"Mismatched \(x\] body.",
            r"Unclosed \(x and more prose.",
            r"Literal \\(x\\) characters.",
            r"Price $5 and unmarked x^2.",
        ):
            with self.subTest(text=text):
                translate.reset_mock()
                translate.return_value = TranslationResult("译文", "en", "zh-CN")

                result = translate_with_math(text)

                self.assertIs(result, translate.return_value)
                translate.assert_called_once_with(
                    text, source="auto", target="zh-CN", timeout=15.0
                )

    def test_unclosed_delimiter_does_not_hide_later_paragraph_or_formula(self) -> None:
        first = "Broken \\( equation\n\nNext paragraph."
        translate = self._translator({first: "损坏的分隔符。\n\n下一段。", "End.": "结束。"})
        text = first + " " + r"\(x^2\)" + " End."

        with patch("translator_lite.math_translation.translate", translate):
            result = translate_with_math(text)

        self.assertEqual(result.text, "损坏的分隔符。\n\n下一段。 " + r"\(x^2\)" + " 结束。")
        self.assertEqual([call.args[0] for call in translate.call_args_list], [first, "End."])

    @patch("translator_lite.math_translation.translate")
    def test_delimiters_do_not_capture_across_blank_paragraph(self, translate) -> None:
        text = "Broken \\( formula\n\nOrdinary paragraph \\)."

        translate_with_math(text)

        translate.assert_called_once_with(text, source="auto", target="zh-CN", timeout=15.0)

    @patch("translator_lite.math_translation.translate")
    def test_multiline_display_formula_is_preserved(self, translate) -> None:
        text = "\\[\\begin{aligned}\nx &= 1 \\\\\ny &= 2\n\\end{aligned}\\]"

        result = translate_with_math(text)

        self.assertEqual(result.text, text)
        translate.assert_not_called()

    @patch("translator_lite.math_translation.time.monotonic", side_effect=[10.0, 11.0, 13.0])
    def test_prose_requests_share_one_timeout_budget(self, _clock) -> None:
        translate = self._translator({"Before": "之前", "after": "之后"})

        with patch("translator_lite.math_translation.translate", translate):
            translate_with_math(r"Before \(x\) after", timeout=5.0)

        self.assertEqual([call.kwargs["timeout"] for call in translate.call_args_list], [4.0, 2.0])

    @patch("translator_lite.math_translation.time.monotonic", side_effect=[10.0, 11.0, 16.0])
    def test_expired_budget_stops_further_requests(self, _clock) -> None:
        translate = self._translator({"Before": "之前"})

        with patch("translator_lite.math_translation.translate", translate):
            with self.assertRaisesRegex(GoogleTranslateError, "超时"):
                translate_with_math(r"Before \(x\) after", timeout=5.0)

        self.assertEqual(translate.call_count, 1)

    @patch("translator_lite.math_translation.translate", side_effect=GoogleTranslateError("network unavailable"))
    def test_network_error_does_not_publish_partial_translation(self, _translate) -> None:
        with self.assertRaisesRegex(GoogleTranslateError, "network unavailable"):
            translate_with_math(r"Before \(x\) after")

    @patch("translator_lite.math_translation.translate")
    def test_formula_path_preserves_existing_input_validation(self, translate) -> None:
        for kwargs in ({"source": ""}, {"target": ""}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    translate_with_math(r"\(x\)", **kwargs)
        with self.assertRaises(ValueError):
            translate_with_math(r"\(" + "x" * 5_000 + r"\)")
        translate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
