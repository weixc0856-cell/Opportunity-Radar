"""N5-only entry point; see tools/run_n4_n5.py. Requires stored N4 results."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.run_n4_n5 import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main(['--nodes', 'n5'] + sys.argv[1:]))
