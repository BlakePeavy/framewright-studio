"""Static Blender worker entry point supporting source and installed package names."""

import importlib
import sys
from pathlib import Path

package_path = Path(__file__).resolve().parent
sys.path.insert(0, str(package_path.parent))
runner = importlib.import_module(package_path.name + ".batch")
arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
code = runner.main(arguments)
if code:
    raise SystemExit(code)
