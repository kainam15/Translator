import gc
import tkinter as tk
import unittest
import weakref
from unittest.mock import Mock, call, patch

from translator_lite.desktop.math_view import MathTextView


class MathTextViewTests(unittest.TestCase):
    def _widget(self) -> Mock:
        widget = Mock()
        widget.cget.return_value = "normal"
        widget.image_create.side_effect = ["image-1", "image-2", "image-3"]
        return widget

    @patch("translator_lite.desktop.math_view.tk.PhotoImage")
    def test_inserted_images_round_trip_through_dump_with_edited_prose(self, photo) -> None:
        widget = self._widget()
        view = MathTextView(widget)
        formula = r"\(x^2\)"
        view.set_content("Before " + formula + " after", {formula: "base64-png"})
        widget.dump.return_value = [
            ("text", "Edited before ", "1.0"),
            ("image", "image-1", "1.14"),
            ("text", " after editing", "1.15"),
        ]

        self.assertEqual(view.get_content(), "Edited before " + formula + " after editing")
        widget.dump.assert_called_once_with("1.0", "end-1c", text=True, image=True)
        photo.assert_called_once_with(master=widget, data="base64-png", format="png")

    @patch("translator_lite.desktop.math_view.tk.PhotoImage")
    def test_duplicate_formulas_have_separate_text_image_names(self, _photo) -> None:
        widget = self._widget()
        view = MathTextView(widget)
        formula = r"\[x^2\]"
        view.set_content(formula + " and " + formula, {formula: "base64-png"})
        widget.dump.return_value = [
            ("image", "image-1", "1.0"),
            ("text", " plus ", "1.1"),
            ("image", "image-2", "1.7"),
        ]

        self.assertEqual(view.get_content(), formula + " plus " + formula)

    @patch("translator_lite.desktop.math_view.tk.PhotoImage", side_effect=tk.TclError("bad png"))
    def test_missing_and_invalid_renderings_keep_raw_latex(self, _photo) -> None:
        widget = self._widget()
        view = MathTextView(widget)
        first, second = r"\(x\)", r"\[\unknown{y}\]"

        view.set_content(first + " and " + second, {first: "broken"})

        self.assertEqual(widget.insert.call_args_list, [
            call("end", first), call("end", " and "), call("end", second)
        ])
        widget.image_create.assert_not_called()

    @patch("translator_lite.desktop.math_view.tk.PhotoImage")
    def test_disabled_result_widget_is_restored_after_replacement(self, _photo) -> None:
        widget = self._widget()
        widget.cget.return_value = "disabled"
        view = MathTextView(widget)

        view.set_content(r"\(x\)", {r"\(x\)": "png"})

        self.assertEqual(widget.configure.call_args_list, [call(state="normal"), call(state="disabled")])
        widget.edit_reset.assert_called_once_with()

    @patch("translator_lite.desktop.math_view.tk.PhotoImage")
    def test_selected_formula_copies_latex_with_current_selected_text(self, _photo) -> None:
        widget = self._widget()
        view = MathTextView(widget)
        formula = r"\(x^2\)"
        view.set_content("Use " + formula, {formula: "png"})
        widget.tag_ranges.return_value = ("1.4", "1.5")
        widget.dump.return_value = [("image", "image-1", "1.4")]

        self.assertEqual(view.copy_selection(), "break")

        widget.dump.assert_called_once_with("1.4", "1.5", text=True, image=True)
        widget.clipboard_clear.assert_called_once_with()
        widget.clipboard_append.assert_called_once_with(formula)

    def test_copy_without_selection_preserves_clipboard(self) -> None:
        widget = self._widget()
        widget.tag_ranges.return_value = ()

        self.assertIsNone(MathTextView(widget).copy_selection())

        widget.clipboard_clear.assert_not_called()

    @patch("translator_lite.desktop.math_view.tk.PhotoImage")
    def test_cut_copies_latex_before_deleting_formula(self, _photo) -> None:
        widget = self._widget()
        view = MathTextView(widget)
        formula = r"\(x^2\)"
        view.set_content(formula, {formula: "png"})
        widget.reset_mock()
        widget.tag_ranges.return_value = ("1.0", "1.1")
        widget.dump.return_value = [("image", "image-1", "1.0")]

        self.assertEqual(view.cut_selection(), "break")

        widget.clipboard_append.assert_called_once_with(formula)
        widget.delete.assert_called_once_with("1.0", "1.1")

    def test_cut_cannot_modify_read_only_result(self) -> None:
        widget = self._widget()
        widget.cget.return_value = "disabled"

        self.assertEqual(MathTextView(widget).cut_selection(), "break")

        widget.delete.assert_not_called()
        widget.clipboard_clear.assert_not_called()

    def test_image_reference_survives_factory_and_widget_call_history(self) -> None:
        class ImageReference:
            pass

        created = []

        def photo_factory(**_kwargs):
            image = ImageReference()
            created.append(weakref.ref(image))
            return image

        widget = self._widget()
        view = MathTextView(widget)
        with patch("translator_lite.desktop.math_view.tk.PhotoImage", photo_factory):
            view.set_content(r"\(x\)", {r"\(x\)": "png"})
        widget.reset_mock()
        gc.collect()

        self.assertIsNotNone(created[0]())

        view.set_content("Replacement text")
        gc.collect()
        self.assertIsNone(created[0]())

    @patch("translator_lite.desktop.math_view.tk.PhotoImage")
    def test_deleted_formula_does_not_reappear_from_initial_content(self, _photo) -> None:
        widget = self._widget()
        view = MathTextView(widget)
        view.set_content(r"Use \(x\)", {r"\(x\)": "png"})
        widget.dump.return_value = [("text", "User replaced everything", "1.0")]

        self.assertEqual(view.get_content(), "User replaced everything")


if __name__ == "__main__":
    unittest.main()
