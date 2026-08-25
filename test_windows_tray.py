import unittest

from windows_tray import (
    MENU_EXIT,
    MENU_SETTINGS,
    MENU_SHOW,
    menu_action_for_command,
)


class SystemTrayTests(unittest.TestCase):
    def test_menu_commands_map_to_expected_actions(self) -> None:
        self.assertEqual(menu_action_for_command(MENU_SHOW), "show")
        self.assertEqual(menu_action_for_command(MENU_SETTINGS), "settings")
        self.assertEqual(menu_action_for_command(MENU_EXIT), "exit")
        self.assertIsNone(menu_action_for_command(0))


if __name__ == "__main__":
    unittest.main()
