"""N2-only entry point; see tools/run_n2_n3.py."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.run_n2_n3 import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main(['--nodes', 'n2'] + sys.argv[1:]))
