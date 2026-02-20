"""Tests for chart rendering functionality."""

import pytest
from gengowatcher.ui_textual import BAR_CHARS, _render_chart


def test_bar_chars_constant_defined():
    """BAR_CHARS should be defined with fractional block characters."""
    assert BAR_CHARS is not None
    assert len(BAR_CHARS) == 9  # space + 8 fractional blocks
    assert BAR_CHARS[0] == " "  # Empty
    assert BAR_CHARS[-1] == "█"  # Full block
    # Check that it contains fractional blocks
    assert "▁" in BAR_CHARS
    assert "▂" in BAR_CHARS
    assert "▃" in BAR_CHARS
    assert "▄" in BAR_CHARS
    assert "▅" in BAR_CHARS
    assert "▆" in BAR_CHARS
    assert "▇" in BAR_CHARS


def test_render_chart_empty_values():
    """_render_chart should handle empty values gracefully."""
    result = _render_chart([], width=10, height=5)
    assert result == ""


def test_render_chart_zero_width():
    """_render_chart should handle zero width."""
    result = _render_chart([1, 2, 3], width=0, height=5)
    assert result == ""


def test_render_chart_zero_height():
    """_render_chart should handle zero height."""
    result = _render_chart([1, 2, 3], width=10, height=0)
    assert result == ""


def test_render_chart_returns_string():
    """_render_chart should return a string."""
    result = _render_chart([1, 2, 3, 4, 5], width=5, height=3)
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_chart_correct_dimensions():
    """_render_chart should return correct dimensions."""
    width = 10
    height = 5
    result = _render_chart([1, 2, 3, 4, 5], width=width, height=height)
    lines = result.split("\n")
    assert len(lines) == height
    for line in lines:
        assert len(line) == width


def test_render_chart_uses_fractional_blocks():
    """_render_chart should use fractional block characters from BAR_CHARS."""
    # Create values that should produce fractional blocks
    values = [0.5, 1.0, 1.5, 2.0, 2.5]
    result = _render_chart(values, width=5, height=3)
    
    # The result should contain characters from BAR_CHARS
    for char in result:
        if char != "\n":
            assert char in BAR_CHARS, f"Character '{char}' not in BAR_CHARS"


def test_render_chart_ascending_values():
    """_render_chart should show ascending pattern for increasing values."""
    values = [1, 2, 3, 4, 5, 6, 7, 8]
    result = _render_chart(values, width=8, height=4)
    lines = result.split("\n")

    # Check that we have the right number of lines
    assert len(lines) == 4

    # The top line should have more empty spaces on the left (lower values)
    # and more filled blocks on the right (higher values)
    top_line = lines[0]
    bottom_line = lines[-1]

    # Bottom line should have more filled content than top line
    top_filled = sum(1 for c in top_line if c != " ")
    bottom_filled = sum(1 for c in bottom_line if c != " ")
    assert bottom_filled > 0
    assert bottom_filled >= top_filled


def test_render_chart_all_zeros():
    """_render_chart should handle all zero values."""
    values = [0, 0, 0, 0, 0]
    result = _render_chart(values, width=5, height=3)
    lines = result.split("\n")

    
    # All lines should be mostly empty (spaces or minimal blocks)
    assert len(lines) == 3
    for line in lines:
        assert len(line) == 5


def test_render_chart_single_value():
    """_render_chart should handle a single value."""
    values = [5]
    result = _render_chart(values, width=5, height=3)
    lines = result.split("\n")

    
    assert len(lines) == 3
    # First column should show the value, rest should be empty
    assert lines[-1][0] in BAR_CHARS  # Bottom line, first column should have a block


def test_render_chart_normalization():
    """_render_chart should normalize values to fit the height."""
    # Very large values should still fit in the chart
    values = [100, 200, 300, 400, 500]
    result = _render_chart(values, width=5, height=3)
    lines = result.split("\n")

    assert len(lines) == 3
    for line in lines:
        assert len(line) == 5

    # The last value (500) should reach near the top
    # Check that the rightmost column has blocks in multiple rows
    rightmost_chars = [lines[i][-1] for i in range(len(lines))]
    filled_count = sum(1 for c in rightmost_chars if c != " ")
    assert filled_count >= 2  # Should have blocks in at least 2 rows


def test_render_chart_downsampling():
    """_render_chart should downsample when there are more values than width."""
    # Create 20 values but only 10 width
    values = list(range(1, 21))
    result = _render_chart(values, width=10, height=3)
    lines = result.split("\n")

    assert len(lines) == 3
    for line in lines:
        assert len(line) == 10


def test_render_chart_padding():
    """_render_chart should pad when there are fewer values than width."""
    # Create 3 values but 10 width
    values = [5, 10, 15]
    result = _render_chart(values, width=10, height=3)
    lines = result.split("\n")

    assert len(lines) == 3
    for line in lines:
        assert len(line) == 10

    # Right side should be mostly empty (padded with zeros)
    for line in lines:
        # Last few characters should be empty (spaces)
        assert line[-1] == " " or line[-2] == " "
