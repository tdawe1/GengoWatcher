# In tests/conftest.py
import sys
from pathlib import Path

# Add the project's 'src' directory to the Python path
# This allows tests to import the 'gengowatcher' package
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))
