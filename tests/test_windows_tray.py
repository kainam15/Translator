import queue
import unittest

from translator_lite.windows.tray import (
    MENU_EXIT,
    MENU_SETTINGS,
    MENU_SHOW,
    SystemTray,
    menu_action_for_command,
)


class SystemTrayTests(unittest.TestCase):
    def test_menu_commands_map_to_expected_actions(self) -> None:
        self.assertEqual(menu_action_for_command(MENU_SHOW), "show")
        self.assertEqual(menu_action_for_command(MENU_SETTINGS), "settings")
        self.assertEqual(menu_action_for_command(MENU_EXIT), "exit")
        self.assertIsNone(menu_action_for_command(0))

    def test_custom_icon_is_loaded_once_and_owned(self) -> None:
        class FakeUser32:
            def __init__(self) -> None:
                self.paths: list[str] = []

            def LoadImageW(self, _instance, path, *_args):
                self.paths.append(path)
                return 321

            def LoadIconW(self, *_args):
                raise AssertionError("custom icon should not use the fallback")

        user32 = FakeUser32()
        tray = SystemTray(
            queue.Queue(), icon_path="translator_lite/assets/translator_icon.ico"
        )

        self.assertEqual(tray._load_icon(user32), 321)
        self.assertEqual(tray._load_icon(user32), 321)
        self.assertEqual(len(user32.paths), 1)
        self.assertTrue(tray._owns_icon)

    def test_missing_custom_icon_uses_windows_fallback(self) -> None:
        class FakeUser32:
            def LoadImageW(self, *_args):
                return 0

            def LoadIconW(self, *_args):
                return 654

        tray = SystemTray(queue.Queue(), icon_path="missing.ico")

        self.assertEqual(tray._load_icon(FakeUser32()), 654)
        self.assertFalse(tray._owns_icon)


if __name__ == "__main__":
    unittest.main()
