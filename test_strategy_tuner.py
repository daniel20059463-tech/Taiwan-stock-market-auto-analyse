"""Tests for StrategyTuner: analysis logic and strategy_params.json write."""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from strategy_tuner import (
    ParamChange,
    ParamRecommendation,
    StrategyTuner,
    _DEFAULTS,
    _MIN_TRADE_COUNT,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_trade(
    *,
    action: str = "SELL",
    price: float = 100.0,
    stop_price: float = 97.0,
    pnl: float = 500.0,
    reason: str = "TAKE_PROFIT",
) -> dict:
    return {
        "action": action,
        "price": price,
        "stop_price": stop_price,
        "pnl": pnl,
        "reason": reason,
    }


def _make_tuner(tmp_params_file: str) -> StrategyTuner:
    tuner = StrategyTuner(db_session_factory=None)
    # Override the params file path for isolation
    import strategy_tuner as st_module
    st_module._PARAMS_FILE = tmp_params_file
    return tuner


# ── load_params ────────────────────────────────────────────────────────────────


def test_load_params_returns_defaults_when_file_missing(tmp_path) -> None:
    missing = str(tmp_path / "nonexistent.json")
    import strategy_tuner as st_module
    original = st_module._PARAMS_FILE
    st_module._PARAMS_FILE = missing
    try:
        params = StrategyTuner.load_params()
        assert params == _DEFAULTS
    finally:
        st_module._PARAMS_FILE = original


def test_load_params_reads_existing_file(tmp_path) -> None:
    params_file = tmp_path / "strategy_params.json"
    params_file.write_text(json.dumps({"BUY_SIGNAL_PCT": 3.0, "TRAIL_STOP_ATR_MULT": 2.5}), encoding="utf-8")

    import strategy_tuner as st_module
    original = st_module._PARAMS_FILE
    st_module._PARAMS_FILE = str(params_file)
    try:
        params = StrategyTuner.load_params()
        assert params["BUY_SIGNAL_PCT"] == 3.0
        assert params["TRAIL_STOP_ATR_MULT"] == 2.5
        assert params["VOLUME_CONFIRM_MULT"] == _DEFAULTS["VOLUME_CONFIRM_MULT"]
    finally:
        st_module._PARAMS_FILE = original


# ── _expected_value ────────────────────────────────────────────────────────────


def test_expected_value_empty_returns_zero() -> None:
    tuner = StrategyTuner(db_session_factory=None)
    assert tuner._expected_value([]) == 0.0


def test_expected_value_all_wins() -> None:
    tuner = StrategyTuner(db_session_factory=None)
    trades = [_make_trade(pnl=1000.0) for _ in range(5)]
    ev = tuner._expected_value(trades)
    assert ev == 1000.0


def test_expected_value_mixed() -> None:
    tuner = StrategyTuner(db_session_factory=None)
    trades = [
        _make_trade(pnl=1000.0),
        _make_trade(pnl=1000.0),
        _make_trade(pnl=-500.0),
        _make_trade(pnl=-500.0),
    ]
    ev = tuner._expected_value(trades)
    # 2/4 * 1000 + 2/4 * (-500) = 500 - 250 = 250
    assert abs(ev - 250.0) < 1e-6


# ── _tune_entry_threshold ─────────────────────────────────────────────────────


def test_tune_entry_threshold_returns_none_when_too_few_trades() -> None:
    tuner = StrategyTuner(db_session_factory=None)
    trades = [_make_trade() for _ in range(5)]  # below _MIN_TRADE_COUNT=10
    result = tuner._tune_entry_threshold(
        trades,
        param_name="BUY_SIGNAL_PCT",
        current_value=2.0,
        direction="long",
    )
    assert result is None


def test_tune_entry_threshold_suggests_increase_when_weak_ev_much_lower(tmp_path) -> None:
    """弱訊號 EV 顯著低於強訊號時，應建議提高入場門檻。

    使用 7 弱 + 5 強（共 12 筆），median index=6 落在弱訊號組內（strength=1），
    確保 strong group 正確分割出 5 筆高訊號強度成交。
    """
    tuner = StrategyTuner(db_session_factory=None)

    # Weak signal group: 7 trades with small stop distance (1%) → low signal strength → losing
    weak_trades = [
        _make_trade(price=100.0, stop_price=99.0, pnl=-400.0)  # 1% distance
        for _ in range(7)
    ]
    # Strong signal group: 5 trades with large stop distance (15%) → high signal strength → profitable
    strong_trades = [
        _make_trade(price=100.0, stop_price=85.0, pnl=1500.0)  # 15% distance
        for _ in range(5)
    ]
    # Sorted strengths: [1,1,1,1,1,1,1,15,15,15,15,15]; index 6 = 1
    # weak = strength <= 1 → 7 trades; strong = strength > 1 → 5 trades ✓
    trades = weak_trades + strong_trades

    result = tuner._tune_entry_threshold(
        trades,
        param_name="BUY_SIGNAL_PCT",
        current_value=2.0,
        direction="long",
    )
    assert result is not None
    assert result.param_name == "BUY_SIGNAL_PCT"
    assert result.new_value > result.old_value  # should increase threshold


def test_tune_entry_threshold_returns_none_when_evs_similar() -> None:
    """多空 EV 相近時，不應調整閾值。"""
    tuner = StrategyTuner(db_session_factory=None)
    # All trades same stop distance → same signal strength → median splits arbitrarily
    # but EV will be equal → no recommendation
    trades = [_make_trade(price=100.0, stop_price=97.0, pnl=500.0) for _ in range(12)]
    result = tuner._tune_entry_threshold(
        trades,
        param_name="BUY_SIGNAL_PCT",
        current_value=2.0,
        direction="long",
    )
    assert result is None


# ── _tune_trail_stop_mult ─────────────────────────────────────────────────────


def test_tune_trail_stop_returns_none_when_too_few_trades() -> None:
    tuner = StrategyTuner(db_session_factory=None)
    trades = [_make_trade(reason="TRAIL_STOP", pnl=200.0), _make_trade(reason="TAKE_PROFIT", pnl=800.0)]
    result = tuner._tune_trail_stop_mult(trades, current_value=2.0)
    assert result is None  # needs >= 3 in each group


def test_tune_trail_stop_suggests_increase_when_trail_pnl_much_lower() -> None:
    """TRAIL_STOP 平均 PnL 不到 TAKE_PROFIT 的 60% 時，應放寬 ATR 倍數。"""
    tuner = StrategyTuner(db_session_factory=None)
    # TRAIL_STOP avg PnL = 200, TAKE_PROFIT avg PnL = 800 → 200 < 800*0.6=480 → trigger
    trades = (
        [_make_trade(reason="TRAIL_STOP", pnl=200.0) for _ in range(4)]
        + [_make_trade(reason="TAKE_PROFIT", pnl=800.0) for _ in range(4)]
    )
    result = tuner._tune_trail_stop_mult(trades, current_value=2.0)
    assert result is not None
    assert result.param_name == "TRAIL_STOP_ATR_MULT"
    assert result.new_value > result.old_value


def test_tune_trail_stop_returns_none_when_trail_pnl_acceptable() -> None:
    """TRAIL_STOP 平均 PnL 超過 TAKE_PROFIT 的 60% 時，不應調整。"""
    tuner = StrategyTuner(db_session_factory=None)
    # TRAIL_STOP avg = 600, TAKE_PROFIT avg = 800 → 600 >= 480 → no change
    trades = (
        [_make_trade(reason="TRAIL_STOP", pnl=600.0) for _ in range(4)]
        + [_make_trade(reason="TAKE_PROFIT", pnl=800.0) for _ in range(4)]
    )
    result = tuner._tune_trail_stop_mult(trades, current_value=2.0)
    assert result is None


# ── _analyze_trades ───────────────────────────────────────────────────────────


def test_analyze_trades_returns_empty_when_no_changes_needed() -> None:
    tuner = StrategyTuner(db_session_factory=None)
    # Uniform trades: equal EV across groups → no recommendations
    trades = [_make_trade(price=100.0, stop_price=97.0, pnl=500.0) for _ in range(12)]
    rec = tuner._analyze_trades(trades, dict(_DEFAULTS))
    assert rec.is_empty()


def test_analyze_trades_produces_recommendation() -> None:
    """模擬弱訊號組 EV 差 + TRAIL_STOP 過早觸發，應產生至少一個建議。"""
    tuner = StrategyTuner(db_session_factory=None)

    strong = [_make_trade(price=100.0, stop_price=85.0, pnl=1500.0, action="SELL", reason="TAKE_PROFIT") for _ in range(6)]
    weak = [_make_trade(price=100.0, stop_price=99.0, pnl=-400.0, action="SELL", reason="STOP_LOSS") for _ in range(6)]
    trail = [_make_trade(price=100.0, stop_price=97.0, pnl=150.0, action="SELL", reason="TRAIL_STOP") for _ in range(4)]
    profit = [_make_trade(price=100.0, stop_price=97.0, pnl=900.0, action="SELL", reason="TAKE_PROFIT") for _ in range(4)]

    trades = strong + weak + trail + profit
    rec = tuner._analyze_trades(trades, dict(_DEFAULTS))
    assert not rec.is_empty()
    assert len(rec.changes) >= 1


# ── _apply writes params file ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_writes_strategy_params_json(tmp_path) -> None:
    """_apply 應將新參數寫入 strategy_params.json。"""
    params_file = str(tmp_path / "strategy_params.json")

    import strategy_tuner as st_module
    original = st_module._PARAMS_FILE
    st_module._PARAMS_FILE = params_file
    try:
        tuner = StrategyTuner(db_session_factory=None)
        rec = ParamRecommendation(
            changes=[
                ParamChange(
                    param_name="BUY_SIGNAL_PCT",
                    old_value=2.0,
                    new_value=2.4,
                    reason="test reason",
                    trade_count_basis=12,
                )
            ]
        )
        ts_ms = 1_775_500_000_000
        await tuner._apply(rec, ts_ms)

        assert os.path.exists(params_file)
        with open(params_file, encoding="utf-8") as f:
            written = json.load(f)

        assert written["BUY_SIGNAL_PCT"] == 2.4
        assert "updated_at" in written
        assert "reason" in written
    finally:
        st_module._PARAMS_FILE = original


# ── run skips when too few trades ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_skips_when_too_few_trades() -> None:
    """trades 不足 _MIN_TRADE_COUNT 時，run 應提前返回不寫任何檔案。"""
    tuner = StrategyTuner(db_session_factory=None)

    # _load_trades returns [] since db is None
    apply_mock = AsyncMock()
    tuner._apply = apply_mock

    await tuner.run(ts_ms=1_775_500_000_000)
    apply_mock.assert_not_called()


# ── max change ratio enforcement ─────────────────────────────────────────────


def test_tune_entry_threshold_change_does_not_exceed_max_ratio() -> None:
    """建議的新值變化幅度不應超過 _MAX_CHANGE_RATIO (20%)。"""
    from strategy_tuner import _MAX_CHANGE_RATIO
    tuner = StrategyTuner(db_session_factory=None)

    current = 2.0
    strong = [_make_trade(price=100.0, stop_price=80.0, pnl=2000.0) for _ in range(6)]
    weak = [_make_trade(price=100.0, stop_price=99.5, pnl=-1000.0) for _ in range(6)]
    trades = strong + weak

    result = tuner._tune_entry_threshold(
        trades,
        param_name="BUY_SIGNAL_PCT",
        current_value=current,
        direction="long",
    )
    if result is not None:
        ratio = abs(result.new_value - result.old_value) / result.old_value
        assert ratio <= _MAX_CHANGE_RATIO + 1e-6  # allow floating point margin
