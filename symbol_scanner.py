"""
symbol_scanner.py — 當日強勢股票掃描器（改良版）

改良重點：
  1. 多重過濾條件：
     - 排除近漲停（change_rate >= 9.0%）：委託積壓、無法成交
     - 排除在日內高點（price > high × 0.95）：追高風險高
     - 排除 09:00–09:15 早盤（市場尚未穩定，假突破多）
  2. 改良評分公式：
     舊：change_rate × log(total_amount)
     新：momentum_score × volume_quality_score × timing_factor
     - momentum_score：從開盤漲幅（非前收漲幅），過濾虛假跳空
     - volume_quality：成交量 / 市場中位數，衡量相對成交熱度
     - timing_factor：距收盤越近越扣分（13:00後已過最佳進場時機）
  3. 類股輪動分析：
     - 計算各類股平均強度，優先選擇強勢族群內的個股
  4. 資料品質：
     - 批次容錯：單批次失敗不中止整體掃描

使用方式：
    from symbol_scanner import scan_strong_symbols, ScanResult
    result = scan_strong_symbols(api, top_n=30)
    print(result.top_symbols)
    print(result.sector_strength)
"""
from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── 過濾參數 ──────────────────────────────────────────────────────────────────
MIN_CHANGE_PCT       = 0.5    # 最低漲幅門檻（排除平盤整理）
MAX_CHANGE_PCT       = 9.0    # 最高漲幅門檻（排除近漲停）
MIN_AMOUNT_THRESHOLD = 1_000  # 最低成交金額（萬元），排除冷門股
NEAR_HIGH_RATIO      = 0.90   # 現價 > 日高 × 此值 → 過於接近高點（與 auto_trader 一致）
EARLY_SESSION_MINS   = 15     # 開盤後前 15 分鐘不掃描（08:00–08:15）
LATE_SESSION_HOUR    = 16     # 16:00 後的個股評分打折（距收盤近）
LATE_SESSION_DISCOUNT = 0.7   # 13:00 後評分乘以此折扣

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))


@dataclass
class SymbolScore:
    """單檔股票的掃描評分詳情。"""
    code: str
    name: str
    sector: str
    change_rate: float          # 漲幅 %（相對前收）
    open_change_rate: float     # 相對開盤漲幅（日內動能）
    total_amount: float         # 成交金額
    last_price: float
    day_high: float
    day_low: float
    score: float                # 最終評分


@dataclass
class ScanResult:
    """掃描結果，包含股票清單與類股強度分析。"""
    top_symbols: list[str]
    symbol_details: list[SymbolScore]
    sector_strength: dict[str, float]       # sector → avg_score
    top_sector: str
    scan_time: str
    total_scanned: int
    filtered_count: int


