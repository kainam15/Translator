import unittest

import translator_lite
from translator_lite.client import translate


class PackageInterfaceTests(unittest.TestCase):
    def test_translate_is_exposed_from_package(self) -> None:
        self.assertIs(translator_lite.translate, translate)

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        with self.assertRaises(AttributeError):
            getattr(translator_lite, "missing")


if __name__ == "__main__":
    unittest.main()
