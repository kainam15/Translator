import io
import json
from pathlib import Path
import queue
import subprocess
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from translator_lite.ocr import service
from translator_lite.windows.ocr import ScreenRegion, WindowsOcrError


class OcrHelperClientTests(unittest.TestCase):
    def _client(self, response=None):
        client = service.OcrHelperClient()
        process = Mock()
        process.poll.return_value = None
        process.wait.return_value = 0
        replies = queue.Queue()
        if response is not None:
            replies.put(json.dumps(response))
        client._process, client._replies = process, replies
        return client, process, replies

    def test_successful_requests_reuse_process_and_utf8_protocol(self) -> None:
        client, process, replies = self._client({"ok": True, "data": {"text": "结果"}})

        self.assertEqual(client.request({"op": "ping"}), {"text": "结果"})
        replies.put(json.dumps({"ok": True, "data": {"ready": True}}))
        self.assertEqual(client.request({"op": "ping"}), {"ready": True})

        self.assertEqual(process.stdin.flush.call_count, 2)
        process.kill.assert_not_called()
        client.close()

    def test_application_error_keeps_healthy_helper_available(self) -> None:
        client, process, replies = self._client({"ok": False, "error": "recognition failed"})

        with self.assertRaisesRegex(WindowsOcrError, "recognition failed"):
            client.request({"op": "recognize"})
        replies.put(json.dumps({"ok": True, "data": {"ready": True}}))
        self.assertEqual(client.request({"op": "ping"}), {"ready": True})

        process.stdin.close.assert_not_called()
        client.close()

    def test_stdout_eof_discards_the_unusable_process(self) -> None:
        client, process, replies = self._client()
        replies.put(None)

        with self.assertRaisesRegex(WindowsOcrError, "退出"):
            client.request({"op": "ping"})

        self.assertIsNone(client._process)
        process.wait.assert_called()
        process.stdout.close.assert_called()

    def test_protocol_error_discards_process_and_closes_pipes(self) -> None:
        client, process, replies = self._client()
        replies.put("not json")

        with self.assertRaises(WindowsOcrError):
            client.request({"op": "ping"})

        self.assertIsNone(client._process)
        process.stdin.close.assert_called()
        process.stdout.close.assert_called()

    def test_reply_timeout_resets_process_but_allows_next_capture(self) -> None:
        client, first, _replies = self._client()

        with self.assertRaisesRegex(WindowsOcrError, "超时"):
            client.request({"op": "ping"}, timeout=0.001)

        second = Mock()
        second.poll.return_value = None
        second.wait.return_value = 0
        replies = queue.Queue()
        replies.put(json.dumps({"ok": True, "data": {"ready": True}}))
        client._process, client._replies = second, replies
        self.assertEqual(client.request({"op": "ping"}), {"ready": True})
        first.wait.assert_called()
        client.close()

    def test_waiting_for_another_request_counts_toward_timeout(self) -> None:
        client, process, _replies = self._client({"ok": True, "data": {}})
        client._request_lock.acquire()
        finished = threading.Event()
        failures = []

        def request():
            try:
                client.request({"op": "ping"}, timeout=0.01)
            except WindowsOcrError as error:
                failures.append(str(error))
            finally:
                finished.set()

        thread = threading.Thread(target=request, daemon=True)
        thread.start()
        try:
            completed_within_budget = finished.wait(0.15)
        finally:
            client._request_lock.release()
            thread.join(1)
        self.assertTrue(completed_within_budget)
        self.assertTrue(failures)
        self.assertIn("超时", failures[0])
        process.stdin.write.assert_not_called()
        client.close()

    @patch("translator_lite.ocr.service.time.monotonic", side_effect=[10.0, 12.0])
    def test_startup_and_write_time_reduce_reply_timeout(self, _clock) -> None:
        client, _process, _queue = self._client()
        replies = Mock()
        replies.get.return_value = json.dumps({"ok": True, "data": {}})
        client._replies = replies

        client.request({"op": "ping"}, timeout=5.0)

        replies.get.assert_called_once_with(timeout=3.0)
        client.close()

    @patch("translator_lite.ocr.service.subprocess.Popen")
    def test_final_close_does_not_allow_late_background_restart(self, popen) -> None:
        client, process, _replies = self._client()
        client.close()
        client.close()

        with self.assertRaisesRegex(WindowsOcrError, "关闭"):
            client.request({"op": "ping"})

        process.wait.assert_called_once()
        popen.assert_not_called()

    def test_reader_ends_cleanly_when_stream_is_closed(self) -> None:
        process = Mock()
        process.stdout = io.StringIO()
        process.stdout.close()
        replies = queue.Queue()

        service.OcrHelperClient._read_replies(process, replies)

        self.assertIsNone(replies.get_nowait())

    @patch("translator_lite.ocr.service.subprocess.run")
    def test_stuck_windows_helper_terminates_owned_process_tree(self, run) -> None:
        client, process, _replies = self._client()
        process.pid = 12345
        process.wait.side_effect = [subprocess.TimeoutExpired("helper", 1), 0]
        run.return_value.returncode = 0

        with patch("translator_lite.ocr.service.os.name", "nt"):
            client.close()

        self.assertIn("/PID", run.call_args.args[0])
        self.assertIn("12345", run.call_args.args[0])
        self.assertIn("/T", run.call_args.args[0])
        self.assertIn("/F", run.call_args.args[0])


