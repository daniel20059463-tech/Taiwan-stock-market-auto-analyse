from __future__ import annotations

import sys

import pytest

import run_backtest


def test_parse_args_rejects_intraday_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_backtest.py", "2330", "2026-04-01", "2026-04-10", "--mode", "intraday"],
    )

    with pytest.raises(SystemExit):
        run_backtest.parse_args()


def test_parse_args_defaults_to_retail_flow_swing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_backtest.py", "2330", "2026-04-01", "2026-04-10"],
    )

    args = run_backtest.parse_args()

    assert args.mode == "retail_flow_swing"
