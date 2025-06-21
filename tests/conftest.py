import sys
from pathlib import Path

# Add the project root to sys.path so modules can be imported
# This assumes conftest.py is in 'tests/' and the modules are in the parent directory.
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
