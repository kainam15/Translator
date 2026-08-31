# Project Context

## Domain Language

- **Translation Client**: builds the Google Translate web RPC request and turns its response into a `TranslationResult`.
- **Desktop App**: owns the Tkinter window lifecycle and coordinates translation, selection, screen OCR, hotkeys, and tray events.
- **Settings**: the persisted selection/OCR hotkeys, pinned-window position, and window size stored under `%APPDATA%\TranslatorLite`.
- **Selection Capture**: obtains selected text through UI Automation, with a clipboard shortcut fallback.
- **Screen OCR**: lets the user drag a screen rectangle, captures it with Win32 GDI, and recognizes it locally through `Windows.Media.Ocr` before translation.
- **Windows Adapters**: native implementations for global hotkeys, mouse hooks, selection, OCR, window positioning and repainting, monitor geometry, and the system tray.
- **Web Tester**: a local-only HTTP interface used to exercise the Translation Client from a browser.

## Constraints

- Keep the application runtime dependency-free outside the Python standard library.
- Treat the Google Translate web RPC as unstable and unsuitable for guaranteed production availability.
- Preserve the lightweight native Windows experience and the tray-resident lifecycle.
- Delete every temporary OCR screenshot immediately after recognition, including failure paths.
