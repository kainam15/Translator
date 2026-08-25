"""Persistent desktop settings with backward-compatible JSON parsing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..windows.hotkey import DEFAULT_HOTKEY, HotkeySpec


SETTINGS_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "TranslatorLite"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


@dataclass(frozen=True)
class AppSettings:
    hotkey: HotkeySpec
    position_pinned: bool = False
    window_position: tuple[int, int] | None = None
    window_size: tuple[int, int] | None = None


def settings_from_payload(payload: object) -> AppSettings:
    """Parse settings defensively and accept legacy hotkey-only files."""
    if not isinstance(payload, dict):
        return AppSettings(DEFAULT_HOTKEY)

    try:
        hotkey = HotkeySpec.from_dict(payload.get("hotkey"))
    except ValueError:
        hotkey = DEFAULT_HOTKEY

    raw_position = payload.get("window_position")
    position: tuple[int, int] | None = None
    if isinstance(raw_position, dict):
        x = raw_position.get("x")
        y = raw_position.get("y")
        if (
            isinstance(x, int)
            and not isinstance(x, bool)
            and isinstance(y, int)
            and not isinstance(y, bool)
        ):
            position = (x, y)

    position_pinned = payload.get("position_pinned") is True and position is not None

    raw_size = payload.get("window_size")
    window_size: tuple[int, int] | None = None
    if isinstance(raw_size, dict):
        width = raw_size.get("width")
        height = raw_size.get("height")
        if (
            isinstance(width, int)
            and not isinstance(width, bool)
            and width > 0
            and isinstance(height, int)
            and not isinstance(height, bool)
            and height > 0
        ):
            window_size = (width, height)

    return AppSettings(hotkey, position_pinned, position, window_size)


def settings_to_payload(settings: AppSettings) -> dict[str, object]:
    position = None
    if settings.window_position is not None:
        position = {
            "x": settings.window_position[0],
            "y": settings.window_position[1],
        }
    window_size = None
    if settings.window_size is not None:
        window_size = {
            "width": settings.window_size[0],
            "height": settings.window_size[1],
        }
    return {
        "hotkey": settings.hotkey.to_dict(),
        "position_pinned": settings.position_pinned,
        "window_position": position,
        "window_size": window_size,
    }


def load_settings(path: Path | None = None) -> AppSettings:
    settings_path = path or SETTINGS_FILE
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        return settings_from_payload(payload)
    except (OSError, json.JSONDecodeError):
        return AppSettings(DEFAULT_HOTKEY)


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    settings_path = path or SETTINGS_FILE
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = settings_path.with_suffix(settings_path.suffix + ".tmp")
    temp_file.write_text(
        json.dumps(settings_to_payload(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_file.replace(settings_path)
