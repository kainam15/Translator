"""Local, persistent OCR helper using newline-delimited JSON over stdio."""

from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import sys

from .document import recognize_document
from .formula_engine import FORMULA_FILES, FormulaEngine
from .rendering import render_formulas


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Translator local formula OCR helper")
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args(argv)
    engine = None
    # PyInstaller's console helper is always started with CREATE_NO_WINDOW.
    # stdout is reserved for protocol replies, never diagnostics or OCR logs.
    input_stream, output_stream = sys.stdin, sys.stdout
    for request_line in input_stream:
        try:
            request = json.loads(request_line)
            if not isinstance(request, dict):
                raise ValueError("无效的 OCR 请求")
            with contextlib.redirect_stdout(sys.stderr):
                operation = request.get("op")
                if operation == "ping":
                    data = {"ready": all((args.models / path).is_file() for path in FORMULA_FILES)}
                elif operation == "recognize":
                    if engine is None:
                        engine = FormulaEngine(args.models)
                    text = recognize_document(
                        Path(request["image_path"]), Path(request["text_image_path"]),
                        engine, language=request.get("language", "auto"),
                        timeout=min(50.0, float(request.get("timeout", 50.0))),
                    )
                    data = {"text": text}
                elif operation == "render":
                    data = {"images": render_formulas(
                        request["text"], dpi=float(request.get("dpi", 144)),
                        font_size=float(request.get("font_size", 13)), color="#18181B",
                    )}
                else:
                    raise ValueError("未知 OCR 操作")
            response = {"ok": True, "data": data}
        except Exception as exc:
            # Do not echo request payloads, screenshots, or recognized text.
            response = {"ok": False, "error": str(exc) or "本地 OCR 失败"}
        output_stream.write(json.dumps(response, ensure_ascii=True) + "\n")
        output_stream.flush()


if __name__ == "__main__":
    main()
