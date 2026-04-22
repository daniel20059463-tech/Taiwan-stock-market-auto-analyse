"""
Sector-level institutional flow aggregation and rotation detection.

"Rotation" here means large non-daytrading money (proxied by investment
trust / 投信) entering a sector significantly above its recent baseline.
Investment trust positions are held for weeks or months, so they represent
genuine positioning rather than intraday speculation.

Detection rule:
  today's sector trust_net_buy > historical_avg × MIN_MULTIPLIER
  AND today's sector trust_net_buy > MIN_TRUST_LOTS (absolute floor)
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field


@dataclass
class SectorFlowSnapshot:
    sector: str
    trust_net_buy: int       # 投信淨買超合計（張）
    foreign_net_buy: int     # 外資淨買超合計（張）
    symbol_count: int        # 類股中有幾支出現投信淨買超
    top_symbols: list[str] = field(default_factory=list)  # 投信買超最多的前3支


@dataclass
class RotationSignal:
    sector: str
    trust_net_buy: int
    avg_trust_net_buy: float     # 近期歷史平均
    multiplier: float            # today / avg
    symbol_count: int
    top_symbols: list[str]


MIN_TRUST_LOTS = 500       # 類股投信合計淨買超至少 500 張才算有意義
MIN_MULTIPLIER = 2.0       # 今日必須是歷史均值的 2 倍以上
MIN_HISTORY_DAYS = 3       # 至少要有 3 天歷史才做比較


def aggregate_sector_flows(
    rows: list,               # list[InstitutionalFlowRow]
    sector_map: dict[str, str],  # symbol -> sector
) -> dict[str, SectorFlowSnapshot]:
    """
    Group institutional flow rows by sector and compute totals.
    Symbols without a sector mapping are skipped.
    """
    buckets: dict[str, dict] = {}

    for row in rows:
        sector = sector_map.get(row.symbol, "")
        if not sector:
            continue
        if sector not in buckets:
            buckets[sector] = {
                "trust_net_buy": 0,
                "foreign_net_buy": 0,
                "symbol_contributions": [],
            }
        buckets[sector]["trust_net_buy"] += row.investment_trust_net_buy
        buckets[sector]["foreign_net_buy"] += row.foreign_net_buy
        if row.investment_trust_net_buy > 0:
            buckets[sector]["symbol_contributions"].append(
                (row.symbol, row.investment_trust_net_buy)
            )

    snapshots: dict[str, SectorFlowSnapshot] = {}
    for sector, data in buckets.items():
        contribs = sorted(data["symbol_contributions"], key=lambda x: x[1], reverse=True)
        snapshots[sector] = SectorFlowSnapshot(
            sector=sector,
            trust_net_buy=data["trust_net_buy"],
            foreign_net_buy=data["foreign_net_buy"],
            symbol_count=len(contribs),
            top_symbols=[s for s, _ in contribs[:3]],
        )

    return snapshots


def detect_rotation_signals(
    today_flows: dict[str, SectorFlowSnapshot],
    history_flows: list[dict[str, SectorFlowSnapshot]],  # oldest first
    min_trust_lots: int = MIN_TRUST_LOTS,
    min_multiplier: float = MIN_MULTIPLIER,
) -> list[RotationSignal]:
    """
    Return sectors where today's institutional trust buying significantly
    exceeds the recent baseline. Only fires when:
      1. Absolute buying ≥ min_trust_lots
      2. Today / historical_avg ≥ min_multiplier
      3. At least MIN_HISTORY_DAYS days of history exist
    """
    if len(history_flows) < MIN_HISTORY_DAYS:
        return []

    signals: list[RotationSignal] = []

    for sector, today_snap in today_flows.items():
        if today_snap.trust_net_buy < min_trust_lots:
            continue

        historical_values = [
            h[sector].trust_net_buy
            for h in history_flows
            if sector in h
        ]
        if len(historical_values) < MIN_HISTORY_DAYS:
            continue

        avg = statistics.mean(historical_values)
        if avg <= 0:
            # baseline was net-selling; any buying is notable but can't compute ratio
            # use a fixed threshold instead
            if today_snap.trust_net_buy >= min_trust_lots * 2:
                signals.append(RotationSignal(
                    sector=sector,
                    trust_net_buy=today_snap.trust_net_buy,
                    avg_trust_net_buy=avg,
                    multiplier=float("inf"),
                    symbol_count=today_snap.symbol_count,
                    top_symbols=today_snap.top_symbols,
                ))
            continue

        multiplier = today_snap.trust_net_buy / avg
        if multiplier >= min_multiplier:
            signals.append(RotationSignal(
                sector=sector,
                trust_net_buy=today_snap.trust_net_buy,
                avg_trust_net_buy=round(avg, 0),
                multiplier=round(multiplier, 1),
                symbol_count=today_snap.symbol_count,
                top_symbols=today_snap.top_symbols,
            ))

    return sorted(signals, key=lambda s: s.trust_net_buy, reverse=True)


def format_rotation_alert(signals: list[RotationSignal], trade_date: str) -> str:
    """Build a Telegram-friendly rotation alert message."""
    if not signals:
        return ""

    lines = [f"[類股輪動偵測] {trade_date}"]
    lines.append("發現大資金（非當沖）進場以下類股：\n")

    for sig in signals[:3]:  # limit to top 3
        mult_str = f"{sig.multiplier:.1f}x" if sig.multiplier != float("inf") else "新啟動"
        top = "、".join(sig.top_symbols) if sig.top_symbols else "—"
        lines.append(
            f"▶ {sig.sector}\n"
            f"  投信淨買超：{sig.trust_net_buy:+,} 張（歷史均值 {sig.avg_trust_net_buy:,.0f} 張，{mult_str}）\n"
            f"  主導標的：{top}"
        )

    lines.append("\n注意：此訊號為波段佈局參考，非當日進場建議。")
    return "\n".join(lines)
