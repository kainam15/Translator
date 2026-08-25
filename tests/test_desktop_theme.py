import tkinter as tk
import unittest
from tkinter import ttk

from translator_lite.desktop import theme


class TypeScaleTests(unittest.TestCase):
    def test_every_role_uses_the_shared_family(self) -> None:
        for role, spec in theme.FONTS.items():
            self.assertEqual(spec[0], theme.FONT_FAMILY, role)
            self.assertIsInstance(spec[1], int, role)

    def test_reading_size_outranks_interface_chrome(self) -> None:
        self.assertGreater(theme.FONTS["content"][1], theme.FONTS["body"][1])
        self.assertGreater(theme.FONTS["body"][1], theme.FONTS["caption"][1])

    def test_source_and_result_share_one_reading_size(self) -> None:
        self.assertEqual(theme.FONTS["content"], theme.FONTS["result"])


class ColorTokenTests(unittest.TestCase):
    def test_every_token_is_an_uppercase_hex_triplet(self) -> None:
        for name, value in theme.COLORS.items():
            self.assertRegex(value, r"^#[0-9A-F]{6}$", name)

    def test_button_kinds_only_reference_known_tokens(self) -> None:
        known = set(theme.COLORS.values())
        for kind, palette in theme.BUTTON_KINDS.items():
            for slot, value in palette.items():
                self.assertIn(value, known, f"{kind}.{slot}")


class ScrollbarVisibilityTests(unittest.TestCase):
    def test_hidden_when_all_content_fits(self) -> None:
        self.assertFalse(theme.should_show_scrollbar(0.0, 1.0))

    def test_shown_when_content_overflows_below(self) -> None:
        self.assertTrue(theme.should_show_scrollbar(0.0, 0.4))

    def test_shown_when_scrolled_to_the_very_bottom(self) -> None:
        # last == 1.0 alone must not hide the bar; content above is still cut off.
        self.assertTrue(theme.should_show_scrollbar(0.6, 1.0))

    def test_tolerates_tk_rounding_slightly_past_the_edges(self) -> None:
        self.assertFalse(theme.should_show_scrollbar(-0.0001, 1.0001))


class MarqueeTests(unittest.TestCase):
    def test_offset_advances_by_one_step(self) -> None:
        self.assertAlmostEqual(theme.advance_marquee(0.10, step=0.02), 0.12)

    def test_offset_wraps_off_the_left_edge_after_leaving_the_right(self) -> None:
        self.assertAlmostEqual(
            theme.advance_marquee(0.99, step=0.02, span=0.3), -0.3
        )

    def test_offset_never_reaches_the_right_edge(self) -> None:
        offset = -theme.MARQUEE_SPAN
        for _ in range(500):
            offset = theme.advance_marquee(offset)
            self.assertLess(offset, 1.0)

    def test_a_full_loop_returns_to_the_starting_edge(self) -> None:
        offset = -theme.MARQUEE_SPAN
        seen_positive = False
        for _ in range(500):
            offset = theme.advance_marquee(offset)
            if offset > 0.5:
                seen_positive = True
            if seen_positive and offset == -theme.MARQUEE_SPAN:
                return
        self.fail("marquee never completed a loop")


class FlatButtonStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def _button(self, kind: str = "primary") -> tk.Button:
        button = theme.flat_button(self.root, "翻译", lambda: None, kind=kind)
        button.pack()
        # Full update, not update_idletasks: Tk discards <Enter>/<Leave> sent to
        # a widget that is not yet viewable, and idle tasks alone do not map it.
        self.root.update()
        return button

    def test_resting_hover_and_press_are_three_distinct_colors(self) -> None:
        button = self._button()
        resting = button.cget("bg")

        button.event_generate("<Enter>")
        hover = button.cget("bg")
        button.event_generate("<ButtonPress-1>")
        pressed = button.cget("bg")

        self.assertEqual(len({resting, hover, pressed}), 3)

    def test_releasing_over_the_button_returns_to_hover(self) -> None:
        button = self._button()
        resting = button.cget("bg")
        button.event_generate("<Enter>")
        hover = button.cget("bg")
        self.assertNotEqual(hover, resting)

        button.event_generate("<ButtonPress-1>")
        button.event_generate("<ButtonRelease-1>")

        self.assertEqual(button.cget("bg"), hover)

    def test_leaving_while_still_pressed_returns_to_resting(self) -> None:
        button = self._button()
        resting = button.cget("bg")

        button.event_generate("<Enter>")
        button.event_generate("<ButtonPress-1>")
        self.assertNotEqual(button.cget("bg"), resting)
        button.event_generate("<Leave>")

        self.assertEqual(button.cget("bg"), resting)

    def test_active_background_tracks_the_current_color(self) -> None:
        # Tk paints activebackground on hover by itself; keeping the two in sync
        # stops it from overriding the state machine.
        button = self._button()
        resting = button.cget("bg")

        button.event_generate("<Enter>")

        self.assertNotEqual(button.cget("bg"), resting)
        self.assertEqual(button.cget("activebackground"), button.cget("bg"))

    def test_resting_background_can_be_overridden_for_ghost_buttons(self) -> None:
        button = theme.flat_button(
            self.root,
            "设置",
            lambda: None,
            kind="ghost",
            bg=theme.COLORS["sunken"],
        )

        self.assertEqual(button.cget("bg"), theme.COLORS["sunken"])

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(KeyError):
            theme.flat_button(self.root, "x", lambda: None, kind="fancy")


class RestyleButtonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.addCleanup(self.root.destroy)

    def _button(self) -> tk.Button:
        button = theme.flat_button(
            self.root, "", lambda: None, kind="ghost", bg=theme.COLORS["raised"]
        )
        button.pack()
        self.root.update()
        return button

    def test_restyling_replaces_the_resting_color(self) -> None:
        button = self._button()

        theme.restyle_button(button, "accent")

        self.assertEqual(button.cget("bg"), theme.BUTTON_KINDS["accent"]["rest"])
        self.assertEqual(button.cget("fg"), theme.BUTTON_KINDS["accent"]["fg"])

    def test_hover_after_restyling_uses_the_new_palette(self) -> None:
        button = self._button()
        theme.restyle_button(button, "accent")

        button.event_generate("<Enter>")

        self.assertEqual(button.cget("bg"), theme.BUTTON_KINDS["accent"]["hover"])

    def test_leaving_after_restyling_returns_to_the_new_resting_color(self) -> None:
        button = self._button()
        theme.restyle_button(button, "accent")

        button.event_generate("<Enter>")
        button.event_generate("<Leave>")

        self.assertEqual(button.cget("bg"), theme.BUTTON_KINDS["accent"]["rest"])

    def test_stale_bindings_do_not_survive_a_restyle(self) -> None:
        # The bug this guards: the first state machine keeps repainting with the
        # palette it captured, so hover snaps back to the old resting colour.
        button = self._button()
        original_rest = button.cget("bg")

        theme.restyle_button(button, "accent")
        button.event_generate("<Enter>")
        button.event_generate("<Leave>")

        self.assertNotEqual(button.cget("bg"), original_rest)


class ScrollingTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tk.Tk()
        self.root.attributes("-alpha", 0.0)
        self.root.geometry("320x140+120+120")
        self.addCleanup(self.root.destroy)

    def _area(self) -> theme.ScrollingText:
        area = theme.scrolling_text(self.root, font_role="result", height=4)
        area.container.pack(fill="both", expand=True)
        self.root.update()
        return area

    def _overflow(self) -> str:
        return "\n".join(f"第 {index} 行译文" for index in range(80))

    def test_scrollbar_stays_hidden_while_content_fits(self) -> None:
        area = self._area()

        area.text.insert("1.0", "你好，世界")
        self.root.update()

        self.assertFalse(area.scrollbar.winfo_ismapped())

    def test_scrollbar_appears_once_content_overflows(self) -> None:
        area = self._area()

        area.text.insert("1.0", self._overflow())
        self.root.update()

        self.assertTrue(area.scrollbar.winfo_ismapped())

    def test_scrollbar_stays_visible_after_scrolling_to_the_bottom(self) -> None:
        area = self._area()
        area.text.insert("1.0", self._overflow())
        self.root.update()

        area.text.yview_moveto(1.0)
        self.root.update()

        self.assertTrue(area.scrollbar.winfo_ismapped())

    def test_no_focus_ring_unless_asked_for(self) -> None:
        area = theme.scrolling_text(self.root)

        self.assertEqual(int(area.text.cget("highlightthickness")), 0)

    def test_focus_ring_hides_against_its_own_surface_until_focused(self) -> None:
        area = theme.scrolling_text(
            self.root, focus_ring=True, background=theme.COLORS["sunken"]
        )

        self.assertEqual(int(area.text.cget("highlightthickness")), 1)
        self.assertEqual(area.text.cget("highlightbackground"), theme.COLORS["sunken"])
        self.assertEqual(area.text.cget("highlightcolor"), theme.COLORS["accent"])

    def test_scrollbar_hides_again_when_the_text_is_cleared(self) -> None:
        area = self._area()
        area.text.insert("1.0", self._overflow())
        self.root.update()

        area.text.delete("1.0", "end")
        self.root.update()

        self.assertFalse(area.scrollbar.winfo_ismapped())


class TtkStyleTests(unittest.TestCase):
    def test_configuring_styles_registers_the_scrollbar_and_combobox(self) -> None:
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        try:
            theme.configure_ttk_styles(root)
            style = ttk.Style(root)

            self.assertEqual(
                style.lookup(theme.SCROLLBAR_STYLE, "troughcolor"),
                theme.COLORS["sunken"],
            )
            self.assertEqual(
                style.lookup(theme.COMBOBOX_STYLE, "foreground"),
                theme.COLORS["text"],
            )
        finally:
            root.destroy()


class SeparatorTests(unittest.TestCase):
    def test_separator_is_a_hairline_in_the_line_token(self) -> None:
        root = tk.Tk()
        root.attributes("-alpha", 0.0)
        try:
            line = theme.separator(root)

            self.assertEqual(int(line.cget("height")), 1)
            self.assertEqual(line.cget("bg"), theme.COLORS["line"])
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
