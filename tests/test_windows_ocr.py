import ctypes
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
        run.return_value.stdout = "Hello OCR\r\n"
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


if __name__ == "__main__":
    unittest.main()
