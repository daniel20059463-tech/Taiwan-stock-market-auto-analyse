from __future__ import annotations

from types import SimpleNamespace

from backtest import _calc_max_drawdown, _compute_result


def _sell_trade(pnl: float) -> SimpleNamespace:
    return SimpleNamespace(
        symbol="2330",
        action="SELL",
        price=100.0,
        shares=1000,
        pnl=pnl,
        reason="TEST",
    )


def test_calc_max_drawdown_uses_initial_equity_baseline() -> None:
    sells = [
        _sell_trade(10_000.0),
        _sell_trade(-20_000.0),
        _sell_trade(5_000.0),
    ]

    max_dd = _calc_max_drawdown(sells, initial_equity=1_000_000.0)

    assert round(max_dd, 2) == 1.98


def test_compute_result_uses_risk_capital_for_drawdown() -> None:
    sells = [
        _sell_trade(20_000.0),
        _sell_trade(-30_000.0),
    ]

    result = _compute_result(sells, initial_equity=1_000_000.0)

    assert result.total_trades == 2
    assert result.max_drawdown_pct == 2.94
