from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formal_simulation import run_formal_simulation_preflight


def main() -> int:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.local", override=False)
    result = run_formal_simulation_preflight()
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
