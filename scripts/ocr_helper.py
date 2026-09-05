"""Thin entry point for the optional console OCR worker."""

from pathlib import Path
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from translator_lite.ocr.worker import main


if __name__ == "__main__":
    main()
