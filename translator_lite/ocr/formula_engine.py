"""CPU ONNX inference for the Pix2Text 1.5 formula models.

The optional OCR helper installs numpy, onnxruntime, Pillow, and tokenizers.
Importing this module itself does not load these optional packages. Model files
stay outside the executable in ``mfd/`` and ``mfr/`` under ``model_dir``.

Model documentation: https://huggingface.co/breezedeus/pix2text-mfr-1.5
Model provenance and conflicting MFD license metadata: docs/ocr-models.md.
Detection follows the exported YOLO model's RGB letterbox and class-wise NMS.
Recognition follows its DeiT preprocessing and cache-free greedy generation.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, Literal, Sequence

if TYPE_CHECKING:
    from PIL import Image


Box = tuple[float, float, float, float]
FORMULA_FILES = (
    "mfd/pix2text-mfd-1.5.onnx",
    "mfr/encoder_model.onnx",
    "mfr/decoder_model.onnx",
    "mfr/tokenizer.json",
    "mfr/config.json",
    "mfr/preprocessor_config.json",
    "mfr/generation_config.json",
)


@dataclass(frozen=True)
class FormulaRegion:
    """One formula rectangle in the original image's pixel coordinates."""

    box: Box
    kind: Literal["inline", "display"]
    score: float


@dataclass(frozen=True)
class _Letterbox:
    width: int
    height: int
    left: int
    top: int
    ratio: float
    original_size: tuple[int, int]
    padded_size: tuple[int, int]


def _letterbox_geometry(
    original_size: tuple[int, int], target_size: tuple[int, int],
    *, stride: int | None = None,
) -> _Letterbox:
    width, height = original_size
    target_width, target_height = target_size
    if min(width, height, target_width, target_height) <= 0:
        raise ValueError("OCR image dimensions must be positive")
    ratio = min(target_width / width, target_height / height)
    resized_width = round(width * ratio)
    resized_height = round(height * ratio)
    pad_width = target_width - resized_width
    pad_height = target_height - resized_height
    if stride is not None:
        if stride <= 0:
            raise ValueError("Detector stride must be positive")
        # Dynamic YOLO exports use the smallest stride-aligned rectangle.
        pad_width %= stride
        pad_height %= stride
    # This is YOLO's centered LetterBox rounding, including odd padding.
    left = round(pad_width / 2 - 0.1)
    top = round(pad_height / 2 - 0.1)
    return _Letterbox(
        resized_width, resized_height, left, top, ratio, original_size,
        (resized_width + pad_width, resized_height + pad_height),
    )


def _restore_box(box: Sequence[float], geometry: _Letterbox) -> Box:
    width, height = geometry.original_size
    left, top, right, bottom = box
    return (
        max(0.0, min(float(width), (left - geometry.left) / geometry.ratio)),
        max(0.0, min(float(height), (top - geometry.top) / geometry.ratio)),
        max(0.0, min(float(width), (right - geometry.left) / geometry.ratio)),
        max(0.0, min(float(height), (bottom - geometry.top) / geometry.ratio)),
    )


def _intersection_over_union(first: Box, second: Box) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    intersection = width * height
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _suppress_overlaps(
    regions: Sequence[FormulaRegion], threshold: float = 0.45, limit: int = 100
) -> list[FormulaRegion]:
    """Class-wise NMS; nested formulas of different classes remain visible."""
    kept: list[FormulaRegion] = []
    # Bound the quadratic step even if a damaged model emits dense detections.
    candidates = sorted(regions, key=lambda item: item.score, reverse=True)[:3000]
    for candidate in candidates:
        if any(
            old.kind == candidate.kind
            and _intersection_over_union(old.box, candidate.box) > threshold
            for old in kept
        ):
            continue
        kept.append(candidate)
        if len(kept) >= limit:
            break
    return sorted(kept, key=lambda item: (item.box[1], item.box[0]))


