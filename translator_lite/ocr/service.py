"""Standard-library client for the optional local formula OCR helper."""

from __future__ import annotations

import atexit
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

from ..math_translation import split_math_parts
from ..windows.ocr import ScreenRegion, WindowsOcrError, capture_screen_region
from ..windows.ocr import recognize_image as recognize_native_image


def _helper_command() -> tuple[list[str], Path] | None:
    if getattr(sys, "frozen", False):
        folder = Path(sys.executable).resolve().parent / "ocr"
        executable = folder / "TranslatorOCR.exe"
        if executable.is_file():
            return [str(executable), "--models", str(folder / "models")], folder
        return None
    root = Path(__file__).resolve().parents[2]
    models = root / ".artifacts" / "ocr-models"
    executable = root / ".artifacts" / "ocr-dist" / "TranslatorOCR" / "TranslatorOCR.exe"
    if executable.is_file():
        return [str(executable), "--models", str(models)], root
    python = root / ".artifacts" / "ocr-env" / "Scripts" / "python.exe"
    if python.is_file() and models.is_dir():
        return [str(python), "-B", "-u", "-m", "translator_lite.ocr.worker", "--models", str(models)], root
    return None


class OcrHelperClient:
    """Serialize requests and keep models warm without blocking the Tk thread."""

    def __init__(self) -> None:
        self._request_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._replies: queue.Queue[str | None] | None = None
        self._closed = False

    @staticmethod
    def _read_replies(process: subprocess.Popen[str], replies: queue.Queue) -> None:
        try:
            assert process.stdout is not None
            for line in process.stdout:
                replies.put(line)
        except (OSError, ValueError):
            # Teardown can close the stream while this daemon reader is active.
            # Notify the requester without emitting protocol contents/logs.
            pass
        finally:
            replies.put(None)

    def _start(self) -> tuple[subprocess.Popen[str], queue.Queue]:
        with self._state_lock:
            if self._closed:
                raise WindowsOcrError("本地 OCR 组件已关闭")
            if (
                self._process is not None
                and self._process.poll() is None
                and self._replies is not None
            ):
                return self._process, self._replies
            if self._process is not None:
                self._stop_process(self._process)
                self._process, self._replies = None, None
            command = _helper_command()
            if command is None:
                raise WindowsOcrError("公式 OCR 组件未安装，请重新运行 OCR 构建脚本")
            arguments, cwd = command
            process = subprocess.Popen(
                arguments, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            replies: queue.Queue[str | None] = queue.Queue()
            self._process, self._replies = process, replies
            threading.Thread(
                target=self._read_replies, args=(process, replies), daemon=True,
                name="TranslatorOcrReplies",
            ).start()
            return process, replies

    def request(self, payload: dict[str, Any], *, timeout: float = 60.0) -> dict:
        if not math.isfinite(timeout) or timeout <= 0:
            raise WindowsOcrError("本地 OCR 等待超时，请稍后重试")
        deadline = time.monotonic() + timeout
        if not self._request_lock.acquire(timeout=timeout):
            # A queued preview must not kill another in-flight recognition.
            raise WindowsOcrError("本地 OCR 正忙，等待超时，请稍后重试")
        process = None
        try:
            try:
                process, replies = self._start()
                assert process.stdin is not None
                process.stdin.write(json.dumps(payload, ensure_ascii=True) + "\n")
                process.stdin.flush()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                line = replies.get(timeout=remaining)
                if line is None:
                    self._reset(process)
                    raise WindowsOcrError("本地 OCR 组件意外退出，请重新框选")
                response = json.loads(line)
                if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
                    raise ValueError("invalid helper response")
                if not response["ok"]:
                    raise WindowsOcrError("本地 OCR 失败: " + str(response.get("error", "未知错误")))
                if not isinstance(response.get("data"), dict):
                    raise ValueError("invalid helper data")
                return response["data"]
            except queue.Empty as exc:
                self._reset(process)
                raise WindowsOcrError("公式 OCR 识别超时，请缩小选区后重试") from exc
            except (OSError, ValueError, TypeError) as exc:
                self._reset(process)
                raise WindowsOcrError("无法调用本地 OCR 组件，请重新安装 OCR 组件") from exc
        finally:
            self._request_lock.release()

    def _reset(self, expected: subprocess.Popen[str] | None = None) -> None:
        """Discard a failed channel while permitting the next request to retry."""
        with self._state_lock:
            if expected is not None and self._process is not expected:
                return
            process, self._process = self._process, None
            self._replies = None
        if process is not None:
            self._stop_process(process)

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        """Reap the owned helper and its native OCR children before cleanup."""
        try:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    try:
                        # The helper can be awaiting a PowerShell OCR child.
                        # Killing only its PID would leave that child reading
                        # a screenshot after this client tries to delete it.
                        subprocess.run(
                            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False, timeout=3.0,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3.0)
        except (OSError, subprocess.TimeoutExpired):
            # App shutdown must stay usable even if the OS already reaped it.
            pass
        finally:
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass

    def close(self) -> None:
        """Permanently close this client, including late background requests."""
        with self._state_lock:
            self._closed = True
        self._reset()


_client = OcrHelperClient()
atexit.register(_client.close)


def helper_available() -> bool:
    return _helper_command() is not None


def _temporary_bitmap() -> Path:
    descriptor, name = tempfile.mkstemp(prefix="translator-lite-ocr-", suffix=".bmp")
    os.close(descriptor)
    return Path(name)


def _remove_temporary_bitmap(path: Path) -> None:
    """Retry briefly for releasing Windows handles and report durable failure."""
    original_error = sys.exc_info()[1]
    for attempt in range(3):
        try:
            path.unlink(missing_ok=True)
            return
        except OSError as exc:
            if attempt < 2:
                time.sleep(0.05)
                continue
            message = "临时 OCR 截图清理失败，请关闭 Translator 后清理临时目录"
            if original_error is not None:
                message = f"{original_error}；{message}"
            raise WindowsOcrError(message) from exc


def recognize_image(image_path: Path, *, language: str = "auto", timeout: float = 60.0) -> str:
    """Use local formula OCR when installed, retaining the native-only fallback."""
    if not helper_available():
        return recognize_native_image(image_path, language=language, timeout=timeout)
    text_image = _temporary_bitmap()
    try:
        result = _client.request({
            "op": "recognize", "image_path": str(image_path.resolve()),
            "text_image_path": str(text_image), "language": language,
            "timeout": max(1.0, timeout - 8.0),
        }, timeout=timeout)
        if not isinstance(result.get("text"), str):
            raise WindowsOcrError("本地 OCR 识别结果格式无效")
        return result["text"]
    finally:
        _remove_temporary_bitmap(text_image)


def recognize_screen_region(
    region: ScreenRegion, *, language: str = "auto", timeout: float = 60.0
) -> str:
    image_path = _temporary_bitmap()
    try:
        capture_screen_region(image_path, region)
        return recognize_image(image_path, language=language, timeout=timeout)
    finally:
        _remove_temporary_bitmap(image_path)


def render_formulas(text: str, *, dpi: float = 144, font_size: float = 13) -> dict[str, str]:
    """Return optional previews; an unavailable renderer never discards LaTeX."""
    if not any(is_math for is_math, _part in split_math_parts(text)) or not helper_available():
        return {}
    try:
        data = _client.request(
            {"op": "render", "text": text, "dpi": dpi, "font_size": font_size},
            timeout=15.0,
        )
        images = data.get("images", {})
        if isinstance(images, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in images.items()):
            return images
    except WindowsOcrError:
        pass
    return {}


def close_helper() -> None:
    _client.close()
