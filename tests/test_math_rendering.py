import base64
import importlib.util
import io
import unittest

from translator_lite.ocr.rendering import render_formulas


@unittest.skipUnless(
    importlib.util.find_spec("matplotlib") and importlib.util.find_spec("PIL"),
    "Helper-side Matplotlib and Pillow are not installed",
)
class MathRenderingTests(unittest.TestCase):
    def _image(self, encoded: str):
        from PIL import Image

        image = Image.open(io.BytesIO(base64.b64decode(encoded)))
        image.load()
        return image

    def test_fraction_and_superscript_render_to_transparent_png(self) -> None:
        formula = r"\[P(x)=\frac{1}{2}+x^4\]"

        rendered = render_formulas("Evaluate " + formula, padding=6)

        self.assertEqual(set(rendered), {formula})
        image = self._image(rendered[formula])
        self.assertEqual(image.format, "PNG")
        self.assertEqual(image.mode, "RGBA")
        self.assertGreater(image.width, 12)
        self.assertGreater(image.height, 12)
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertEqual(image.getchannel("A").getextrema(), (0, 255))
        self.assertEqual(image.getchannel("A").crop((0, 0, image.width, 6)).getbbox(), None)

    def test_dpi_and_font_size_control_pixel_size(self) -> None:
        formula = r"\(x^2+1\)"
        small = self._image(render_formulas(formula, dpi=72, font_size=12)[formula])
        high_dpi = self._image(render_formulas(formula, dpi=144, font_size=12)[formula])
        large_font = self._image(render_formulas(formula, dpi=72, font_size=24)[formula])

        self.assertGreater(high_dpi.width, small.width)
        self.assertGreater(high_dpi.height, small.height)
        self.assertGreater(large_font.width, small.width)
        self.assertGreater(large_font.height, small.height)

    def test_unsupported_formula_is_omitted_without_losing_valid_formula(self) -> None:
        supported = r"\(x^2\)"
        unsupported = r"\[\definitelyunsupported{x}\]"

        rendered = render_formulas(unsupported + " and " + supported)

        self.assertEqual(set(rendered), {supported})

    def test_plain_text_and_invalid_delimiters_have_no_images(self) -> None:
        for text in ("ordinary text", r"broken \(x", r"empty \[ \]", r"literal \\(x\\)"):
            with self.subTest(text=text):
                self.assertEqual(render_formulas(text), {})

    def test_duplicate_formula_has_one_mapping_entry(self) -> None:
        formula = r"\(O(x)\)"

        rendered = render_formulas(formula + " and " + formula)

        self.assertEqual(set(rendered), {formula})

    def test_invalid_render_parameters_are_rejected(self) -> None:
        for kwargs in ({"dpi": 0}, {"font_size": -1}, {"padding": -1}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    render_formulas(r"\(x\)", **kwargs)


if __name__ == "__main__":
    unittest.main()
