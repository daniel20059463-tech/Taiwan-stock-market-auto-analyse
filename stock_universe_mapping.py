from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any


_SEED_PATTERN = re.compile(
    r'\["(?P<symbol>\d{4})",\s*"(?P<name>(?:\\u[0-9a-fA-F]{4}|\\.|[^"])*)",\s*"[^"]*",\s*[^,]+,\s*[^\]]+\]'
)


def load_dotenv_file(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            import os

            os.environ.setdefault(key, value)


def parse_twstocks_seeds(source: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for match in _SEED_PATTERN.finditer(source):
        symbol = match.group("symbol")
        name = match.group("name").encode("utf-8").decode("unicode_escape").strip()
        if symbol:
            parsed[symbol] = name or symbol
    return parsed


def load_frontend_mapping(path: str | Path = "src/data/twStocks.ts") -> dict[str, str]:
    return parse_twstocks_seeds(Path(path).read_text(encoding="utf-8"))


def load_official_universe() -> dict[str, dict[str, Any]]:
    import runtime_bootstrap

    return runtime_bootstrap._load_dynamic_shioaji_universe_from_env()


def compare_universe_mappings(
    official: dict[str, dict[str, Any]],
    frontend: dict[str, str],
) -> dict[str, Any]:
    official_symbols = set(official)
    frontend_symbols = set(frontend)
    common_symbols = sorted(official_symbols & frontend_symbols)

    name_mismatches: list[tuple[str, str, str]] = []
    for symbol in common_symbols:
        official_name = str(official[symbol].get("name") or symbol).strip()
        frontend_name = str(frontend[symbol] or symbol).strip()
        if official_name != frontend_name:
            name_mismatches.append((symbol, official_name, frontend_name))

    missing_in_frontend = [
        (symbol, str(official[symbol].get("name") or symbol).strip())
        for symbol in sorted(official_symbols - frontend_symbols)
    ]
    extra_in_frontend = [
        (symbol, str(frontend[symbol] or symbol).strip())
        for symbol in sorted(frontend_symbols - official_symbols)
    ]

    return {
        "universe_total": len(official),
        "frontend_total": len(frontend),
        "common_total": len(common_symbols),
        "name_mismatches": name_mismatches,
        "missing_in_frontend": missing_in_frontend,
        "extra_in_frontend": extra_in_frontend,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        f"UNIVERSE_TOTAL {report['universe_total']}",
        f"FRONTEND_TOTAL {report['frontend_total']}",
        f"COMMON_TOTAL {report['common_total']}",
        f"NAME_MISMATCH_COUNT {len(report['name_mismatches'])}",
        f"MISSING_IN_FRONTEND {len(report['missing_in_frontend'])}",
        f"EXTRA_IN_FRONTEND {len(report['extra_in_frontend'])}",
    ]
    if report["name_mismatches"]:
        lines.append(f"NAME_MISMATCH_SAMPLE {report['name_mismatches'][:20]}")
    if report["missing_in_frontend"]:
        lines.append(f"MISSING_SAMPLE {report['missing_in_frontend'][:20]}")
    if report["extra_in_frontend"]:
        lines.append(f"EXTRA_SAMPLE {report['extra_in_frontend'][:20]}")
    lines.append("OK" if is_report_clean(report) else "FAIL")
    return "\n".join(lines)


def is_report_clean(report: dict[str, Any]) -> bool:
    return not (
        report["name_mismatches"]
        or report["missing_in_frontend"]
        or report["extra_in_frontend"]
    )


def main() -> int:
    load_dotenv_file()
    official = load_official_universe()
    frontend = load_frontend_mapping()
    report = compare_universe_mappings(official, frontend)
    print(format_report(report))
    return 0 if is_report_clean(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
