# Repository Guidelines

## Project Structure & Module Organization

Runtime code lives in the `translator_lite/` package. `client.py` implements translation transport and parsing. `desktop/` owns the Tkinter app, persisted settings, and window placement. Native Windows implementations belong in `windows/`; the local HTTP tester and its page live in `web/`. Package resources are under `assets/`. Keep tests in `tests/`, build automation in `scripts/`, and PyInstaller configuration in `Translator.spec`. Root files `Translator.pyw`, `app.py`, and `google_translate_client.py` are compatibility launchers; keep them thin. Domain responsibilities and constraints are documented in `CONTEXT.md`.

## Build, Test, and Development Commands

Run these from PowerShell at the repository root:

- `python -m pip install -e .` installs editable commands for development.
- `python -m translator_lite` starts the desktop app.
- `python -X utf8 -m translator_lite.web.server` starts the tester at `http://127.0.0.1:8000`.
- `python -B -m unittest discover -s tests -v` runs all tests without writing bytecode.
- `python -m pip install -e ".[build]"` installs the PyInstaller build extra.
- `.\scripts\build_exe.ps1` creates `dist\Translator.exe`.

## Coding Style & Naming Conventions

Use four spaces and PEP 8 layout. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; `UPPER_CASE` for constants. Type-hint public and platform-facing interfaces. Keep Win32 `ctypes` declarations explicit, including `argtypes`, `restype`, and structure fields. Runtime code must remain standard-library-only unless a change documents and justifies a new dependency. Prefer relative imports inside the package.

## Testing Guidelines

Tests use `unittest`. Name files `test_<module>.py` and methods `test_<behavior>`. Match tests to package seams: settings tests use temporary paths, Windows tests verify ABI layouts and message routing, and UI tests must clean up every window or process. Add regression coverage for RPC parsing, selection fallbacks, hotkeys, mouse hooks, tray lifecycle, resizing, and high-DPI placement when changed.

## Commit & Pull Request Guidelines

Follow repository history with short, feature-focused Chinese commit summaries. Keep commits coherent. Pull requests must describe user-visible behavior, list verification commands and results, and link issues when applicable. Include screenshots for Tkinter, browser, tray-icon, or DPI changes, plus the tested Windows version and display scaling.

## Security & Release Notes

Never commit generated `dist/`, `build/`, bytecode, secrets, settings, or captured text. Selected text is sent to Google. The undocumented web RPC is unstable; do not present it as a guaranteed production interface. A public release also requires an explicit maintainer-selected `LICENSE`.
