from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

WORKSPACE = Path(__file__).resolve().parents[1]

if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))


def main() -> int:
    load_dotenv(WORKSPACE / ".env")

    import run

    dependencies = run._build_strategy_dependencies("retail_flow_swing")
    target_trade_date = run._strategy_runtime.resolve_flow_cache_trade_date(
        dependencies,
        today_trade_date_fn=run._today_trade_date,
    )
    run._prime_institutional_flow_cache(dependencies)

    cache = dependencies["institutional_flow_cache"]
    rows = cache.rows_for_date(target_trade_date)
    summary = {
        "trade_date": target_trade_date,
        "row_count": len(rows),
        "sample_symbols": [row.symbol for row in rows[:5]],
        "cache_write": bool(rows),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
