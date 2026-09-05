"""Join native prose OCR with separately detected and recognized formulas."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import time
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from ..windows.ocr import OcrLine
    from .formula_engine import FormulaEngine


Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class RecognizedFormula:
    box: Box
    kind: str
    latex: str

    @property
    def text(self) -> str:
        if self.kind == "display":
            return "\\[" + self.latex + "\\]"
        return "\\(" + self.latex + "\\)"


def _bounds(boxes: Sequence[Box]) -> Box:
    return (
        min(box[0] for box in boxes), min(box[1] for box in boxes),
        max(box[2] for box in boxes), max(box[3] for box in boxes),
    )


def _covered(word: Box, formula: Box) -> bool:
    overlap = max(0.0, min(word[2], formula[2]) - max(word[0], formula[0]))
    overlap *= max(0.0, min(word[3], formula[3]) - max(word[1], formula[1]))
    area = (word[2] - word[0]) * (word[3] - word[1])
    return area > 0 and overlap / area > 0.5


def _join_tokens(tokens: list[tuple[Box, str]]) -> str:
    result = ""
    for _box, text in sorted(tokens, key=lambda token: token[0][0]):
        if not result:
            result = text
        elif text[:1] in ",.!?;:%，。！？；：、）】" or result[-1:] in "(（【":
            result += text
        elif "\u3400" <= result[-1:] <= "\u9fff" and "\u3400" <= text[:1] <= "\u9fff":
            result += text
        else:
            result += " " + text
    return result


def merge_layout(lines: Sequence[OcrLine], formulas: Sequence[RecognizedFormula]) -> str:
    """Reinsert formulas by geometry; never guess lost exponents from prose."""
    if not formulas:
        return "\n".join(line.text for line in lines if line.text.strip()).strip()
    rows: list[tuple[Box, list[tuple[Box, str]]]] = []
    for line in lines:
        words = [
            (word.box, word.text) for word in line.words
            if not any(_covered(word.box, formula.box) for formula in formulas)
        ]
        if words:
            rows.append((_bounds([word[0] for word in words]), words))

    display_rows: list[tuple[Box, str]] = []
    for formula in formulas:
        best_index = None
        best_overlap = 0.0
        if formula.kind == "inline":
            for index, (box, _tokens) in enumerate(rows):
                height = min(box[3] - box[1], formula.box[3] - formula.box[1])
                overlap = max(0.0, min(box[3], formula.box[3]) - max(box[1], formula.box[1]))
                score = overlap / max(height, 1)
                if score > max(0.35, best_overlap):
                    best_index, best_overlap = index, score
        if best_index is None:
            display_rows.append((formula.box, formula.text))
        else:
            # A white formula gap can make Windows split one physical line
            # into two OCR lines. Join only nearby fragments bridged by it.
            best_box, tokens = rows[best_index]
            for index in range(len(rows) - 1, -1, -1):
                if index == best_index:
                    continue
                box, other_tokens = rows[index]
                height = min(box[3] - box[1], best_box[3] - best_box[1])
                overlap = max(0.0, min(box[3], best_box[3]) - max(box[1], best_box[1]))
                gap = max(formula.box[0] - box[2], box[0] - formula.box[2], 0)
                if overlap / max(height, 1) >= 0.65 and gap <= max(height * 2, 20):
                    tokens.extend(other_tokens)
                    rows.pop(index)
                    if index < best_index:
                        best_index -= 1
            tokens.append((formula.box, formula.text))
            rows[best_index] = (_bounds([token[0] for token in tokens]), tokens)

    output = [(box, _join_tokens(tokens)) for box, tokens in rows] + display_rows
    output.sort(key=lambda row: (row[0][1], row[0][0]))
    return "\n".join(text for _box, text in output if text).strip()


def recognize_document(
    image_path: Path,
    text_image_path: Path,
    engine: FormulaEngine,
    *,
    language: str = "auto",
    timeout: float = 50.0,
) -> str:
    """Recognize formulas in memory and send a masked temporary image to OCR.

    Both disk paths belong to the caller, which deletes them on every outcome.
    The supplied source file is never modified, and no image is uploaded.
    """
    from PIL import Image, ImageDraw
    from ..windows.ocr import recognize_image_lines

    deadline = time.monotonic() + timeout
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    regions = engine.detect(image)
    if len(regions) > 24:
        raise ValueError("选区中的公式过多，请分成较小的区域识别")
    formulas: list[RecognizedFormula] = []
    for region in regions:
        if time.monotonic() >= deadline - 10:
            raise TimeoutError("公式识别超时，请缩小选区")
        # Adding padding can capture neighboring prose and change the formula.
        # Preserve the detector's crop and every meaningful LaTeX style/case.
        latex = engine.recognize(image.crop(region.box)).strip()
        if not latex:
            raise ValueError("有公式未能识别，请放大页面后重新框选")
        formulas.append(RecognizedFormula(region.box, region.kind, latex))

    masked = image.copy()
    draw = ImageDraw.Draw(masked)
    for formula in formulas:
        left, top, right, bottom = formula.box
        draw.rectangle(
            (math.floor(left), math.floor(top), math.ceil(right), math.ceil(bottom)),
            fill="white",
        )
    masked.save(text_image_path, format="BMP")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("OCR 识别超时，请缩小选区")
    lines = recognize_image_lines(text_image_path, language=language, timeout=min(20.0, remaining))
    return merge_layout(lines, formulas)
