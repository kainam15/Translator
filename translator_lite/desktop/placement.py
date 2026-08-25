"""Window placement rules shared by desktop views."""


RESIZE_EDGES = frozenset(("n", "ne", "e", "se", "s", "sw", "w", "nw"))

#: ``tk scaling`` at 96 DPI, the density this UI's pixel constants are drawn for.
BASELINE_TK_SCALING = 96.0 / 72.0


def scale_for_dpi(value: int, scaling: float) -> int:
    """Convert a 96-DPI design pixel into a physical pixel for this display.

    Tk sizes fonts in points and multiplies them by ``tk scaling``, but a window
    geometry is raw pixels. Without this the two drift apart on a high-DPI
    screen: the text grows while the window it lives in does not.
    """
    if scaling <= 0:
        return value
    return max(1, round(value * scaling / BASELINE_TK_SCALING))


def clamp_window_position(
    x: int,
    y: int,
    width: int,
    height: int,
    work_area: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Keep the complete window inside the selected monitor's work area."""
    left, top, right, bottom = work_area
    max_x = max(left, right - width)
    max_y = max(top, bottom - height)
    return max(left, min(x, max_x)), max(top, min(y, max_y))


def resize_window_geometry(
    edge: str,
    start_pointer: tuple[int, int],
    current_pointer: tuple[int, int],
    initial_geometry: tuple[int, int, int, int],
    minimum_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Resize one or two window edges while keeping opposite edges anchored."""
    if edge not in RESIZE_EDGES:
        raise ValueError(f"unsupported resize edge: {edge}")

    start_x, start_y = start_pointer
    current_x, current_y = current_pointer
    initial_x, initial_y, initial_width, initial_height = initial_geometry
    minimum_width, minimum_height = minimum_size
    delta_x = current_x - start_x
    delta_y = current_y - start_y

    x = initial_x
    y = initial_y
    width = initial_width
    height = initial_height

    if "w" in edge:
        width = initial_width - delta_x
        x = initial_x + delta_x
    elif "e" in edge:
        width = initial_width + delta_x

    if "n" in edge:
        height = initial_height - delta_y
        y = initial_y + delta_y
    elif "s" in edge:
        height = initial_height + delta_y

    if width < minimum_width:
        width = minimum_width
        if "w" in edge:
            x = initial_x + initial_width - minimum_width

    if height < minimum_height:
        height = minimum_height
        if "n" in edge:
            y = initial_y + initial_height - minimum_height

    return x, y, width, height
