"""Tests for chart rendering functionality."""

from gengowatcher.ui_charts import BAR_CHARS, render_chart


def test_bar_chars_constant_defined():
    """BAR_CHARS should be defined with fractional block characters."""
    assert len(BAR_CHARS) == 9
    assert BAR_CHARS[0] == " "
    assert BAR_CHARS[-1] == "█"
    assert "▁▂▃▄▅▆▇" in BAR_CHARS


def test_render_chart_empty_values():
    assert render_chart([], width=10, height=5) == ""


def test_render_chart_zero_width():
    assert render_chart([1, 2, 3], width=0, height=5) == ""


def test_render_chart_zero_height():
    assert render_chart([1, 2, 3], width=10, height=0) == ""


def test_render_chart_returns_string():
    result = render_chart([1, 2, 3, 4, 5], width=5, height=3)
    assert isinstance(result, str)
    assert result


def test_render_chart_correct_dimensions():
    result = render_chart([1, 2, 3, 4, 5], width=10, height=5)
    lines = result.splitlines()
    assert len(lines) == 5
    assert all(len(line) == 10 for line in lines)


def test_render_chart_uses_fractional_blocks():
    result = render_chart([0.5, 1.0, 1.5, 2.0, 2.5], width=5, height=3)
    assert all(char in BAR_CHARS or char == "\n" for char in result)


def test_render_chart_ascending_values():
    result = render_chart([1, 2, 3, 4, 5, 6, 7, 8], width=8, height=4)
    lines = result.splitlines()
    assert len(lines) == 4
    top_filled = sum(char != " " for char in lines[0])
    bottom_filled = sum(char != " " for char in lines[-1])
    assert bottom_filled > 0
    assert bottom_filled >= top_filled


def test_render_chart_all_zeros():
    result = render_chart([0, 0, 0, 0, 0], width=5, height=3)
    lines = result.splitlines()
    assert len(lines) == 3
    assert all(line == " " * 5 for line in lines)


def test_render_chart_single_value():
    result = render_chart([5], width=5, height=3)
    lines = result.splitlines()
    assert len(lines) == 3
    assert lines[-1][0] in BAR_CHARS
    assert all(line[1:] == " " * 4 for line in lines)


def test_render_chart_normalization():
    result = render_chart([100, 200, 300, 400, 500], width=5, height=3)
    lines = result.splitlines()
    assert len(lines) == 3
    assert all(len(line) == 5 for line in lines)
    assert sum(line[-1] != " " for line in lines) >= 2


def test_render_chart_downsampling():
    result = render_chart(list(range(1, 21)), width=10, height=3)
    lines = result.splitlines()
    assert len(lines) == 3
    assert all(len(line) == 10 for line in lines)


def test_render_chart_padding():
    result = render_chart([5, 10, 15], width=10, height=3)
    lines = result.splitlines()
    assert len(lines) == 3
    assert all(len(line) == 10 for line in lines)
    assert all(line[3:] == " " * 7 for line in lines)
