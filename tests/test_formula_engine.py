"""Geometry regressions for the optional formula helper without model downloads."""

import unittest

from translator_lite.ocr.formula_engine import (
    FormulaRegion,
    _formula_kind,
    _letterbox_geometry,
    _restore_box,
    _suppress_overlaps,
)


class FormulaDetectionGeometryTests(unittest.TestCase):
    def test_wide_capture_restores_equation_above_letterbox_padding(self):
        geometry = _letterbox_geometry((1600, 400), (768, 768))
        self.assertEqual((geometry.width, geometry.height, geometry.top), (768, 192, 288))
        box = _restore_box((240, 312, 528, 360), geometry)
        self.assertEqual(box, (500, 50, 1100, 150))

    def test_odd_letterbox_padding_matches_yolo_rounding(self):
        geometry = _letterbox_geometry((1000, 501), (768, 768))
        self.assertEqual((geometry.height, geometry.top), (385, 191))
        box = _restore_box((-4, 188, 800, 580), geometry)
        self.assertEqual(box, (0, 0, 1000, 501))

    def test_dynamic_model_avoids_square_padding_for_wide_captures(self):
        geometry = _letterbox_geometry((1600, 400), (768, 768), stride=32)
        self.assertEqual(geometry.padded_size, (768, 192))
        self.assertEqual(geometry.top, 0)
        box = _restore_box((240, 24, 528, 72), geometry)
        self.assertEqual(box, (500, 50, 1100, 150))

    def test_overlapping_anchors_keep_best_score_without_losing_another_formula(self):
        first = FormulaRegion((10, 20, 100, 60), "display", 0.9)
        duplicate = FormulaRegion((12, 21, 101, 62), "display", 0.6)
        second = FormulaRegion((140, 22, 200, 58), "inline", 0.8)
        self.assertEqual(_suppress_overlaps([duplicate, second, first]), [first, second])

    def test_different_formula_classes_are_not_suppressed(self):
        inline = FormulaRegion((10, 20, 100, 60), "inline", 0.9)
        display = FormulaRegion((10, 20, 100, 60), "display", 0.8)
        self.assertEqual(_suppress_overlaps([inline, display]), [inline, display])

    def test_metadata_labels_determine_inline_and_display_semantics(self):
        self.assertEqual(_formula_kind("embedding"), "inline")
        self.assertEqual(_formula_kind("isolated"), "display")
        with self.assertRaises(ValueError):
            _formula_kind("text")

    def test_empty_capture_is_rejected(self):
        with self.assertRaises(ValueError):
            _letterbox_geometry((0, 100), (768, 768))


if __name__ == "__main__":
    unittest.main()