class OcrCaptureLifecycleTests(unittest.TestCase):
    @patch("translator_lite.ocr.service.time.sleep")
    def test_temporary_cleanup_retries_a_releasing_windows_handle(self, sleep) -> None:
        path = Mock()
        path.unlink.side_effect = [PermissionError("in use"), None]

        service._remove_temporary_bitmap(path)

        self.assertEqual(path.unlink.call_count, 2)
        sleep.assert_called_once_with(0.05)

    @patch("translator_lite.ocr.service.time.sleep")
    def test_persistent_cleanup_failure_keeps_original_ocr_error_visible(self, _sleep) -> None:
        path = Mock()
        path.unlink.side_effect = PermissionError("in use")

        with self.assertRaisesRegex(WindowsOcrError, "recognition failed.*清理失败"):
            try:
                raise WindowsOcrError("recognition failed")
            finally:
                service._remove_temporary_bitmap(path)

        self.assertEqual(path.unlink.call_count, 3)

    @patch("translator_lite.ocr.service._temporary_bitmap")
    @patch("translator_lite.ocr.service.recognize_native_image", return_value="native text")
    @patch("translator_lite.ocr.service.helper_available", return_value=False)
    def test_missing_helper_uses_native_without_extra_mask_file(self, _available, native, temporary) -> None:
        source = Path("source.bmp")

        self.assertEqual(service.recognize_image(source, language="en", timeout=4), "native text")

        native.assert_called_once_with(source, language="en", timeout=4)
        temporary.assert_not_called()

    @patch("translator_lite.ocr.service.helper_available", return_value=True)
    def test_helper_success_and_failure_remove_mask_and_preserve_source(self, _available) -> None:
        for response in ({"text": "recognized"}, WindowsOcrError("helper failed"), {"text": 12}):
            with self.subTest(response=response), TemporaryDirectory() as directory:
                source = Path(directory) / "source.bmp"
                mask = Path(directory) / "masked.bmp"
                source.write_bytes(b"source")
                mask.write_bytes(b"mask")
                request = Mock()
                if isinstance(response, Exception):
                    request.side_effect = response
                else:
                    request.return_value = response
                with patch.object(service, "_temporary_bitmap", return_value=mask):
                    with patch.object(service._client, "request", request):
                        if response == {"text": "recognized"}:
                            self.assertEqual(service.recognize_image(source), "recognized")
                        else:
                            with self.assertRaises(WindowsOcrError):
                                service.recognize_image(source)
                self.assertFalse(mask.exists())
                self.assertEqual(source.read_bytes(), b"source")

    def test_capture_error_always_removes_owned_screenshot(self) -> None:
        with TemporaryDirectory() as directory:
            image = Path(directory) / "capture.bmp"
            image.write_bytes(b"capture")
            with patch.object(service, "_temporary_bitmap", return_value=image):
                with patch.object(service, "capture_screen_region", side_effect=WindowsOcrError("capture failed")):
                    with self.assertRaisesRegex(WindowsOcrError, "capture failed"):
                        service.recognize_screen_region(ScreenRegion(0, 0, 10, 10))
            self.assertFalse(image.exists())

    def test_capture_success_removes_owned_screenshot_and_forwards_options(self) -> None:
        with TemporaryDirectory() as directory:
            image = Path(directory) / "capture.bmp"
            image.write_bytes(b"capture")
            with patch.object(service, "_temporary_bitmap", return_value=image):
                with patch.object(service, "capture_screen_region"):
                    with patch.object(service, "recognize_image", return_value="text") as recognize:
                        region = ScreenRegion(0, 0, 10, 10)
                        self.assertEqual(service.recognize_screen_region(region, language="en", timeout=8), "text")
            recognize.assert_called_once_with(image, language="en", timeout=8)
            self.assertFalse(image.exists())

    @patch("translator_lite.ocr.service.helper_available", return_value=True)
    @patch("translator_lite.ocr.service._client.request", side_effect=WindowsOcrError("unavailable"))
    def test_preview_failure_leaves_raw_formula_available(self, request, _available) -> None:
        self.assertEqual(service.render_formulas(r"\(x^2\)"), {})
        request.assert_called_once()

    @patch("translator_lite.ocr.service._client.request")
    def test_plain_text_does_not_start_render_helper(self, request) -> None:
        self.assertEqual(service.render_formulas("plain text"), {})
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
