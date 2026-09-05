# Project Context

## Domain Language

- **Translation Client**: builds the Google Translate web RPC request and turns its response into a `TranslationResult`.
- **Desktop App**: owns the Tkinter window lifecycle and coordinates translation, selection, screen OCR, hotkeys, and tray events.
- **Settings**: the persisted selection/OCR hotkeys, pinned-window position, and window size stored under `%APPDATA%\TranslatorLite`.
- **Selection Capture**: obtains selected text through UI Automation, with a clipboard shortcut fallback.
- **Screen OCR**: captures a screen rectangle with Win32 GDI. The standard-library client starts an optional local helper over hidden JSON stdio; absent the helper, it uses `Windows.Media.Ocr` alone.
  The helper detects formula regions, recognizes their LaTeX, masks formulas in a separate temporary image, then joins native text geometry and formulas in reading order. The source-language selector controls native prose OCR; auto mode selects available English recognition per eligible prose line while retaining mixed scripts. It never globally rewrites O/o/0.
- **Formula Helper**: owns optional ONNX Runtime, NumPy, Pillow, Tokenizers, Matplotlib, and externally stored Pix2Text models. It is packaged independently and loaded lazily, keeping heavy dependencies out of the main EXE. Formula previews use local MathText; unsupported LaTeX falls back to source text.
- **Math Document**: retains explicit `\(...\)` / `\[...\]` LaTeX as authoritative data. Desktop views show rendered images while current text extraction and clipboard operations restore exact LaTeX. Desktop translation sends prose fragments to Google, preserving formulas verbatim; the plain translation client and Web Tester retain their existing behavior.
- **Windows Adapters**: native implementations for global hotkeys, mouse hooks, selection, OCR, window positioning and repainting, monitor geometry, and the system tray.
- **Web Tester**: a local-only HTTP interface used to exercise the Translation Client from a browser.

## Constraints

- Keep the main application runtime dependency-free outside the Python standard library. Formula OCR is a documented optional dependency exception in a separate helper environment/process; its pinned build and model provenance live in `scripts/ocr-requirements.txt` and `docs/ocr-models.md`.
- Treat the Google Translate web RPC as unstable and unsuitable for guaranteed production availability.
- Preserve the lightweight native Windows experience and the tray-resident lifecycle.
- Delete every temporary OCR screenshot immediately after recognition, including failure paths.
