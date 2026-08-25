"""Minimal client for the Google Translate web frontend's internal RPC.

This is not the supported Google Cloud Translation API.  The web endpoint and
its response shape can change without notice.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


RPC_ID = "MkEWBc"
DEFAULT_BASE_URL = "https://translate.google.com.tw"
MAX_FRONTEND_TEXT_LENGTH = 5_000


class GoogleTranslateError(RuntimeError):
    """Raised when the internal web endpoint cannot be called or parsed."""


@dataclass(frozen=True)
class TranslationResult:
    text: str
    detected_source_language: str | None
    target_language: str

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def build_request_body(text: str, source: str, target: str) -> bytes:
    """Build the form body used by the TranslateWebserverUi frontend."""
    if not isinstance(text, str) or not text:
        raise ValueError("text 必须是非空字符串")
    if len(text) > MAX_FRONTEND_TEXT_LENGTH:
        raise ValueError(
            f"text 超过 Google Translate 前端的 {MAX_FRONTEND_TEXT_LENGTH} 字符限制"
        )
    if not isinstance(source, str) or not source:
        raise ValueError("source 必须是语言代码或 auto")
    if not isinstance(target, str) or not target:
        raise ValueError("target 必须是语言代码")

    rpc_arguments = json.dumps(
        [[text, source, target, True], [None]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    batch = [[[RPC_ID, rpc_arguments, None, "generic"]]]
    f_req = json.dumps(batch, ensure_ascii=False, separators=(",", ":"))
    return urlencode({"f.req": f_req}).encode("utf-8")


def _find_rpc_payload(response_text: str) -> list[Any]:
    """Remove the XSSI prefix and decode the nested MkEWBc response."""
    marker = '[["wrb.fr"'
    start = response_text.find(marker)
    if start < 0:
        raise GoogleTranslateError("响应中没有找到 wrb.fr RPC 数据")

    try:
        batch, _ = json.JSONDecoder().raw_decode(response_text[start:])
    except json.JSONDecodeError as exc:
        raise GoogleTranslateError("无法解析 batchexecute 外层响应") from exc

    for entry in batch:
        if (
            isinstance(entry, list)
            and len(entry) >= 3
            and entry[0] == "wrb.fr"
            and entry[1] == RPC_ID
            and isinstance(entry[2], str)
        ):
            try:
                payload = json.loads(entry[2])
            except json.JSONDecodeError as exc:
                raise GoogleTranslateError("无法解析 MkEWBc 内层响应") from exc
            if isinstance(payload, list):
                return payload

    raise GoogleTranslateError("响应中没有找到 MkEWBc RPC 结果")


def parse_response(response_text: str, target: str) -> TranslationResult:
    """Extract translated segments and detected source language."""
    payload = _find_rpc_payload(response_text)

    try:
        segments = payload[1][0][0][5]
    except (IndexError, TypeError) as exc:
        raise GoogleTranslateError("MkEWBc 响应结构已变化，无法定位译文") from exc

    if not isinstance(segments, list):
        raise GoogleTranslateError("MkEWBc 响应中的译文分段格式无效")

    translated_parts = [
        segment[0]
        for segment in segments
        if isinstance(segment, list)
        and segment
        and isinstance(segment[0], str)
    ]
    if not translated_parts:
        raise GoogleTranslateError("MkEWBc 响应中没有译文")

    detected = payload[2] if len(payload) > 2 and isinstance(payload[2], str) else None
    return TranslationResult(
        text="".join(translated_parts),
        detected_source_language=detected,
        target_language=target,
    )


def translate(
    text: str,
    *,
    source: str = "auto",
    target: str = "zh-CN",
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 15.0,
) -> TranslationResult:
    """Translate text by replaying the web frontend's MkEWBc request."""
    parsed_base_url = urlparse(base_url)
    if parsed_base_url.scheme != "https" or not parsed_base_url.netloc:
        raise ValueError("base_url 必须是有效的 HTTPS URL")

    endpoint = (
        f"{base_url.rstrip('/')}/_/TranslateWebserverUi/data/batchexecute"
        f"?rpcids={RPC_ID}"
    )
    request = Request(
        endpoint,
        data=build_request_body(text, source, target),
        method="POST",
        headers={
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": base_url.rstrip("/"),
            "Referer": f"{base_url.rstrip('/')}/",
            "X-Same-Domain": "1",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            response_text = response.read().decode("utf-8")
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:300]
        raise GoogleTranslateError(f"Google 返回 HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise GoogleTranslateError(f"无法连接 Google Translate: {exc.reason}") from exc

    return parse_response(response_text, target)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="调用 Google Translate 网页前端的内部 MkEWBc RPC"
    )
    parser.add_argument("text", help="待翻译文本")
    parser.add_argument("--from", dest="source", default="auto", help="源语言代码")
    parser.add_argument("--to", dest="target", default="zh-CN", help="目标语言代码")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Google Translate 域名")
    parser.add_argument("--timeout", type=float, default=15.0, help="超时秒数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = translate(
            args.text,
            source=args.source,
            target=args.target,
            base_url=args.base_url,
            timeout=args.timeout,
        )
    except (GoogleTranslateError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    else:
        print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
