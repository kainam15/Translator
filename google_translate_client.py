"""Backward-compatible command and import interface for the translation client."""

from translator_lite.client import (
    DEFAULT_BASE_URL,
    MAX_FRONTEND_TEXT_LENGTH,
    RPC_ID,
    GoogleTranslateError,
    TranslationResult,
    build_request_body,
    main,
    parse_response,
    translate,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "MAX_FRONTEND_TEXT_LENGTH",
    "RPC_ID",
    "GoogleTranslateError",
    "TranslationResult",
    "build_request_body",
    "parse_response",
    "translate",
]


if __name__ == "__main__":
    raise SystemExit(main())
