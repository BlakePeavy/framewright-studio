"""Compatibility entry point for the packaged JSON batch runner."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from framewright.batch import main  # noqa: E402

if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    code = main(arguments)
    if code:
        raise SystemExit(code)
