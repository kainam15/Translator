import unittest

from translator_lite.desktop.placement import (
    BASELINE_TK_SCALING,
    clamp_window_position,
    resize_window_geometry,
    scale_for_dpi,
)


class ScaleForDpiTests(unittest.TestCase):
    def test_baseline_scaling_leaves_design_pixels_untouched(self) -> None:
        self.assertEqual(scale_for_dpi(560, BASELINE_TK_SCALING), 560)

    def test_doubled_scaling_doubles_the_pixel_budget(self) -> None:
        # Fonts are points and Tk multiplies them by the scaling factor, so a
        # window measured in raw pixels has to grow by the same ratio.
        self.assertEqual(scale_for_dpi(560, BASELINE_TK_SCALING * 2), 1120)

    def test_high_dpi_display_scaling(self) -> None:
        # 2.664 is what Tk reports on a 2560x1600 panel at 200% Windows scaling.
        self.assertEqual(scale_for_dpi(540, 2.664), 1079)

    def test_result_is_never_smaller_than_one_pixel(self) -> None:
        self.assertEqual(scale_for_dpi(1, 0.0001), 1)

    def test_nonsense_scaling_falls_back_to_the_design_value(self) -> None:
        self.assertEqual(scale_for_dpi(560, 0.0), 560)
        self.assertEqual(scale_for_dpi(560, -3.0), 560)


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

    def test_southeast_resize_changes_width_and_height(self) -> None:
        self.assertEqual(
            resize_window_geometry(
                "se",
                (100, 100),
                (180, 160),
                (20, 30, 720, 660),
                (440, 500),
            ),
            (20, 30, 800, 720),
        )

    def test_northwest_resize_keeps_southeast_corner_anchored(self) -> None:
        self.assertEqual(
            resize_window_geometry(
                "nw",
                (100, 100),
                (50, 60),
                (20, 30, 720, 660),
                (440, 500),
            ),
            (-30, -10, 770, 700),
        )

    def test_west_resize_stops_at_minimum_width(self) -> None:
        self.assertEqual(
            resize_window_geometry(
                "w",
                (100, 100),
                (400, 100),
                (100, 30, 500, 660),
                (440, 500),
            ),
            (160, 30, 440, 660),
        )

    def test_unknown_resize_edge_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resize_window_geometry(
                "center",
                (0, 0),
                (0, 0),
                (0, 0, 720, 660),
                (440, 500),
            )


if __name__ == "__main__":
    unittest.main()
