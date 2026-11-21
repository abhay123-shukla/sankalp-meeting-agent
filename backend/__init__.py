"""
Sankalp (ExecPulse) - Meeting-to-Execution Agent Backend Package
"""
import sys
from pathlib import Path

# Ensure backend directory is in sys.path when imported as a package
_backend_dir = str(Path(__file__).resolve().parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
