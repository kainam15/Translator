import unittest
from types import SimpleNamespace

from translator_lite.ocr.document import RecognizedFormula, merge_layout


def line(text, *words):
    return SimpleNamespace(
        text=text,
        words=tuple(SimpleNamespace(text=word, box=box) for word, box in words),
    )


class DocumentLayoutTests(unittest.TestCase):
    def test_inline_formula_is_inserted_between_words_in_reading_order(self):
        lines = [line(
            "Evaluate at and continue.",
            ("Evaluate", (0, 10, 45, 30)),
            ("at", (50, 10, 65, 30)),
            ("and", (150, 10, 178, 30)),
            ("continue.", (182, 10, 250, 30)),
        )]
        formulas = [RecognizedFormula((70, 8, 140, 32), "inline", "x=1/2")]
        self.assertEqual(
            merge_layout(lines, formulas), r"Evaluate at \(x=1/2\) and continue."
        )

    def test_display_formula_keeps_its_row_and_original_case(self):
        lines = [
            line("Compare", ("Compare", (0, 0, 80, 20))),
            line("carefully.", ("carefully.", (0, 100, 80, 120))),
        ]
        formulas = [RecognizedFormula((30, 40, 200, 80), "display", "O(x)+o(x)")]
        self.assertEqual(
            merge_layout(lines, formulas), "Compare\n\\[O(x)+o(x)\\]\ncarefully."
        )

    def test_masked_formula_rejoins_native_line_fragments(self):
        lines = [
            line("At", ("At", (0, 10, 20, 30))),
            line("continue.", ("continue.", (110, 10, 190, 30))),
        ]
        formula = RecognizedFormula((30, 8, 100, 32), "inline", "x=1/2")
        self.assertEqual(merge_layout(lines, [formula]), r"At \(x=1/2\) continue.")

    def test_native_text_overlapping_formula_is_not_duplicated(self):
        lines = [line("2x4", ("2x4", (20, 40, 80, 60)))]
        formula = RecognizedFormula((10, 30, 100, 70), "display", "2x^{4}")
        self.assertEqual(merge_layout(lines, [formula]), r"\[2x^{4}\]")

    def test_formula_and_following_punctuation_are_joined(self):
        lines = [line("At ?", ("At", (0, 10, 20, 30)), ("?", (110, 10, 120, 30)))]
        formula = RecognizedFormula((30, 10, 100, 30), "inline", "x=1/2")
        self.assertEqual(merge_layout(lines, [formula]), r"At \(x=1/2\)?")

    def test_plain_text_preserves_original_recognition(self):
        lines = [line("大小写 O 和 o", ("大小写", (0, 0, 60, 20)))]
        self.assertEqual(merge_layout(lines, []), "大小写 O 和 o")

    def test_unattached_inline_formula_is_not_discarded(self):
        formula = RecognizedFormula((10, 30, 100, 70), "inline", r"\frac{1}{2}")
        self.assertEqual(merge_layout([], [formula]), r"\(\frac{1}{2}\)")


if __name__ == "__main__":
    unittest.main()
