"""Optional helper-side formula rendering; never imports into the Tk runtime."""

from __future__ import annotations

import base64
import io
import math

from ..math_translation import split_math_parts


MAX_FORMULA_PIXELS = 8_000_000


def render_formulas(
    text: str,
    *,
    dpi: float = 144.0,
    font_size: float = 18.0,
    padding: int = 5,
    color: str = "#1f2937",
) -> dict[str, str]:
    """Map complete delimited formulas to transparent, base64-encoded PNGs.

    Matplotlib's Agg mathtext parser handles fractions and exponents without
    an external LaTeX executable. Unsupported syntax is omitted so callers
    can display the original LaTeX. Pillow and Matplotlib are helper-only
    dependencies; an unavailable renderer also leaves formulas as raw text.
    """
    if not math.isfinite(dpi) or dpi <= 0:
        raise ValueError("Formula dpi must be positive and finite")
    if not math.isfinite(font_size) or font_size <= 0:
        raise ValueError("Formula font size must be positive and finite")
    if not isinstance(padding, int) or isinstance(padding, bool) or padding < 0:
        raise ValueError("Formula padding must be a nonnegative integer")

    formulas = dict.fromkeys(
        part for is_math, part in split_math_parts(text) if is_math
    )
    if not formulas:
        return {}
    try:
        from matplotlib.font_manager import FontProperties
        from matplotlib.mathtext import MathTextParser
        from PIL import Image, ImageChops, ImageColor
    except ImportError:
        return {}

    rgba = ImageColor.getcolor(color, "RGBA")
    parser = MathTextParser("agg")
    properties = FontProperties(size=font_size)
    rendered: dict[str, str] = {}
    for formula in formulas:
        try:
            body = formula[2:-2].strip()
            raster = parser.parse("$" + body + "$", dpi=dpi, prop=properties)
            pixels = memoryview(raster.image)
            height, width = pixels.shape
            if width <= 0 or height <= 0:
                continue
            padded_size = (width + 2 * padding, height + 2 * padding)
            if padded_size[0] * padded_size[1] > MAX_FORMULA_PIXELS:
                continue

            alpha = Image.frombytes("L", (width, height), bytes(pixels))
            if rgba[3] != 255:
                alpha = ImageChops.multiply(
                    alpha, Image.new("L", alpha.size, rgba[3])
                )
            glyphs = Image.new("RGBA", alpha.size, rgba)
            glyphs.putalpha(alpha)
            image = Image.new("RGBA", padded_size, (0, 0, 0, 0))
            image.paste(glyphs, (padding, padding))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            rendered[formula] = base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            # OCR can produce unsupported / malformed LaTeX. A rendering
            # failure must not discard that formula or other recognized text.
            continue
    return rendered
