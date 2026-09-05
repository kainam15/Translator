"""Windows screen capture and built-in Windows Runtime OCR adapter."""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wintypes
import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0
BITS_PER_PIXEL = 32
MAX_CAPTURE_PIXELS = 100_000_000


class WindowsOcrError(RuntimeError):
    """Raised when screen capture or Windows OCR cannot complete."""


@dataclass(frozen=True)
class OcrWord:
    """Recognized word and its left/top/right/bottom image-pixel bounds."""

    text: str
    box: tuple[float, float, float, float]


@dataclass(frozen=True)
class OcrLine:
    """One recognized line retaining individual word placement."""

    text: str
    words: tuple[OcrWord, ...]

    @property
    def box(self) -> tuple[float, float, float, float]:
        """Return the union of word bounds, or an empty box for an empty line."""
        if not self.words:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            min(word.box[0] for word in self.words),
            min(word.box[1] for word in self.words),
            max(word.box[2] for word in self.words),
            max(word.box[3] for word in self.words),
        )


@dataclass(frozen=True)
class ScreenRegion:
    """A physical-pixel rectangle in virtual-screen coordinates."""

    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        values = (self.left, self.top, self.width, self.height)
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            raise TypeError("OCR 选区坐标必须是整数")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("OCR 选区必须具有正数宽度和高度")

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [
        ("rgbBlue", ctypes.c_ubyte),
        ("rgbGreen", ctypes.c_ubyte),
        ("rgbRed", ctypes.c_ubyte),
        ("rgbReserved", ctypes.c_ubyte),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", RGBQUAD * 1),
    ]


_POWERSHELL_OCR_SCRIPT = r"""
$ProgressPreference = 'SilentlyContinue'
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] > $null
[Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime] > $null
[Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime] > $null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime] > $null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType=WindowsRuntime] > $null
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] > $null
[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime] > $null
[Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime] > $null

$script:asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1
})[0]

function Await-WinRT($operation, [Type]$resultType) {
    $method = $script:asTask.MakeGenericMethod($resultType)
    $task = $method.Invoke($null, @($operation))
    $task.GetAwaiter().GetResult()
}

function Get-OcrLines($ocrResult) {
    foreach ($line in $ocrResult.Lines) {
        $words = @(foreach ($word in $line.Words) {
            $bounds = $word.BoundingRect
            @{
                text = $word.Text
                box = @(
                    [double]$bounds.X
                    [double]$bounds.Y
                    [double]($bounds.X + $bounds.Width)
                    [double]($bounds.Y + $bounds.Height)
                )
            }
        })
        @{ text = $line.Text; words = $words }
    }
}

$stream = $null
$softwareBitmap = $null
try {
    $imagePath = $env:TRANSLATOR_LITE_OCR_IMAGE
    if ([string]::IsNullOrWhiteSpace($imagePath)) {
        throw '没有收到待识别的临时截图'
    }
    $file = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imagePath)) ([Windows.Storage.StorageFile])
    $stream = Await-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $softwareBitmap = Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $requestedLanguage = $env:TRANSLATOR_LITE_OCR_LANGUAGE
    if ([string]::IsNullOrWhiteSpace($requestedLanguage)) {
        $requestedLanguage = 'auto'
    }
    if ($requestedLanguage -eq 'auto') {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
        if ($null -eq $engine) {
            $available = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
            if ($available.Count -gt 0) {
                $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($available[0])
            }
        }
    } else {
        $language = [Windows.Globalization.Language]::new($requestedLanguage)
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
        if ($null -eq $engine) {
            throw "未安装 $requestedLanguage 的 Windows OCR 语言包，请安装该语言包或选择自动检测"
        }
    }
    if ($null -eq $engine) {
        throw '未安装可用的 Windows OCR 语言包'
    }
    $result = Await-WinRT ($engine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])
    $engineLanguage = $engine.RecognizerLanguage.LanguageTag
    $englishText = ''
    $englishLines = @()
    # CJK recognizers can split Latin words and confuse letter case. Reuse the
    # same bitmap and process for an English candidate; Python selects it only
    # when the original result contains ASCII letters and no other letters.
    if ($requestedLanguage -eq 'auto' -and $engineLanguage -match '^(zh|ja|ko)(-|$)' -and $result.Text -match '[a-zA-Z]') {
        try {
            $englishLanguage = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages |
                Where-Object { $_.LanguageTag -match '^en(-|$)' } |
                Select-Object -First 1
            if ($null -ne $englishLanguage) {
                $englishEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($englishLanguage)
                if ($null -ne $englishEngine) {
                    $englishResult = Await-WinRT ($englishEngine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])
                    $englishText = $englishResult.Text
                    $englishLines = @(Get-OcrLines $englishResult)
                }
            }
        } catch {
            # An optional retry must not discard a successful first result.
            $englishText = ''
            $englishLines = @()
        }
    }
    $payload = @{
        text = $result.Text
        language = $engineLanguage
        english_text = $englishText
        lines = @(Get-OcrLines $result)
        english_lines = $englishLines
    } | ConvertTo-Json -Compress -Depth 8
    [Console]::Out.Write($payload)
} catch {
    $message = $_.Exception.Message
    if ([string]::IsNullOrWhiteSpace($message)) {
        $message = 'Windows OCR 调用失败'
    }
    [Console]::Error.Write($message)
    exit 1
} finally {
    if ($null -ne $softwareBitmap) {
        $softwareBitmap.Dispose()
    }
    if ($null -ne $stream) {
        $stream.Dispose()
    }
}
"""