def _formula_kind(name: str) -> Literal["inline", "display"]:
    lowered = name.lower().replace("-", "_")
    if lowered in {"embedding", "embedded", "inline", "inline_formula"}:
        return "inline"
    if lowered in {"isolated", "display", "display_formula", "isolated_formula"}:
        return "display"
    raise ValueError(f"Unsupported formula detector class: {name!r}")


class FormulaEngine:
    """Detect formula regions and transcribe individual crops into LaTeX."""

    def __init__(self, model_dir: Path, *, max_new_tokens: int = 256) -> None:
        if not 1 <= max_new_tokens <= 512:
            raise ValueError("max_new_tokens must be between 1 and 512")
        self.model_dir = Path(model_dir)
        missing = [
            name for name in FORMULA_FILES
            if not (self.model_dir / name).is_file()
        ]
        if missing:
            raise FileNotFoundError("Missing formula OCR models: " + ", ".join(missing))
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.detector = ort.InferenceSession(
            str(self.model_dir / FORMULA_FILES[0]),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.encoder = ort.InferenceSession(
            str(self.model_dir / FORMULA_FILES[1]),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.decoder = ort.InferenceSession(
            str(self.model_dir / FORMULA_FILES[2]),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = Tokenizer.from_file(
            str(self.model_dir / "mfr/tokenizer.json")
        )
        self.config = self._read_config("config.json")
        self.processor = self._read_config("preprocessor_config.json")
        self.generation = self._read_config("generation_config.json")
        self.max_new_tokens = max_new_tokens
        self.detector_kinds = self._detector_kinds()
        self._check_model_interfaces()

    def _read_config(self, name: str) -> dict[str, Any]:
        return json.loads((self.model_dir / "mfr" / name).read_text(encoding="utf-8"))

    def _detector_kinds(self) -> dict[int, Literal["inline", "display"]]:
        raw_names = self.detector.get_modelmeta().custom_metadata_map.get("names")
        if not raw_names:
            raise ValueError("Formula detector metadata is missing class names")
        try:
            names = json.loads(raw_names)
        except json.JSONDecodeError:
            names = ast.literal_eval(raw_names)
        if isinstance(names, list):
            names = dict(enumerate(names))
        if not isinstance(names, dict):
            raise ValueError("Invalid formula detector class names")
        result = {
            int(label): _formula_kind(str(name)) for label, name in names.items()
        }
        if set(result) != set(range(len(result))):
            raise ValueError("Formula detector classes must be contiguous")
        return result

    def _check_model_interfaces(self) -> None:
        if len(self.detector.get_inputs()) != 1 or len(self.encoder.get_inputs()) != 1:
            raise ValueError("Unexpected formula model inputs")
        decoder_inputs = {item.name for item in self.decoder.get_inputs()}
        supported = {"input_ids", "encoder_hidden_states", "encoder_attention_mask"}
        if not {"input_ids", "encoder_hidden_states"} <= decoder_inputs <= supported:
            raise ValueError(f"Unsupported formula decoder inputs: {decoder_inputs}")
        if "logits" not in {item.name for item in self.decoder.get_outputs()}:
            raise ValueError("Formula decoder has no logits output")
        if self.processor.get("do_center_crop", False):
            raise ValueError("Center-cropped formula preprocessors are not supported")

    def detect(self, image: Image.Image) -> list[FormulaRegion]:
        """Return formula boxes without sending the captured image over a network."""
        import numpy as np
        from PIL import Image as PilImage

        model_input = self.detector.get_inputs()[0]
        shape = model_input.shape
        target_height = shape[2] if isinstance(shape[2], int) else 768
        target_width = shape[3] if isinstance(shape[3], int) else 768
        dynamic_shape = not isinstance(shape[2], int) and not isinstance(shape[3], int)
        metadata = self.detector.get_modelmeta().custom_metadata_map
        stride = int(metadata.get("stride", "32")) if dynamic_shape else None
        geometry = _letterbox_geometry(
            image.size, (target_width, target_height), stride=stride
        )
        resized = image.convert("RGB").resize(
            (geometry.width, geometry.height), PilImage.Resampling.BILINEAR
        )
        canvas = PilImage.new("RGB", geometry.padded_size, (114, 114, 114))
        canvas.paste(resized, (geometry.left, geometry.top))
        pixels = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        predictions = np.asarray(
            self.detector.run(None, {model_input.name: np.ascontiguousarray(pixels)})[0]
        )
        channels = 4 + len(self.detector_kinds)
        if predictions.ndim != 3 or predictions.shape[0] != 1:
            raise ValueError(f"Unexpected detector output shape: {predictions.shape}")
        values = predictions[0]
        if values.shape[0] == channels:
            values = values.T
        elif values.shape[1] != channels:
            raise ValueError(f"Unexpected detector output shape: {predictions.shape}")
        regions: list[FormulaRegion] = []
        labels = values[:, 4:].argmax(axis=1)
        scores = values[np.arange(len(values)), labels + 4]
        confident = scores >= 0.25
        for row, label, score in zip(
            values[confident], labels[confident], scores[confident]
        ):
            center_x, center_y, width, height = (float(value) for value in row[:4])
            if not all(
                math.isfinite(value)
                for value in (center_x, center_y, width, height, float(score))
            ):
                continue
            if width <= 0 or height <= 0:
                continue
            box = _restore_box(
                (center_x - width / 2, center_y - height / 2,
                 center_x + width / 2, center_y + height / 2), geometry,
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            regions.append(
                FormulaRegion(box, self.detector_kinds[int(label)], float(score))
            )
        return _suppress_overlaps(regions)

    def recognize(self, image: Image.Image) -> str:
        """Transcribe a formula crop, preserving case and mathematical structure.

        Raises instead of returning truncated LaTeX when generation exceeds its
        token or wall-clock bound. No spelling or case substitutions are made.
        """
        import numpy as np
        from PIL import Image as PilImage

        size = self.processor["size"]
        resample = PilImage.Resampling(int(self.processor.get("resample", 3)))
        resized = image.convert("RGB").resize(
            (int(size["width"]), int(size["height"])), resample
        )
        pixels = np.asarray(resized, dtype=np.float32)
        if self.processor.get("do_rescale", True):
            pixels = pixels * np.float32(
                self.processor.get("rescale_factor", 1 / 255)
            )
        if self.processor.get("do_normalize", True):
            mean = np.asarray(self.processor["image_mean"], dtype=np.float32)
            std = np.asarray(self.processor["image_std"], dtype=np.float32)
            pixels = (pixels - mean) / std
        pixels = np.ascontiguousarray(pixels.transpose(2, 0, 1)[None])
        start_time = time.monotonic()
        encoded = self.encoder.run(
            None, {self.encoder.get_inputs()[0].name: pixels}
        )[0]
        start = int(self.generation.get(
            "decoder_start_token_id", self.config["decoder_start_token_id"]
        ))
        eos = int(self.generation.get("eos_token_id", self.config["eos_token_id"]))
        tokens = [start]
        decoder_inputs = {item.name for item in self.decoder.get_inputs()}
        for _ in range(self.max_new_tokens):
            if time.monotonic() - start_time > 30.0:
                raise TimeoutError("Formula recognition exceeded 30 seconds")
            feed = {
                "input_ids": np.asarray([tokens], dtype=np.int64),
                "encoder_hidden_states": encoded,
            }
            if "encoder_attention_mask" in decoder_inputs:
                feed["encoder_attention_mask"] = np.ones(
                    encoded.shape[:2], dtype=np.int64
                )
            logits = self.decoder.run(["logits"], feed)[0]
            next_token = int(np.argmax(logits[0, -1]))
            if next_token == eos:
                return self.tokenizer.decode(
                    tokens[1:], skip_special_tokens=True
                ).strip()
            tokens.append(next_token)
        raise RuntimeError(f"Formula exceeded the {self.max_new_tokens}-token recognition limit")
