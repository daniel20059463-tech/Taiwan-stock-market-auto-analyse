# -*- coding: utf-8 -*-
"""
Agent 3：新聞確認 Agent（否決權 Agent）

責任：
- 接收最終候選股清單（經過籌碼+技術雙重篩選後）
- 用 WebSearch 搜尋重大事件（財報、法說、利空）
- 輸出：是否有理由否決進場（override flag）
- 不主導選股，只扮演「最後關卡」

注意：此 agent 需在 Claude 環境內由 supervisor 呼叫（使用 Agent tool + WebSearch）
      本模組提供 prompt 模板與結果解析，實際搜尋由 Claude sub-agent 執行。
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class NewsVerdict:
    symbol: str
    override: bool          # True = 否決進場
    reason: str             # 否決或通過的理由
    confidence: float       # 0~1，新聞確定性


@dataclass
class NewsReport:
    verdicts: dict[str, NewsVerdict] = field(default_factory=dict)

    def is_blocked(self, symbol: str) -> bool:
        v = self.verdicts.get(symbol)
        return v.override if v else False

    def summary(self, symbol: str) -> str:
        v = self.verdicts.get(symbol)
        if not v:
            return f"{symbol}: 無新聞資料（預設通過）"
        tag = "否決" if v.override else "通過"
        return f"{symbol} [{tag}] {v.reason}"


def build_search_prompt(symbol: str, side: str) -> str:
    """產生給 Claude sub-agent 的搜尋指令。"""
    direction = "做多" if side == "long" else "放空"
    return (
        f"請搜尋台股 {symbol} 在 2026年5月 的最新新聞。\n"
        f"我打算{direction}這檔股票。\n"
        f"請只回報**會改變基本面或造成重大波動**的事件，例如：\n"
        f"- 突發利空（財務造假、重大訴訟、產品召回、客戶流失）\n"
        f"- 已知但未反映的重大利多（法說會超預期、大客戶訂單）\n"
        f"- 即將除息除權（影響價格計算）\n"
        f"- 技術性停牌或下市風險\n\n"
        f"輸出格式（JSON）：\n"
        f'{{"override": true/false, "reason": "一句話說明", "confidence": 0.0~1.0}}\n'
        f"若無重大事件則 override=false，reason 說明「無重大事件」。"
    )


def parse_verdict(symbol: str, raw: str) -> NewsVerdict:
    """解析 sub-agent 回傳的 JSON 字串。"""
    import json, re
    try:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            d = json.loads(m.group())
            return NewsVerdict(
                symbol=symbol,
                override=bool(d.get("override", False)),
                reason=str(d.get("reason", "")),
                confidence=float(d.get("confidence", 0.5)),
            )
    except Exception:
        pass
    return NewsVerdict(symbol=symbol, override=False,
                       reason="解析失敗，預設通過", confidence=0.3)
