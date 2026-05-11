from __future__ import annotations

from rich.text import Text

try:
    import plotext as plotext
except ImportError:  # pragma: no cover - optional runtime dependency
    plotext = None


# Fractional block characters for bar chart rendering.
# Characters arranged from empty to full: space, then ▁▂▃▄▅▆▇█.
BAR_CHARS = " ▁▂▃▄▅▆▇█"


def render_chart(
    values: list[float],
    width: int = 20,
    height: int = 5,
) -> str:
    """Render a bar chart using fractional block characters."""
    if not values or width <= 0 or height <= 0:
        return ""

    max_val = max(values) if values else 1.0
    if max_val == 0:
        max_val = 1.0

    if len(values) > width:
        step = len(values) / width
        resampled = []
        for i in range(width):
            start_idx = int(i * step)
            end_idx = int((i + 1) * step)
            bucket = values[start_idx:end_idx]
            resampled.append(sum(bucket) / len(bucket) if bucket else 0)
        values = resampled
    elif len(values) < width:
        values = list(values) + [0.0] * (width - len(values))

    max_units = height * 8
    normalized = [(v / max_val) * max_units for v in values]

    lines = []
    for row in range(height - 1, -1, -1):
        line = ""
        for col_val in normalized:
            units_needed_for_row = row * 8
            if col_val > units_needed_for_row + 8:
                line += BAR_CHARS[-1]
            elif col_val > units_needed_for_row:
                fraction = int(col_val - units_needed_for_row)
                line += BAR_CHARS[min(fraction, len(BAR_CHARS) - 1)]
            else:
                line += BAR_CHARS[0]
        lines.append(line)

    return "\n".join(lines)


def aggregate_series(values: list[float], bin_size: int = 2) -> list[float]:
    """Aggregate a series into fixed-size bins."""
    if bin_size <= 1:
        return list(values)
    aggregated: list[float] = []
    for i in range(0, len(values), bin_size):
        aggregated.append(float(sum(values[i : i + bin_size])))
    return aggregated


def render_chart_with_axes(
    values: list[float],
    *,
    width: int = 12,
    height: int = 4,
    x_left: str = "old",
    x_right: str = "new",
) -> str:
    """Render chart with minimal y-axis and x-axis labels."""
    chart = render_chart(values, width=width, height=height)
    if not chart:
        return ""

    lines = chart.splitlines()
    max_val = max(values) if values else 0.0
    if max_val <= 0:
        max_val = 1.0

    y_label_width = max(1, len(str(int(round(max_val)))))
    with_axis: list[str] = []
    for row_idx, line in enumerate(lines):
        approx_value = int(round(max_val * (height - row_idx) / height))
        with_axis.append(f"{approx_value:>{y_label_width}} |{line}")

    with_axis.append(f"{0:>{y_label_width}} +{'─' * width}")
    left_pad = " " * (y_label_width + 2)
    spacing = max(1, width - len(x_left) - len(x_right))
    with_axis.append(f"{left_pad}{x_left}{' ' * spacing}{x_right}")
    return "\n".join(with_axis)


def render_plotext_bar_chart(
    values: list[float],
    *,
    width: int,
    height: int,
    x_left: str,
    x_mid: str,
    x_right: str,
) -> str:
    """Render a bar chart via plotext with true axes/ticks."""
    if plotext is None or not values or width <= 0 or height <= 0:
        return ""

    try:
        x = list(range(1, len(values) + 1))
        mid = max(1, len(values) // 2)
        right = len(values)

        plotext.clear_figure()
        plotext.plotsize(width, height)
        plotext.bar(x, values, fill=True, width=0.8)
        plotext.xticks([1, mid, right], [x_left, x_mid, x_right])
        plotext.ylabel("jobs")
        plotext.xlabel("time")
        plotext.grid(True)

        built = plotext.build()
        plotext.clear_figure()
        return str(Text.from_ansi(built)).rstrip()
    except Exception:
        return ""


_render_chart = render_chart
_aggregate_series = aggregate_series
_render_chart_with_axes = render_chart_with_axes
_render_plotext_bar_chart = render_plotext_bar_chart
