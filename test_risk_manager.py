"""Tests for RiskManager — covers can_buy gates, stop/sizing/target math,
on_sell state tracking, calc_net_pnl, and drawdown properties."""
from __future__ import annotations

import time

import pytest

from risk_manager import (
    RiskManager,
    TX_FEE_BUY_PCT,
    TX_FEE_SELL_PCT,
    TX_TAX_SELL_PCT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_rm(**kwargs) -> RiskManager:
    defaults = {"account_capital": 1_000_000.0}
    defaults.update(kwargs)
    return RiskManager(**defaults)


# ---------------------------------------------------------------------------
# can_buy — pass
# ---------------------------------------------------------------------------

def test_can_buy_passes_when_all_clear():
    rm = make_rm()
    ok, msg = rm.can_buy("2330", price=100.0, shares=1000, current_positions=0)
    assert ok
    assert msg == "OK"


# ---------------------------------------------------------------------------
# can_buy — daily loss limit
# ---------------------------------------------------------------------------

def test_can_buy_blocked_by_daily_loss_limit():
    rm = make_rm(account_capital=1_000_000.0, max_daily_loss_pct=2.0)
    # max_daily_loss = 20,000
    rm.on_sell("2330", pnl=-20_001.0)
    ok, msg = rm.can_buy("2330", price=100.0, shares=1000, current_positions=0)
    assert not ok
    assert "每日損失限制" in msg


def test_can_buy_allowed_just_below_daily_loss_limit():
    rm = make_rm(account_capital=1_000_000.0, max_daily_loss_pct=2.0)
    rm.on_sell("2330", pnl=-19_999.0)
    ok, _ = rm.can_buy("2330", price=100.0, shares=1000, current_positions=0)
    assert ok


# ---------------------------------------------------------------------------
# can_buy — rolling 5-day loss
# ---------------------------------------------------------------------------

def test_can_buy_blocked_by_rolling_5day_loss():
    # max_daily_loss_pct=100 so daily gate doesn't fire first
    rm = make_rm(account_capital=1_000_000.0, rolling_5day_loss_pct=6.0, max_daily_loss_pct=100.0)
    # max_rolling_loss = 60,000 — accumulate via multiple sells in one day
    for _ in range(4):
        rm.on_sell("2330", pnl=-16_000.0)
    ok, msg = rm.can_buy("2330", price=100.0, shares=1000, current_positions=0)
    assert not ok
    assert "近五日損益" in msg


# ---------------------------------------------------------------------------
# can_buy — global drawdown
# ---------------------------------------------------------------------------

def test_can_buy_blocked_by_global_drawdown():
    # max_daily_loss_pct=100 and rolling=100 so those gates don't fire first
    rm = make_rm(account_capital=1_000_000.0, max_daily_loss_pct=100.0, rolling_5day_loss_pct=100.0)
    # 16% loss exceeds MAX_GLOBAL_DRAWDOWN_PCT (15%)
    rm.on_sell("2330", pnl=-160_000.0)
    ok, msg = rm.can_buy("2330", price=100.0, shares=1000, current_positions=0)
    assert not ok
    assert "回撤" in msg


# ---------------------------------------------------------------------------
# can_buy — cooldown after consecutive losses
# ---------------------------------------------------------------------------

def test_can_buy_blocked_during_cooldown():
    rm = make_rm()
    for _ in range(3):
        rm.on_sell("2330", pnl=-1.0)
    assert rm.is_in_cooldown
    ok, msg = rm.can_buy("2330", price=100.0, shares=1000, current_positions=0)
    assert not ok
    assert "冷卻" in msg


def test_consecutive_loss_counter_resets_on_win():
    rm = make_rm()
    rm.on_sell("2330", pnl=-1.0)
    rm.on_sell("2330", pnl=-1.0)
    rm.on_sell("2330", pnl=+500.0)  # win resets counter
    assert rm.consecutive_losses == 0
    assert not rm.is_in_cooldown


# ---------------------------------------------------------------------------
# can_buy — position cap
# ---------------------------------------------------------------------------

def test_can_buy_blocked_by_position_cap():
    rm = make_rm(max_positions=5)
    ok, msg = rm.can_buy("2330", price=100.0, shares=1000, current_positions=5)
    assert not ok
    assert "持倉檔數" in msg


# ---------------------------------------------------------------------------
# can_buy — single position size
# ---------------------------------------------------------------------------

def test_can_buy_blocked_by_single_position_size():
    rm = make_rm(account_capital=1_000_000.0, max_single_pos_pct=10.0)
    # max_single_position = 100,000; price*shares = 200*1000 = 200,000
    ok, msg = rm.can_buy("2330", price=200.0, shares=1000, current_positions=0)
    assert not ok
    assert "單筆部位" in msg


def test_can_buy_passes_at_exactly_single_position_limit():
    rm = make_rm(account_capital=1_000_000.0, max_single_pos_pct=10.0)
    # 100 * 1000 = 100,000 == max_single_position (not >, so passes)
    ok, _ = rm.can_buy("2330", price=100.0, shares=1000, current_positions=0)
    assert ok


# ---------------------------------------------------------------------------
# calc_stop_price
# ---------------------------------------------------------------------------

def test_calc_stop_price_uses_atr():
    rm = make_rm()
    # atr_multiplier=2.0, entry=100, atr=2 → raw_stop_pct = 4% → within [1.5,6]
    stop = rm.calc_stop_price(entry_price=100.0, atr=2.0)
    assert abs(stop - 96.0) < 0.01


def test_calc_stop_price_clamped_to_min():
    rm = make_rm(min_stop_pct=1.5)
    # Very small ATR → clamped to min
    stop = rm.calc_stop_price(entry_price=100.0, atr=0.1)
    assert abs(stop - (100.0 * (1 - 1.5 / 100))) < 0.01


def test_calc_stop_price_clamped_to_max():
    rm = make_rm(max_stop_pct=6.0)
    # Huge ATR → clamped to max
    stop = rm.calc_stop_price(entry_price=100.0, atr=50.0)
    assert abs(stop - (100.0 * (1 - 6.0 / 100))) < 0.01


def test_calc_stop_price_fallback_when_no_atr():
    rm = make_rm(min_stop_pct=1.5, max_stop_pct=6.0)
    # No ATR → midpoint = 3.75%
    stop = rm.calc_stop_price(entry_price=100.0, atr=None)
    expected = 100.0 * (1 - 3.75 / 100)
    assert abs(stop - expected) < 0.01


# ---------------------------------------------------------------------------
# calc_position_shares
# ---------------------------------------------------------------------------

def test_calc_position_shares_normal():
    # max_single_pos_pct=30 → max_single=300,000 → won't cap 2000 shares @100
    rm = make_rm(account_capital=1_000_000.0, max_single_pos_pct=30.0)
    # risk_amount = 10,000; risk_per_share = 100-95 = 5; raw = 2000 → 2000 shares
    shares = rm.calc_position_shares(entry_price=100.0, stop_price=95.0)
    assert shares == 2000


def test_calc_position_shares_capped_by_max_single_position():
    rm = make_rm(account_capital=1_000_000.0, max_single_pos_pct=10.0)
    # max_single_position = 100,000; at price=100 → max 1000 shares
    shares = rm.calc_position_shares(entry_price=100.0, stop_price=50.0)
    assert shares == 1000


def test_calc_position_shares_floor_when_risk_per_share_zero():
    rm = make_rm()
    shares = rm.calc_position_shares(entry_price=100.0, stop_price=100.0)
    assert shares == 1000  # falls back to lot_size


# ---------------------------------------------------------------------------
# calc_target_price
# ---------------------------------------------------------------------------

def test_calc_target_price():
    rm = make_rm(risk_reward_ratio=2.0)
    # entry=100, stop=95 → risk=5 → target=110
    target = rm.calc_target_price(entry_price=100.0, stop_price=95.0)
    assert abs(target - 110.0) < 0.01


# ---------------------------------------------------------------------------
# calc_net_pnl
# ---------------------------------------------------------------------------

def test_calc_net_pnl_profitable_trade():
    rm = make_rm()
    # gross = (110-100)*1000 = 10,000
    # buy_fee = 100*1000*0.1425/100 = 142.5
    # sell_fee = 110*1000*(0.1425+0.30)/100 = 487.025 (≈487.25 actually)
    net = rm.calc_net_pnl(entry_price=100.0, sell_price=110.0, shares=1000)
    buy_fee = 100.0 * 1000 * TX_FEE_BUY_PCT / 100
    sell_fee = 110.0 * 1000 * (TX_FEE_SELL_PCT + TX_TAX_SELL_PCT) / 100
    expected = round(10_000.0 - buy_fee - sell_fee, 2)
    assert abs(net - expected) < 0.01


def test_calc_net_pnl_losing_trade():
    rm = make_rm()
    net = rm.calc_net_pnl(entry_price=100.0, sell_price=95.0, shares=1000)
    assert net < 0


# ---------------------------------------------------------------------------
# current_drawdown_pct
# ---------------------------------------------------------------------------

def test_current_drawdown_pct_zero_at_start():
    rm = make_rm()
    assert rm.current_drawdown_pct == 0.0


def test_current_drawdown_pct_after_loss():
    rm = make_rm(account_capital=1_000_000.0)
    rm.on_sell("2330", pnl=-100_000.0)
    dd = rm.current_drawdown_pct
    assert abs(dd - 10.0) < 0.01


def test_current_drawdown_pct_recovers_after_gain():
    rm = make_rm(account_capital=1_000_000.0)
    rm.on_sell("2330", pnl=-100_000.0)
    rm.on_sell("2330", pnl=+100_000.0)
    assert rm.current_drawdown_pct == 0.0


# ---------------------------------------------------------------------------
# is_halted / is_weekly_halted
# ---------------------------------------------------------------------------

def test_is_halted_true_after_daily_limit_exceeded():
    rm = make_rm(account_capital=1_000_000.0, max_daily_loss_pct=2.0)
    rm.on_sell("2330", pnl=-20_001.0)
    assert rm.is_halted


def test_is_weekly_halted_true_after_rolling_limit():
    rm = make_rm(account_capital=1_000_000.0, rolling_5day_loss_pct=6.0)
    for _ in range(3):
        rm.on_sell("2330", pnl=-20_001.0)
    assert rm.is_weekly_halted


# ---------------------------------------------------------------------------
# just_entered_cooldown — one-shot flag
# ---------------------------------------------------------------------------

def test_just_entered_cooldown_fires_once():
    rm = make_rm()
    for _ in range(3):
        rm.on_sell("2330", pnl=-1.0)
    assert rm.just_entered_cooldown is True
    assert rm.just_entered_cooldown is False  # second read resets


# ---------------------------------------------------------------------------
# status_dict
# ---------------------------------------------------------------------------

def test_status_dict_returns_expected_keys():
    rm = make_rm()
    d = rm.status_dict()
    for key in ("date", "dailyPnl", "isHalted", "currentDrawdownPct", "isInCooldown"):
        assert key in d