def scan_strong_symbols(api: Any, *, top_n: int = 100) -> ScanResult:
    """
    掃描全市場上市股票，回傳當日最強勢的前 top_n 檔。

    回傳 ScanResult（包含詳細評分與類股分析）。
    若 API 失敗，回傳空 ScanResult。
    """
    now_tw = datetime.datetime.now(tz=_TZ_TW)
    scan_time = now_tw.strftime("%H:%M:%S")

    # ── 時段檢查：開盤前 15 分鐘不掃描 ──────────────────────────────────────
    is_early_session = (
        now_tw.hour == 8
        and now_tw.minute < EARLY_SESSION_MINS
    )
    if is_early_session:
        logger.info("symbol_scanner: 早盤前 %d 分鐘，跳過掃描", EARLY_SESSION_MINS)
        return _empty_result(scan_time=scan_time)

    is_late_session = now_tw.hour >= LATE_SESSION_HOUR

    # ── 取得合約清單 ──────────────────────────────────────────────────────────
    try:
        all_contracts = [
            c for c in api.Contracts.Stocks.TSE
            if len(getattr(c, "code", "")) == 4
        ]
    except Exception as exc:
        logger.error("無法取得合約清單: %s", exc)
        return _empty_result(scan_time=scan_time)

    logger.info(
        "symbol_scanner: TSE 共 %d 檔，開始 snapshot（時間=%s%s）",
        len(all_contracts),
        scan_time,
        " [尾盤]" if is_late_session else "",
    )

    # ── 批次抓 snapshot ───────────────────────────────────────────────────────
    batch_size = 200
    all_snapshots: list[Any] = []
    for i in range(0, len(all_contracts), batch_size):
        batch = all_contracts[i: i + batch_size]
        try:
            snaps = api.snapshots(batch)
            all_snapshots.extend(snaps)
        except Exception as exc:
            logger.warning(
                "symbol_scanner: 批次 %d 失敗（%d~%d）: %s",
                i // batch_size, i, i + batch_size, exc,
            )

    total_scanned = len(all_snapshots)
    if not all_snapshots:
        logger.warning("symbol_scanner: 未取得任何 snapshot")
        return _empty_result(scan_time=scan_time, total_scanned=0)

    # ── 計算市場中位數（用於 volume_quality）────────────────────────────────
    amounts = [
        float(getattr(s, "total_amount", 0) or 0)
        for s in all_snapshots
        if float(getattr(s, "total_amount", 0) or 0) > 0
    ]
    median_amount = _median(amounts) if amounts else 1.0

    # ── 過濾 + 評分 ──────────────────────────────────────────────────────────
    scored: list[SymbolScore] = []
    filtered_count = 0

    for s in all_snapshots:
        code = str(getattr(s, "code", "")).strip()
        if not code:
            continue

        change_rate = float(getattr(s, "change_rate", 0) or 0)
        total_amount = float(getattr(s, "total_amount", 0) or 0)
        last_price = float(getattr(s, "close", 0) or getattr(s, "price", 0) or 0)
        open_price = float(getattr(s, "open", 0) or 0)
        day_high = float(getattr(s, "high", 0) or last_price)
        day_low = float(getattr(s, "low", 0) or last_price)
        name = str(getattr(s, "name", code) or code)
        sector = str(getattr(s, "category", "市場") or "市場")

        # 過濾：最低漲幅
        if change_rate < MIN_CHANGE_PCT:
            filtered_count += 1
            continue

        # 過濾：近漲停（≥ 9%）
        if change_rate >= MAX_CHANGE_PCT:
            filtered_count += 1
            continue

        # 過濾：無成交
        if total_amount < MIN_AMOUNT_THRESHOLD:
            filtered_count += 1
            continue

        # 過濾：現價接近日高（頂部 5%）
        if day_high > day_low and last_price > day_high * NEAR_HIGH_RATIO:
            filtered_count += 1
            continue

        # ── 評分公式 ──────────────────────────────────────────────────────────

        # ① 動能分：相對開盤的漲幅（強調日內持續走強）
        if open_price > 0:
            open_change_rate = (last_price - open_price) / open_price * 100
        else:
            open_change_rate = change_rate

        # 同時考慮前收漲幅與日內動能，取加權平均
        momentum_score = change_rate * 0.4 + max(open_change_rate, 0) * 0.6

        # ② 量能品質分：相對市場成交熱度（log 壓縮避免大盤股壓倒一切）
        volume_quality = math.log1p(total_amount / median_amount)

        # ③ 尾盤折扣：13:00 後評分打折
        timing_factor = LATE_SESSION_DISCOUNT if is_late_session else 1.0

        score = momentum_score * volume_quality * timing_factor

        scored.append(SymbolScore(
            code=code,
            name=name,
            sector=sector,
            change_rate=round(change_rate, 2),
            open_change_rate=round(open_change_rate, 2),
            total_amount=total_amount,
            last_price=last_price,
            day_high=day_high,
            day_low=day_low,
            score=round(score, 4),
        ))

    # ── 類股輪動分析 ──────────────────────────────────────────────────────────
    sector_scores: dict[str, list[float]] = {}
    for item in scored:
        sector_scores.setdefault(item.sector, []).append(item.score)

    sector_strength = {
        sector: round(sum(scores) / len(scores), 4)
        for sector, scores in sector_scores.items()
        if scores
    }

    top_sector = max(sector_strength, key=lambda k: sector_strength[k]) if sector_strength else ""

    # ── 排序：優先選強勢類股內的個股 ────────────────────────────────────────
    def sort_key(item: SymbolScore) -> float:
        # 強勢類股內的個股額外加分 10%
        sector_bonus = 1.1 if item.sector == top_sector else 1.0
        return item.score * sector_bonus

    ranked = sorted(scored, key=sort_key, reverse=True)[:top_n]
    symbols = [item.code for item in ranked]

    if ranked:
        top3 = ", ".join(
            f"{item.code}({item.name}) +{item.change_rate:.1f}%"
            for item in ranked[:3]
        )
        logger.info(
            "symbol_scanner: 掃描 %d 檔 → 過濾 %d → 選出 %d 強勢股\n"
            "  前三：%s\n"
            "  強勢族群：%s（avg score=%.3f）",
            total_scanned,
            filtered_count,
            len(symbols),
            top3,
            top_sector,
            sector_strength.get(top_sector, 0),
        )
    else:
        logger.warning(
            "symbol_scanner: 掃描 %d 檔，過濾後無符合條件的強勢股",
            total_scanned,
        )

    return ScanResult(
        top_symbols=symbols,
        symbol_details=ranked,
        sector_strength=sector_strength,
        top_sector=top_sector,
        scan_time=scan_time,
        total_scanned=total_scanned,
        filtered_count=filtered_count,
    )


def _empty_result(*, scan_time: str = "", total_scanned: int = 0) -> ScanResult:
    return ScanResult(
        top_symbols=[],
        symbol_details=[],
        sector_strength={},
        top_sector="",
        scan_time=scan_time,
        total_scanned=total_scanned,
        filtered_count=0,
    )


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_v[mid - 1] + sorted_v[mid]) / 2
    return sorted_v[mid]
