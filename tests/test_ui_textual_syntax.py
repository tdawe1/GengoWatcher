"""Syntax-level regression tests for the textual UI module."""

from pathlib import Path
import py_compile


def test_ui_textual_module_compiles():
    module_path = Path(__file__).resolve().parents[1] / "src/gengowatcher/ui_textual.py"
    py_compile.compile(str(module_path), doraise=True)
