"""
sentiment_filter.py — 新聞情緒過濾器

接收 AnalyzerService 的情緒分析結果，
提供「是否阻擋買入」的查詢介面給 AutoTrader。

架構：
  1. AnalyzerService 分析文章後，呼叫 update(symbol, score)
  2. AutoTrader 在買入前呼叫 is_buy_blocked(symbol)
  3. SentimentConsumer（非同步任務）持續從 AnalyzerService.get_result() 消耗結果

Article ID 慣例：
  提交文章時，article_id 格式為 "{SYMBOL}:{uuid}"
  例如 "2330:abc123"。SentimentConsumer 解析前綴以對應股票代號。

使用方式：
    sf = SentimentFilter(block_threshold=-0.3)
    sf.update("2330", sentiment=-0.65)
    if not sf.is_buy_blocked("2330"):
        # 執行買入
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ── 預設參數 ──────────────────────────────────────────────────────────────────
BLOCK_THRESHOLD   = -0.3     # 情緒分數低於此值時阻擋買入
MAX_AGE_SECONDS   = 3600     # 情緒資料最多保留 1 小時
POLL_INTERVAL     = 0.5      # 消耗 AnalyzerService 結果的輪詢間隔（秒）


@dataclass
class SentimentEntry:
    symbol: str
    score: float
    updated_at: float        # Unix timestamp


class SentimentFilter:
    """
    維護每檔股票的最新情緒分數，提供阻擋查詢介面。
    所有操作為同步，可安全在 asyncio 單執行緒環境使用。
    """

    def __init__(
        self,
        *,
        block_threshold: float = BLOCK_THRESHOLD,
        max_age_seconds: float = MAX_AGE_SECONDS,
    ) -> None:
        self._threshold = block_threshold
        self._max_age = max_age_seconds
        self._entries: dict[str, SentimentEntry] = {}

    def update(self, symbol: str, sentiment: float) -> None:
        """更新某股票的情緒分數（由 SentimentConsumer 呼叫）。"""
        self._entries[symbol] = SentimentEntry(
            symbol=symbol,
            score=sentiment,
            updated_at=time.time(),
        )
        if sentiment < self._threshold:
            logger.info(
                "SentimentFilter: %s 情緒負面 (%.3f < %.3f)，加入阻擋清單",
                symbol, sentiment, self._threshold,
            )
        else:
            logger.debug("SentimentFilter: %s 情緒中性/正面 (%.3f)", symbol, sentiment)

    def is_buy_blocked(self, symbol: str) -> bool:
        """
        若該股存在近期負面新聞情緒，回傳 True。
        過期資料（超過 max_age_seconds）視為無效，不阻擋。
        """
        entry = self._entries.get(symbol)
        if entry is None:
            return False  # 無資料 → 不阻擋

        if time.time() - entry.updated_at > self._max_age:
            return False  # 資料過期 → 不阻擋

        return entry.score < self._threshold

    def get_score(self, symbol: str) -> float | None:
        """回傳最新情緒分數，無資料或已過期則回傳 None。"""
        entry = self._entries.get(symbol)
        if entry is None:
            return None
        if time.time() - entry.updated_at > self._max_age:
            return None
        return entry.score

    def clear_expired(self) -> int:
        """移除過期條目，回傳清除數量。"""
        now = time.time()
        expired = [
            sym for sym, e in self._entries.items()
            if now - e.updated_at > self._max_age
        ]
        for sym in expired:
            del self._entries[sym]
        if expired:
            logger.debug("SentimentFilter: 清除 %d 筆過期情緒資料", len(expired))
        return len(expired)

    def snapshot(self) -> list[dict]:
        """回傳目前有效情緒資料的快照（供偵錯用）。"""
        now = time.time()
        return [
            {
                "symbol": e.symbol,
                "score": round(e.score, 4),
                "blocked": e.score < self._threshold,
                "age_seconds": round(now - e.updated_at, 0),
            }
            for e in self._entries.values()
            if now - e.updated_at <= self._max_age
        ]


# ── 非同步消耗器 ──────────────────────────────────────────────────────────────

class SentimentConsumer:
    """
    背景非同步任務，持續從 AnalyzerService 消耗分析結果，
    並更新 SentimentFilter。

    Article ID 慣例：{SYMBOL}:{uuid} → 解析 SYMBOL 部分。
    """

    def __init__(
        self,
        analyzer: Any,               # AnalyzerService instance
        sentiment_filter: SentimentFilter,
        *,
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        self._analyzer = analyzer
        self._filter = sentiment_filter
        self._poll_interval = poll_interval
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._consume_loop(), name="sentiment-consumer")
        logger.info("SentimentConsumer: 已啟動")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SentimentConsumer: 已停止")

    async def _consume_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                # 在 executor 中非阻塞地嘗試取得結果（timeout=0 即 get_nowait）
                result = await loop.run_in_executor(
                    None, lambda: self._analyzer.get_result(timeout=0.05)
                )
                if result is not None:
                    self._process_result(result)
                else:
                    await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("SentimentConsumer: 處理結果時發生錯誤 %s", exc)
                await asyncio.sleep(self._poll_interval)

    def _process_result(self, result: Any) -> None:
        """
        從 AnalysisResult 中解析 symbol 並更新情緒過濾器。
        article_id 格式："{SYMBOL}:{rest}" → 取 SYMBOL 部分。
        """
        if not result.signal_valid:
            return

        article_id: str = getattr(result, "article_id", "")
        sentiment: float = getattr(result, "sentiment", 0.0)

        if ":" in article_id:
            symbol = article_id.split(":", 1)[0].strip().upper()
        else:
            symbol = article_id.strip().upper()

        if not symbol:
            return

        self._filter.update(symbol, sentiment)

        # 定期清理過期資料
        self._filter.clear_expired()
