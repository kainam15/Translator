"""Translate prose while keeping explicitly delimited LaTeX local and intact."""

from __future__ import annotations

import re
import time

from .client import (
    GoogleTranslateError,
    TranslationResult,
    build_request_body,
    translate,
)


_DELIMITER = re.compile(r"\\(?:\(|\)|\[|\])")
_PARAGRAPH_BREAK = re.compile(r"\r?\n[^\S\r\n]*\r?\n")
_CLOSING_DELIMITER = {r"\(": r"\)", r"\[": r"\]"}


def _math_spans(text: str) -> list[tuple[int, int]]:
    """Find nonempty, matched math spans without consuming broken paragraphs."""
    spans: list[tuple[int, int]] = []
    opening: re.Match[str] | None = None
    for delimiter in _DELIMITER.finditer(text):
        preceding = delimiter.start() - 1
        while preceding >= 0 and text[preceding] == "\\":
            preceding -= 1
        if (delimiter.start() - preceding - 1) % 2:
            # A doubled backslash is a literal slash / LaTeX line break.
            continue

        token = delimiter.group()
        if token in _CLOSING_DELIMITER:
            # Resynchronize at a new opener after an unclosed earlier one.
            opening = delimiter
        elif opening is not None:
            body = text[opening.end():delimiter.start()]
            if (
                token == _CLOSING_DELIMITER[opening.group()]
                and body.strip()
                and not _PARAGRAPH_BREAK.search(body)
            ):
                spans.append((opening.start(), delimiter.end()))
            opening = None
    return spans


def split_math_parts(text: str) -> list[tuple[bool, str]]:
    """Return ordered ``(is_math, original_text)`` parts, retaining delimiters.

    Concatenating every part reproduces the input exactly. Both the helper
    renderer and the editable desktop view use the same conservative parser.
    """
    parts: list[tuple[bool, str]] = []
    cursor = 0
    for start, end in _math_spans(text):
        if start > cursor:
            parts.append((False, text[cursor:start]))
        parts.append((True, text[start:end]))
        cursor = end
    if cursor < len(text):
        parts.append((False, text[cursor:]))
    return parts


def translate_with_math(
    text: str,
    *,
    source: str = "auto",
    target: str = "zh-CN",
    timeout: float = 15.0,
) -> TranslationResult:
    """Translate only prose around ``\\(...\\)`` and ``\\[...\\]`` spans.

    Formulas, punctuation-only separators, and boundary whitespace are copied
    verbatim. All prose requests share one timeout budget. Malformed or empty
    delimiters remain ordinary text, and a formula cannot cross a blank
    paragraph. Inputs without valid math retain the existing client behavior.
    """
    spans = _math_spans(text) if isinstance(text, str) else []
    if not spans:
        return translate(text, source=source, target=target, timeout=timeout)

    # Keep the client validation, including the complete input length limit,
    # even when a pure formula does not require a network request.
    build_request_body(text, source, target)
    deadline = time.monotonic() + timeout
    detected = None if source == "auto" else source
    output: list[str] = []
    cursor = 0

    # The final zero-width span lets the trailing prose use the same path.
    for start, end in [*spans, (len(text), len(text))]:
        prose = text[cursor:start]
        core = prose.strip()
        if any(character.isalpha() for character in core):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GoogleTranslateError("翻译超时，请缩小选区后重试")
            result = translate(
                core, source=source, target=target, timeout=remaining
            )
            if detected is None:
                detected = result.detected_source_language
            leading = len(prose) - len(prose.lstrip())
            trailing = len(prose.rstrip())
            output.append(prose[:leading] + result.text.strip() + prose[trailing:])
        else:
            output.append(prose)
        output.append(text[start:end])
        cursor = end

    return TranslationResult(
        text="".join(output),
        detected_source_language=detected,
        target_language=target,
    )
