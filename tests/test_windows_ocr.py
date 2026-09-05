import ctypes
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from translator_lite.windows.ocr import (
    BITMAPINFOHEADER,
    ScreenRegion,
    WindowsOcrError,
    recognize_image,
    recognize_screen_region,
)


class WindowsOcrTests(unittest.TestCase):
    def test_bitmap_header_matches_windows_abi(self) -> None:
        self.assertEqual(ctypes.sizeof(BITMAPINFOHEADER), 40)

    def test_screen_region_exposes_edges(self) -> None:
        region = ScreenRegion(-200, 40, 640, 320)

        self.assertEqual(region.right, 440)
        self.assertEqual(region.bottom, 360)

    def test_non_positive_region_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ScreenRegion(0, 0, 0, 20)

    @patch("translator_lite.windows.ocr._powershell_executable")
    @patch("translator_lite.windows.ocr.subprocess.run")
    def test_recognize_image_uses_hidden_encoded_powershell(
        self, run, powershell
    ) -> None:
        powershell.return_value = "powershell.exe"
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps(
            {"text": "Hello OCR\r\n", "language": "en-GB", "english_text": ""}
        )
        run.return_value.stderr = ""
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "sample.bmp"
            image_path.write_bytes(b"BM")

            result = recognize_image(image_path)

        self.assertEqual(result, "Hello OCR")
        command = run.call_args.args[0]
        self.assertIn("-EncodedCommand", command)
        self.assertNotIn(str(image_path), command)
        self.assertEqual(
            run.call_args.kwargs["env"]["TRANSLATOR_LITE_OCR_IMAGE"],
            str(image_path.resolve()),
        )
        self.assertEqual(
            run.call_args.kwargs["env"]["TRANSLATOR_LITE_OCR_LANGUAGE"], "auto"
        )

    @patch("translator_lite.windows.ocr._powershell_executable")
    @patch("translator_lite.windows.ocr.subprocess.run")
    def test_english_page_uses_english_recognition_on_chinese_windows(
        self, run, powershell
    ) -> None:
        powershell.return_value = "powershell.exe"
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({
            "text": "Because ofthis, it is useful tO know hOW tO evaluate a polynomial.",
            "language": "zh-Hans-CN",
            "english_text": "Because of this, it is useful to know how to evaluate a polynomial.",
        })
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "sample.bmp"
            image_path.write_bytes(b"BM")

            result = recognize_image(image_path)

        self.assertEqual(
            result,
            "Because of this, it is useful to know how to evaluate a polynomial.",
        )

    @patch("translator_lite.windows.ocr._powershell_executable")
    @patch("translator_lite.windows.ocr.subprocess.run")
    def test_other_scripts_and_missing_english_keep_original_recognition(
        self, run, powershell
    ) -> None:
        powershell.return_value = "powershell.exe"
        run.return_value.returncode = 0
        cases = (
            ("zh-Hans-CN", "这是中文测试", "garbled English"),
            ("zh-Hans-CN", "使用 Python 计算", "Python"),
            ("ja-JP", "日本語のテスト", "garbled English"),
            ("ko-KR", "한국어 테스트", "garbled English"),
            ("zh-Hans-CN", "123 + 456 = 579", "123 + 456 - 579"),
            ("zh-Hans-CN", "Café déjà vu", "Cafe deja vu"),
            ("zh-Hans-CN", "The angle is θ.", "The angle is O."),
            ("de-DE", "Die Funktion ist linear.", "different text"),
            ("en-GB", "NASA uses Python.", "different text"),
            ("zh-Hans-CN", "Because ofthis", ""),
            ("zh-Hans-CN", "Because ofthis", "  "),
            ("zh-Hans-CN", "", "spurious text"),
        )
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "sample.bmp"
            image_path.write_bytes(b"BM")
            for language, original, english in cases:
                with self.subTest(language=language, original=original):
                    run.return_value.stdout = json.dumps({
                        "text": original,
                        "language": language,
                        "english_text": english,
                    })
                    self.assertEqual(recognize_image(image_path), original)

    @patch("translator_lite.windows.ocr._powershell_executable")
    @patch("translator_lite.windows.ocr.subprocess.run")
    def test_explicit_language_is_passed_without_shell_interpolation(
        self, run, powershell
    ) -> None:
        powershell.return_value = "powershell.exe"
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({
            "text": "NASA uses Python.", "language": "en-GB", "english_text": ""
        })
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "sample.bmp"
            image_path.write_bytes(b"BM")
            self.assertEqual(
                recognize_image(image_path, language="en"), "NASA uses Python."
            )
        self.assertEqual(
            run.call_args.kwargs["env"]["TRANSLATOR_LITE_OCR_LANGUAGE"], "en"
        )
        self.assertNotIn("en", run.call_args.args[0])

    @patch("translator_lite.windows.ocr._powershell_executable")
    @patch("translator_lite.windows.ocr.subprocess.run")
    def test_invalid_native_response_is_reported(self, run, powershell) -> None:
        powershell.return_value = "powershell.exe"
        run.return_value.returncode = 0
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "sample.bmp"
            image_path.write_bytes(b"BM")
            for response in ("not json", "null", "{}", '{"text": 123}'):
                with self.subTest(response=response):
                    run.return_value.stdout = response
                    with self.assertRaisesRegex(WindowsOcrError, "识别结果格式无效"):
                        recognize_image(image_path)

    @patch("translator_lite.windows.ocr._powershell_executable")
    @patch("translator_lite.windows.ocr.subprocess.run")
    def test_recognize_image_reports_windows_ocr_error(
        self, run, powershell
    ) -> None:
        powershell.return_value = "powershell.exe"
        run.return_value.returncode = 1
        run.return_value.stdout = ""
        run.return_value.stderr = "未安装 OCR 语言包"
        with TemporaryDirectory() as directory:
            image_path = Path(directory) / "sample.bmp"
            image_path.write_bytes(b"BM")

            with self.assertRaisesRegex(WindowsOcrError, "未安装 OCR 语言包"):
                recognize_image(image_path)

    @patch(
        "translator_lite.windows.ocr.recognize_image",
        return_value="recognized text",
    )
    @patch("translator_lite.windows.ocr.capture_screen_region")
    def test_temporary_capture_is_deleted(self, capture, _recognize) -> None:
        result = recognize_screen_region(ScreenRegion(10, 20, 100, 80))

        self.assertEqual(result, "recognized text")
        temporary_path = capture.call_args.args[0]
        self.assertFalse(temporary_path.exists())

    @patch(
        "translator_lite.windows.ocr.recognize_image",
        side_effect=WindowsOcrError("recognition failed"),
    )
    @patch("translator_lite.windows.ocr.capture_screen_region")
    def test_failed_recognition_deletes_capture_and_forwards_language(
        self, capture, recognize
    ) -> None:
        with self.assertRaisesRegex(WindowsOcrError, "recognition failed"):
            recognize_screen_region(
                ScreenRegion(10, 20, 100, 80), language="en", timeout=5.0
            )
        temporary_path = capture.call_args.args[0]
        self.assertFalse(temporary_path.exists())
        recognize.assert_called_once_with(temporary_path, language="en", timeout=5.0)


if __name__ == "__main__":
    unittest.main()
