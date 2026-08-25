# Repository Guidelines

## Project Structure & Module Organization

The flat layout is intentional. `google_translate_client.py` owns Google Translate RPC transport and parsing. `desktop_app.py` implements the Tkinter interface; `windows_hotkey.py`, `windows_selection.py`, and `windows_tray.py` isolate native Windows behavior. `Translator.pyw` is the desktop entry point, while `app.py` serves `static/index.html`. Assets live in `assets/`, tests use root-level `test_*.py` files, and packaging uses `Translator.spec` plus `build_exe.ps1`. Treat `dist/`, `build/`, and `__pycache__/` as generated output.

## Build, Test, and Development Commands

Run these from PowerShell at the repository root:

- `pythonw .\Translator.pyw` starts the desktop app without a console window.
- `python -X utf8 .\app.py` starts the browser tester at `http://127.0.0.1:8000`.
- `python -X utf8 .\google_translate_client.py "Hello" --to zh-CN` exercises the translation client directly.
- `python -m unittest -v` runs the complete test suite.
- `python -m pip install PyInstaller` installs the build-only dependency.
- `.\build_exe.ps1` creates the Windows executable in `dist\Translator.exe`.

Use `-X utf8` when redirected output may contain Chinese text. If PowerShell blocks scripts, run `powershell -ExecutionPolicy Bypass -File .\build_exe.ps1`.

## Coding Style & Naming Conventions

Use four-space indentation and PEP 8 layout. Use `snake_case` for modules, functions, and variables; `PascalCase` for classes; `UPPER_CASE` for constants. Type-hint public and platform-boundary APIs. Keep Win32 `ctypes` declarations explicit, including `argtypes`, `restype`, and structure fields. Preserve the standard-library-only runtime; justify new packages. No formatter or linter is configured, so match surrounding code.

## Testing Guidelines

Tests use Python `unittest`. Name files `test_<module>.py` and methods `test_<behavior>`. Cover RPC parsing, clipboard/UI Automation fallbacks, hotkeys, tray routing, and high-DPI placement when changed. Never modify the user's real `%APPDATA%\TranslatorLite\settings.json`; use temporary paths and clean up spawned windows or processes. Run the full suite before submitting.

## Commit & Pull Request Guidelines

Follow existing history: write short, feature-focused Chinese commit summaries. Keep commits coherent. Pull requests should explain behavior, list verification commands and results, link issues when applicable, and include screenshots for Tkinter, browser, tray-icon, or DPI-related UI changes. State the Windows version and display scaling tested. Commit generated files only when intentionally updating a release artifact.

## Security & Configuration Tips

The client calls an undocumented Google Translate web RPC that may change. Never commit cookies, API keys, personal settings, or captured private text. Selected text is sent to Google. Any new `Ctrl+C` fallback path must preserve and restore clipboard state.
