from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from stock_universe_mapping import compare_universe_mappings, parse_twstocks_seeds


def test_parse_twstocks_seeds_decodes_unicode_names() -> None:
    ts_source = """
const STOCK_SEEDS: StockSeed[] = [
  ["1101", "\\u53f0\\u6ce5", "01", 0, 0],
  ["2330", "\\u53f0\\u7a4d\\u96fb", "24", 0, 0],
];
"""

    parsed = parse_twstocks_seeds(ts_source)

    assert parsed == {
        "1101": "台泥",
        "2330": "台積電",
    }


def test_compare_universe_mappings_reports_missing_extra_and_name_mismatches() -> None:
    official = {
        "1101": {"name": "台泥"},
        "2330": {"name": "台積電"},
        "7821": {"name": "神數"},
    }
    frontend = {
        "1101": "台泥",
        "2330": "台積",
        "4804": "大略-KY",
    }

    report = compare_universe_mappings(official, frontend)

    assert report["universe_total"] == 3
    assert report["frontend_total"] == 3
    assert report["common_total"] == 2
    assert report["name_mismatches"] == [("2330", "台積電", "台積")]
    assert report["missing_in_frontend"] == [("7821", "神數")]
    assert report["extra_in_frontend"] == [("4804", "大略-KY")]


def test_real_twstocks_seed_has_unique_symbol_keys() -> None:
    source = Path("src/data/twStocks.ts").read_text(encoding="utf-8")

    parsed = parse_twstocks_seeds(source)

    assert "2330" in parsed
    assert parsed["2330"]
    assert len(parsed) >= 1900
