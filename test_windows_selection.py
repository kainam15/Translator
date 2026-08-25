import ctypes
import unittest

from windows_selection import GUID


class WindowsSelectionTests(unittest.TestCase):
    def test_guid_layout_matches_com_abi(self) -> None:
        self.assertEqual(ctypes.sizeof(GUID), 16)


if __name__ == "__main__":
    unittest.main()
