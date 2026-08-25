"""Visual tokens and the widget primitives built from them.

Every colour and font used by the desktop UI is named here so a change lands in
one place. Widgets are plain Tk: ``ttk`` styling cannot express the hover and
press states this interface needs.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, NamedTuple


FONT_FAMILY = "Microsoft YaHei UI"
ICON_FAMILY = "Segoe MDL2 Assets"

#: Five reading roles. ``content`` and ``result`` are deliberately equal: the
#: translation is the product, so it never renders smaller than its input.
FONTS: dict[str, tuple[Any, ...]] = {
    "heading": (FONT_FAMILY, 14, "bold"),
    "title": (FONT_FAMILY, 10, "bold"),
    "content": (FONT_FAMILY, 13),
    "result": (FONT_FAMILY, 13),
    "label": (FONT_FAMILY, 9, "bold"),
    "body": (FONT_FAMILY, 9),
    "caption": (FONT_FAMILY, 8),
}

ICON_FONT = (ICON_FAMILY, 11)
#: Latin-only face for rendering key combinations, where YaHei looks uneven.
KEYCAP_FONT = ("Segoe UI Semibold", 13)

COLORS: dict[str, str] = {
    # Neutral ramp, lightest to darkest.
    "surface": "#FFFFFF",
    "raised": "#FAFAFA",
    "sunken": "#F4F4F5",
    "line": "#E4E4E7",
    "line_strong": "#D4D4D8",
    "faint": "#A1A1AA",
    "muted": "#71717A",
    "text": "#18181B",
    # Accent.
    "on_accent": "#FFFFFF",
    "accent": "#2563EB",
    "accent_hover": "#1D4ED8",
    "accent_press": "#1E40AF",
    "accent_soft": "#EFF4FF",
    "accent_soft_hover": "#DDE8FF",
    "accent_soft_press": "#C9DAFF",
    # Semantic.
    "danger": "#B42318",
    "warning": "#B54708",
    "success": "#15803D",
    "success_soft": "#DCFCE7",
    "success_soft_hover": "#BBF7D0",
    "success_soft_press": "#A7F3C4",
    # Neutral interaction.
    "hover": "#EDEDF0",
    "press": "#E2E2E7",
    "selection": "#C7D9FF",
}

BUTTON_KINDS: dict[str, dict[str, str]] = {
    "primary": {
        "fg": COLORS["on_accent"],
        "rest": COLORS["accent"],
        "hover": COLORS["accent_hover"],
        "press": COLORS["accent_press"],
    },
    "accent": {
        "fg": COLORS["accent"],
        "rest": COLORS["accent_soft"],
        "hover": COLORS["accent_soft_hover"],
        "press": COLORS["accent_soft_press"],
    },
    "ghost": {
        "fg": COLORS["muted"],
        "rest": COLORS["raised"],
        "hover": COLORS["hover"],
        "press": COLORS["press"],
    },
    "quiet": {
        "fg": COLORS["muted"],
        "rest": COLORS["sunken"],
        "hover": COLORS["hover"],
        "press": COLORS["press"],
    },
    # Transient confirmation state, e.g. a copy button right after it fired.
    "success": {
        "fg": COLORS["success"],
        "rest": COLORS["success_soft"],
        "hover": COLORS["success_soft_hover"],
        "press": COLORS["success_soft_press"],
    },
}


def should_show_scrollbar(first: float, last: float, tolerance: float = 1e-3) -> bool:
    """Decide whether a scrollable view still hides content.

    ``first``/``last`` are the fractions reported by ``Text.yview()``. Testing
    ``last >= 1.0`` alone would wrongly hide the bar once the user scrolls to
    the bottom, so both edges have to be visible before it goes away.
    """
    return not (first <= tolerance and last >= 1.0 - tolerance)


#: Width of the indeterminate progress thumb, as a fraction of the bar.
MARQUEE_SPAN = 0.28


def advance_marquee(
    offset: float, step: float = 0.022, span: float = MARQUEE_SPAN
) -> float:
    """Next left edge of a looping indeterminate bar.

    ``offset`` is a ``relx`` fraction that starts one thumb-width off the left
    edge and restarts there once the thumb has cleared the right edge.
    """
    advanced = offset + step
    return -span if advanced >= 1.0 else advanced


def _bind_button_states(
    button: tk.Button, resting: str, hover: str, press: str
) -> None:
    """Give a flat button three visual states instead of Tk's two.

    Tk collapses hover and press into ``activebackground``; the two are kept in
    sync with ``bg`` here so Tk's own active painting cannot override us.
    """
    state = {"inside": False, "pressed": False}

    def paint() -> None:
        if state["pressed"] and state["inside"]:
            current = press
        elif state["inside"]:
            current = hover
        else:
            current = resting
        button.configure(bg=current, activebackground=current)

    def on_enter(_event: tk.Event[tk.Misc]) -> None:
        state["inside"] = True
        paint()

    def on_leave(_event: tk.Event[tk.Misc]) -> None:
        state["inside"] = False
        state["pressed"] = False
        paint()

    def on_press(_event: tk.Event[tk.Misc]) -> None:
        state["pressed"] = True
        paint()

    def on_release(_event: tk.Event[tk.Misc]) -> None:
        state["pressed"] = False
        paint()

    button.bind("<Enter>", on_enter, add="+")
    button.bind("<Leave>", on_leave, add="+")
    button.bind("<ButtonPress-1>", on_press, add="+")
    button.bind("<ButtonRelease-1>", on_release, add="+")


def flat_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], Any],
    *,
    kind: str = "ghost",
    bg: str | None = None,
    font_role: str = "body",
    padx: int = 9,
    pady: int = 5,
    width: int = 0,
) -> tk.Button:
    """Build a borderless button that rests, hovers, and presses distinctly.

    ``bg`` overrides only the resting colour, for ghost buttons that sit on a
    surface other than the window background.
    """
    palette = BUTTON_KINDS[kind]
    resting = palette["rest"] if bg is None else bg
    button = tk.Button(
        parent,
        text=text,
        command=command,
        fg=palette["fg"],
        bg=resting,
        activeforeground=palette["fg"],
        activebackground=resting,
        disabledforeground=COLORS["faint"],
        bd=0,
        highlightthickness=0,
        relief="flat",
        cursor="hand2",
        padx=padx,
        pady=pady,
        width=width,
        font=FONTS[font_role],
    )
    _bind_button_states(button, resting, palette["hover"], palette["press"])
    return button


_STATE_SEQUENCES = ("<Enter>", "<Leave>", "<ButtonPress-1>", "<ButtonRelease-1>")


def restyle_button(button: tk.Button, kind: str, *, bg: str | None = None) -> None:
    """Move an existing flat button onto another palette.

    The old state machine has to go with it: its closure captured the previous
    resting colour and would repaint over the new one on the next hover. This
    clears every binding for the four state sequences, so do not use it on a
    button that carries extra handlers for them.
    """
    palette = BUTTON_KINDS[kind]
    resting = palette["rest"] if bg is None else bg
    for sequence in _STATE_SEQUENCES:
        button.unbind(sequence)
    button.configure(
        fg=palette["fg"],
        activeforeground=palette["fg"],
        bg=resting,
        activebackground=resting,
    )
    _bind_button_states(button, resting, palette["hover"], palette["press"])


def separator(parent: tk.Misc) -> tk.Frame:
    """A one-pixel rule; the only structural divider this UI uses."""
    return tk.Frame(
        parent,
        height=1,
        bg=COLORS["line"],
        bd=0,
        highlightthickness=0,
    )


SCROLLBAR_STYLE = "Thin.Vertical.TScrollbar"
COMBOBOX_STYLE = "Language.TCombobox"


def configure_ttk_styles(root: tk.Misc) -> ttk.Style:
    """Restyle the two ttk widgets this UI uses so they match the plain ones."""
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # Drop clam's stepper arrows entirely; what is left is trough plus thumb.
    style.layout(
        SCROLLBAR_STYLE,
        [
            (
                "Vertical.Scrollbar.trough",
                {
                    "sticky": "ns",
                    "children": [
                        (
                            "Vertical.Scrollbar.thumb",
                            {"expand": "1", "sticky": "nswe"},
                        )
                    ],
                },
            )
        ],
    )
    style.configure(
        SCROLLBAR_STYLE,
        troughcolor=COLORS["sunken"],
        background=COLORS["line_strong"],
        bordercolor=COLORS["sunken"],
        lightcolor=COLORS["line_strong"],
        darkcolor=COLORS["line_strong"],
        relief="flat",
        width=8,
    )
    style.map(SCROLLBAR_STYLE, background=[("active", COLORS["faint"])])

    style.configure(
        COMBOBOX_STYLE,
        fieldbackground=COLORS["surface"],
        background=COLORS["surface"],
        foreground=COLORS["text"],
        bordercolor=COLORS["line"],
        lightcolor=COLORS["line"],
        darkcolor=COLORS["line"],
        arrowcolor=COLORS["muted"],
        padding=(8, 4),
        font=FONTS["body"],
    )
    style.map(
        COMBOBOX_STYLE,
        fieldbackground=[("readonly", COLORS["surface"])],
        selectbackground=[("readonly", COLORS["surface"])],
        selectforeground=[("readonly", COLORS["text"])],
        bordercolor=[("focus", COLORS["accent"])],
        arrowcolor=[("active", COLORS["accent"])],
    )
    return style


class ScrollingText(NamedTuple):
    container: tk.Frame
    text: tk.Text
    scrollbar: ttk.Scrollbar


def scrolling_text(
    parent: tk.Misc,
    *,
    font_role: str = "content",
    height: int = 4,
    background: str = COLORS["surface"],
    padx: int = 14,
    pady: int = 8,
    focus_ring: bool = False,
    **text_options: Any,
) -> ScrollingText:
    """A text area whose scrollbar only takes up room when it has to.

    With ``focus_ring`` the widget carries a one-pixel highlight that matches
    its own background until Tk paints it accent-coloured on focus.
    """
    container = tk.Frame(parent, bg=background, bd=0, highlightthickness=0)
    container.columnconfigure(0, weight=1)
    container.rowconfigure(0, weight=1)

    scrollbar = ttk.Scrollbar(container, orient="vertical", style=SCROLLBAR_STYLE)
    text = tk.Text(
        container,
        height=height,
        wrap="word",
        bd=0,
        highlightthickness=1 if focus_ring else 0,
        highlightbackground=background,
        highlightcolor=COLORS["accent"],
        bg=background,
        fg=COLORS["text"],
        insertbackground=COLORS["text"],
        selectbackground=COLORS["selection"],
        selectforeground=COLORS["text"],
        padx=padx,
        pady=pady,
        font=FONTS[font_role],
        **text_options,
    )
    text.grid(row=0, column=0, sticky="nsew")
    scrollbar.grid(row=0, column=1, sticky="ns")
    scrollbar.grid_remove()

    shown = {"visible": False}

    def on_view_change(first: str, last: str) -> None:
        scrollbar.set(first, last)
        visible = should_show_scrollbar(float(first), float(last))
        # Only touch geometry on a real transition: re-gridding from inside a
        # yscrollcommand would trigger another view change.
        if visible == shown["visible"]:
            return
        shown["visible"] = visible
        if visible:
            scrollbar.grid()
        else:
            scrollbar.grid_remove()

    text.configure(yscrollcommand=on_view_change)
    scrollbar.configure(command=text.yview)
    return ScrollingText(container, text, scrollbar)
