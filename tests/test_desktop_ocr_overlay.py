import unittest

from translator_lite.desktop.ocr_overlay import normalize_screen_region
from translator_lite.windows.ocr import ScreenRegion


class OcrOverlayGeometryTests(unittest.TestCase):
    def test_normalizes_reverse_drag(self) -> None:
        region = normalize_screen_region((300, 220), (100, 80))

        self.assertEqual(region, ScreenRegion(100, 80, 200, 140))

    def test_preserves_negative_virtual_screen_coordinates(self) -> None:
        region = normalize_screen_region((-900, 50), (-120, 600))

        self.assertEqual(region, ScreenRegion(-900, 50, 780, 550))

    def test_rejects_accidental_click(self) -> None:
        self.assertIsNone(normalize_screen_region((20, 20), (24, 25)))


if __name__ == "__main__":
    unittest.main()
