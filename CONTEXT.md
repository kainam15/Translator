# Project Context

## Domain Language

- **Translation Client**: builds the Google Translate web RPC request and turns its response into a `TranslationResult`.
- **Desktop App**: owns the Tkinter window lifecycle and coordinates translation, selection, hotkeys, and tray events.
- **Settings**: the persisted hotkey, pinned-window position, and window size stored under `%APPDATA%\TranslatorLite`.
- **Selection Capture**: obtains selected text through UI Automation, with a clipboard shortcut fallback.
- **Windows Adapters**: native implementations for global hotkeys, mouse hooks, selection, window positioning and repainting, monitor geometry, and the system tray.
- **Web Tester**: a local-only HTTP interface used to exercise the Translation Client from a browser.

## Constraints

- Keep the application runtime dependency-free outside the Python standard library.
- Treat the Google Translate web RPC as unstable and unsuitable for guaranteed production availability.
- Preserve the lightweight native Windows experience and the tray-resident lifecycle.
