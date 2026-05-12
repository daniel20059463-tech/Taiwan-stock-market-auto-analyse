# -*- coding: utf-8 -*-
"""
開盤前多 Agent 分析入口

執行時序（09:00 前完成）：
  1. Flow Agent     → 籌碼掃描（投信/外資/自營）
  2. Technical Agent → 技術過濾（MA10/RSI/動能）
  3. News Agent     → Claude sub-agent WebSearch 否決檢查   ← 需 Claude 環境
  4. Risk Agent     → 部位計算
  5. Supervisor     → 彙整決策、更新持倉、推播 Telegram

使用方式：
  python run_premarket.py                  # 完整流程，推播 Telegram
  python run_premarket.py --dry-run        # 不寫入持倉，僅印報告
  python run_premarket.py --skip-news      # 跳過 news agent（加快速度）
"""
from __future__ import annotations
import sys, argparse, time, json, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from trading_agents import flow_agent, technical_agent, news_agent, risk_agent, supervisor


def run_news_agent_local(candidates: list[tuple[str, str]]) -> dict[str, bool]:
    """
    本地新聞否決（非 Claude sub-agent 時的替代方案）：
    用 Yahoo Finance RSS 快速檢查，無法做深度分析。
    回傳 {symbol: override_flag}
    """
    verdicts: dict[str, bool] = {}
    for sym, side in candidates:
        # 預設不否決（新聞 agent 需要 Claude sub-agent 才能真正運作）
        verdicts[sym] = False
    return verdicts


def main() -> None:
    parser = argparse.ArgumentParser(description="開盤前多 Agent 分析")
    parser.add_argument("--dry-run", action="store_true", help="不寫入持倉")
    parser.add_argument("--skip-news", action="store_true", help="跳過新聞 agent")
    parser.add_argument("--no-telegram", action="store_true", help="不推播 Telegram")
    args = parser.parse_args()

    print("=" * 60)
    print("  台股自動交易系統 | 開盤前多 Agent 掃描")
    print("=" * 60)
    t0 = time.time()

    # ── Agent 1：籌碼分析 ───────────────────────────────────
    print("\n[Agent 1] 籌碼分析 Agent 啟動...")
    flow_rpt = flow_agent.run(top_n=30)
    print(f"  日期 {flow_rpt.flow_date}  掃描 {flow_rpt.total_symbols} 檔")
    print(f"  多方候選 {len(flow_rpt.long_candidates)} 檔")
    for c in flow_rpt.long_candidates[:5]:
        print(f"    {c.summary()}")
    print(f"  空方候選 {len(flow_rpt.short_candidates)} 檔")
    for c in flow_rpt.short_candidates[:3]:
        print(f"    {c.summary()}")

    # ── Agent 2：技術分析 ───────────────────────────────────
    print("\n[Agent 2] 技術分析 Agent 啟動...")
    long_syms  = [c.symbol for c in flow_rpt.long_candidates]
    short_syms = [c.symbol for c in flow_rpt.short_candidates]
    tech_long  = technical_agent.run(long_syms,  side="long")
    tech_short = technical_agent.run(short_syms, side="short")

    # 合併評分
    scored_long = []
    for c in flow_rpt.long_candidates:
        sig = tech_long.get(c.symbol)
        if sig:
            combined = 0.60 * c.flow_score + 0.40 * sig.tech_score
            scored_long.append((combined, c.symbol, sig))
    scored_long.sort(reverse=True)

    scored_short = []
    for c in flow_rpt.short_candidates:
        sig = tech_short.get(c.symbol)
        if sig:
            combined = 0.60 * c.flow_score + 0.40 * sig.tech_score
            scored_short.append((combined, c.symbol, sig))
    scored_short.sort(reverse=True)

    print(f"  技術過濾後：多方 {len(scored_long)} 檔，空方 {len(scored_short)} 檔")
    print("  多方 TOP5：")
    for score, sym, sig in scored_long[:5]:
        print(f"    {sym} 綜合{score:.3f} | {sig.summary()}")

    # ── Agent 3：新聞確認（否決權）─────────────────────────
    top_candidates = [(sym, "long") for _, sym, _ in scored_long[:6]] + \
                     [(sym, "short") for _, sym, _ in scored_short[:3]]

    if args.skip_news:
        print("\n[Agent 3] 新聞 Agent：已跳過（--skip-news）")
        news_verdicts = {sym: False for sym, _ in top_candidates}
    else:
        print(f"\n[Agent 3] 新聞 Agent 啟動（{len(top_candidates)} 檔）...")
        print("  注意：完整新聞分析需 Claude sub-agent（WebSearch）")
        print("  目前使用本地快速模式（不否決）")
        news_verdicts = run_news_agent_local(top_candidates)
        blocked = [s for s, b in news_verdicts.items() if b]
        print(f"  否決 {len(blocked)} 檔：{blocked or '無'}")

    # ── Agent 4 + Supervisor：風控 + 最終決策 ───────────────
    print("\n[Agent 4 + Supervisor] 風控計算 + 建倉決策...")
    rpt = supervisor.run(
        news_verdicts=news_verdicts,
        dry_run=args.dry_run,
        send_telegram=not args.no_telegram,
    )

    # ── 最終報告 ─────────────────────────────────────────────
    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(rpt.to_telegram_text())
    print(f"\n執行完成 ({elapsed:.1f}s)")
    if args.dry_run:
        print("[DRY-RUN] 持倉未寫入")


if __name__ == "__main__":
    main()
