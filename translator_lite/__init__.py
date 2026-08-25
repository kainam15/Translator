"""Public interface for Translator Lite without eager submodule imports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .client import GoogleTranslateError, TranslationResult, translate

__all__ = ["GoogleTranslateError", "TranslationResult", "translate"]
__version__ = "0.1.0"


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import client

        return getattr(client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
