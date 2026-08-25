import unittest

from translator_lite.desktop.placement import clamp_window_position


class DesktopPlacementTests(unittest.TestCase):
    def test_clamp_keeps_window_inside_positive_work_area(self) -> None:
        self.assertEqual(
            clamp_window_position(1800, -20, 720, 660, (0, 0, 1920, 1040)),
            (1200, 0),
        )

    def test_clamp_supports_negative_monitor_coordinates(self) -> None:
        self.assertEqual(
            clamp_window_position(-2500, 500, 720, 660, (-1920, 0, 0, 1080)),
            (-1920, 420),
        )


if __name__ == "__main__":
    unittest.main()
