"""Window placement rules shared by desktop views."""


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