def virtual_screen_bounds() -> ScreenRegion:
    """Return the complete Windows virtual desktop in physical pixels."""
    if not hasattr(ctypes, "WinDLL"):
        return ScreenRegion(0, 0, 1920, 1080)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    user32.GetSystemMetrics.restype = ctypes.c_int
    left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    if width <= 0 or height <= 0:
        return ScreenRegion(0, 0, 1920, 1080)
    return ScreenRegion(left, top, width, height)


def _capture_libraries() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    user32.GetDC.argtypes = (wintypes.HWND,)
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
    user32.ReleaseDC.restype = ctypes.c_int

    gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = (wintypes.HDC,)
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.CreateCompatibleBitmap.argtypes = (
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
    )
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.BitBlt.argtypes = (
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    )
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = (
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
    )
    gdi32.GetDIBits.restype = ctypes.c_int
    return user32, gdi32


def capture_screen_region(destination: Path, region: ScreenRegion) -> None:
    """Capture a physical screen region to a top-down 32-bit BMP file."""
    if not hasattr(ctypes, "WinDLL"):
        raise WindowsOcrError("屏幕 OCR 仅支持 Windows")
    if region.width * region.height > MAX_CAPTURE_PIXELS:
        raise WindowsOcrError("OCR 选区过大，请缩小范围后重试")

    user32, gdi32 = _capture_libraries()
    screen_dc = wintypes.HDC()
    memory_dc = wintypes.HDC()
    bitmap = wintypes.HBITMAP()
    previous_object = wintypes.HGDIOBJ()
    bitmap_selected = False

    try:
        screen_dc = user32.GetDC(None)
        if not screen_dc:
            raise ctypes.WinError(ctypes.get_last_error())
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not memory_dc:
            raise ctypes.WinError(ctypes.get_last_error())
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, region.width, region.height)
        if not bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        previous_object = gdi32.SelectObject(memory_dc, bitmap)
        if not previous_object or previous_object == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        bitmap_selected = True

        if not gdi32.BitBlt(
            memory_dc,
            0,
            0,
            region.width,
            region.height,
            screen_dc,
            region.left,
            region.top,
            SRCCOPY | CAPTUREBLT,
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        if not gdi32.SelectObject(memory_dc, previous_object):
            raise ctypes.WinError(ctypes.get_last_error())
        bitmap_selected = False

        image_size = region.width * region.height * (BITS_PER_PIXEL // 8)
        bitmap_info = BITMAPINFO(
            bmiHeader=BITMAPINFOHEADER(
                biSize=ctypes.sizeof(BITMAPINFOHEADER),
                biWidth=region.width,
                biHeight=-region.height,
                biPlanes=1,
                biBitCount=BITS_PER_PIXEL,
                biCompression=BI_RGB,
                biSizeImage=image_size,
                biXPelsPerMeter=0,
                biYPelsPerMeter=0,
                biClrUsed=0,
                biClrImportant=0,
            )
        )
        pixels = (ctypes.c_ubyte * image_size)()
        scan_lines = gdi32.GetDIBits(
            screen_dc,
            bitmap,
            0,
            region.height,
            ctypes.cast(pixels, ctypes.c_void_p),
            ctypes.byref(bitmap_info),
            DIB_RGB_COLORS,
        )
        if scan_lines != region.height:
            raise ctypes.WinError(ctypes.get_last_error())

        file_header_size = 14
        pixel_offset = file_header_size + ctypes.sizeof(BITMAPINFOHEADER)
        file_size = pixel_offset + image_size
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as bitmap_file:
            bitmap_file.write(
                struct.pack("<2sIHHI", b"BM", file_size, 0, 0, pixel_offset)
            )
            bitmap_file.write(bytes(bitmap_info.bmiHeader))
            bitmap_file.write(bytes(pixels))
    except OSError as exc:
        raise WindowsOcrError(f"截取 OCR 选区失败: {exc}") from exc
    finally:
        if bitmap_selected and memory_dc and previous_object:
            gdi32.SelectObject(memory_dc, previous_object)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        if screen_dc:
            user32.ReleaseDC(None, screen_dc)


def _powershell_executable() -> str:
    system_root = os.environ.get("SystemRoot")
    if system_root:
        candidate = (
            Path(system_root)
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        if candidate.is_file():
            return str(candidate)
    executable = shutil.which("powershell.exe")
    if executable:
        return executable
    raise WindowsOcrError("找不到 Windows PowerShell，无法调用 Windows OCR")


def _parse_payload(output: str) -> dict:
    """Decode the shared text and positioned-lines response."""
    try:
        payload = json.loads(output)
    except (ValueError, TypeError) as exc:
        raise WindowsOcrError("Windows OCR 识别结果格式无效") from exc
    if not isinstance(payload, dict) or not all(
        isinstance(payload.get(key), str)
        for key in ("text", "language", "english_text")
    ):
        raise WindowsOcrError("Windows OCR 识别结果格式无效")
    return payload


def _select_recognized_text(payload: dict) -> str:
    """Prefer the English candidate for ASCII prose read by a CJK engine."""
    original = payload["text"].strip()
    english = payload["english_text"].strip()
    language = payload["language"].lower().split("-")[0]
    if english and language in {"zh", "ja", "ko"}:
        letters = [character for character in original if character.isalpha()]
        # Retain Chinese, mixed scripts, accented prose and Greek variables.
        # Never repair spacing or case by guessing at the recognized words.
        if letters and all(character.isascii() for character in letters):
            return english
    return original


def _run_ocr_payload(
    image_path: Path, *, language: str = "auto", timeout: float = 30.0
) -> dict:
    """Load one bitmap and return all recognition candidates from one process."""
    if not hasattr(ctypes, "WinDLL"):
        raise WindowsOcrError("Windows OCR 仅支持 Windows 10 或更高版本")
    if not image_path.is_file():
        raise WindowsOcrError("OCR 临时截图不存在")

    encoded_script = base64.b64encode(
        _POWERSHELL_OCR_SCRIPT.encode("utf-16-le")
    ).decode("ascii")
    environment = os.environ.copy()
    environment["TRANSLATOR_LITE_OCR_IMAGE"] = str(image_path.resolve())
    environment["TRANSLATOR_LITE_OCR_LANGUAGE"] = language
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [
                _powershell_executable(),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-STA",
                "-EncodedCommand",
                encoded_script,
            ],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=timeout,
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise WindowsOcrError("Windows OCR 识别超时") from exc
    except OSError as exc:
        raise WindowsOcrError(f"无法启动 Windows OCR: {exc}") from exc

    if completed.returncode != 0:
        detail = completed.stderr.strip() or "Windows OCR 返回失败状态"
        detail = detail.replace(str(image_path), "<临时截图>")
        raise WindowsOcrError(f"Windows OCR 失败: {detail}")
    return _parse_payload(completed.stdout)


def _parse_lines(value: object) -> list[OcrLine]:
    """Validate native layout data before using it to place formulas."""
    invalid = "Windows OCR 识别结果格式无效"
    if not isinstance(value, list):
        raise WindowsOcrError(invalid)
    lines = []
    for item in value:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("text"), str)
            or not isinstance(item.get("words"), list)
        ):
            raise WindowsOcrError(invalid)
        words = []
        for word in item["words"]:
            if not isinstance(word, dict) or not isinstance(word.get("text"), str):
                raise WindowsOcrError(invalid)
            box = word.get("box")
            if (
                not isinstance(box, list)
                or len(box) != 4
                or not all(
                    isinstance(coordinate, (int, float))
                    and not isinstance(coordinate, bool)
                    and math.isfinite(coordinate)
                    for coordinate in box
                )
                or box[2] <= box[0]
                or box[3] <= box[1]
            ):
                raise WindowsOcrError(invalid)
            words.append(OcrWord(word["text"], tuple(float(value) for value in box)))
        if item["text"].strip() and not words:
            raise WindowsOcrError(invalid)
        if words:
            lines.append(OcrLine(item["text"], tuple(words)))
    return lines


def _is_ascii_prose(text: str) -> bool:
    letters = [character for character in text if character.isalpha()]
    return bool(letters) and all(character.isascii() for character in letters)


def _line_match_score(first: OcrLine, second: OcrLine) -> float:
    """Find corresponding lines by overlap while respecting columns and rows."""
    a, b = first.box, second.box
    overlap_x = min(a[2], b[2]) - max(a[0], b[0])
    overlap_y = min(a[3], b[3]) - max(a[1], b[1])
    width_a, width_b = a[2] - a[0], b[2] - b[0]
    height_a, height_b = a[3] - a[1], b[3] - b[1]
    if min(width_a, width_b, height_a, height_b) <= 0:
        return 0.0
    if overlap_x < min(width_a, width_b) * 0.5:
        return 0.0
    if overlap_y < min(height_a, height_b) * 0.5:
        return 0.0
    intersection = overlap_x * overlap_y
    return intersection / (width_a * height_a + width_b * height_b - intersection)


def _line_is_covered(fragment: OcrLine, candidate: OcrLine) -> bool:
    """Detect profile fragments already included in a longer English row."""
    a, b = fragment.box, candidate.box
    width, height = a[2] - a[0], a[3] - a[1]
    overlap_x = min(a[2], b[2]) - max(a[0], b[0])
    overlap_y = min(a[3], b[3]) - max(a[1], b[1])
    return (
        width > 0
        and height > 0
        and overlap_y >= max(height, b[3] - b[1]) * 0.75
        and overlap_x * overlap_y >= width * height * 0.85
    )


def _select_recognized_lines(
    payload: dict, *, language: str = "auto"
) -> list[OcrLine]:
    original = _parse_lines(payload.get("lines"))
    english = _parse_lines(payload.get("english_lines", []))
    engine_language = payload["language"].lower().split("-")[0]
    if language != "auto" or engine_language not in {"zh", "ja", "ko"}:
        return original

    # Match globally, best overlap first, so one English line is never inserted
    # twice when the profile recognizer segments the same row differently.
    eligible = [_is_ascii_prose(line.text) for line in original]
    matches = []
    for english_index, candidate in enumerate(english):
        if not candidate.text.strip():
            continue
        # Never replace an ASCII fragment with an English line that also spans
        # a real Chinese/mixed-script fragment from the same row.
        if any(
            not eligible[index] and _line_match_score(line, candidate) > 0
            for index, line in enumerate(original)
        ):
            continue
        for original_index, line in enumerate(original):
            if eligible[original_index]:
                score = _line_match_score(line, candidate)
                if score > 0:
                    matches.append((score, original_index, english_index))
    replacements = {}
    used_english = set()
    consumed_original = set()
    for _score, original_index, english_index in sorted(matches, reverse=True):
        if original_index in consumed_original or english_index in used_english:
            continue
        candidate = english[english_index]
        covered = {original_index}
        covered.update(
            index for index, line in enumerate(original)
            if eligible[index]
            and index not in consumed_original
            and _line_is_covered(line, candidate)
        )
        replacements[min(covered)] = candidate
        consumed_original.update(covered)
        used_english.add(english_index)
    return [
        replacements.get(index, line)
        for index, line in enumerate(original)
        if index not in consumed_original or index in replacements
    ]


def recognize_image(
    image_path: Path, *, language: str = "auto", timeout: float = 30.0
) -> str:
    """Recognize locally, honoring a source language or detecting Latin prose."""
    payload = _run_ocr_payload(image_path, language=language, timeout=timeout)
    return _select_recognized_text(payload)


def recognize_image_lines(
    image_path: Path, *, language: str = "auto", timeout: float = 30.0
) -> list[OcrLine]:
    """Recognize positioned lines, selecting English prose separately per row."""
    payload = _run_ocr_payload(image_path, language=language, timeout=timeout)
    return _select_recognized_lines(payload, language=language)


def recognize_screen_region(
    region: ScreenRegion, *, language: str = "auto", timeout: float = 30.0
) -> str:
    """Capture, recognize, and always delete the temporary screen image."""
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix="translator-lite-ocr-", suffix=".bmp"
    )
    os.close(file_descriptor)
    image_path = Path(temporary_name)
    try:
        capture_screen_region(image_path, region)
        return recognize_image(image_path, language=language, timeout=timeout)
    finally:
        try:
            image_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # The OCR result is more useful than a cleanup error. Windows will
            # release the file when the child PowerShell process exits.
            pass
