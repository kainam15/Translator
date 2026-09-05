"""Model downloads must not replace valid files with truncated/corrupt bytes."""

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.setup_ocr import ModelFile, download_file, verify_file


class ModelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.target = self.directory / "model.onnx"
        self.payload = b"verified ONNX bytes"
        self.specification = ModelFile(
            "mfd", "model.onnx", len(self.payload),
            hashlib.sha256(self.payload).hexdigest(),
        )

    def test_complete_verified_download_atomically_replaces_previous_file(self):
        self.target.write_bytes(b"previous model")
        with mock.patch("scripts.setup_ocr.urllib.request.urlopen",
                        return_value=io.BytesIO(self.payload)):
            download_file(self.target, self.specification)
        self.assertTrue(verify_file(self.target, self.specification))
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_truncated_download_preserves_previous_file_and_cleans_temporary_file(self):
        self.target.write_bytes(b"previous model")
        with mock.patch("scripts.setup_ocr.urllib.request.urlopen",
                        return_value=io.BytesIO(self.payload[:3])):
            with self.assertRaises(ValueError):
                download_file(self.target, self.specification)
        self.assertEqual(self.target.read_bytes(), b"previous model")
        self.assertEqual(list(self.directory.iterdir()), [self.target])

    def test_same_size_corruption_is_rejected_by_checksum(self):
        self.target.write_bytes(b"previous model")
        corrupt = b"x" * len(self.payload)
        with mock.patch("scripts.setup_ocr.urllib.request.urlopen",
                        return_value=io.BytesIO(corrupt)):
            with self.assertRaises(ValueError):
                download_file(self.target, self.specification)
        self.assertEqual(self.target.read_bytes(), b"previous model")
        self.assertEqual(list(self.directory.iterdir()), [self.target])


if __name__ == "__main__":
    unittest.main()
