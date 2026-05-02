"""
International market news fetcher with OpenAI Traditional Chinese summarization.

Fetches RSS feeds from major financial news sources every 10 minutes,
then uses gpt-4o-mini to translate and summarize into Traditional Chinese
with a note on potential impact for Taiwan stocks.
"""
from __future__ import annotations

import datetime
import logging
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from typing import Any

logger = logging.getLogger(__name__)

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
CACHE_TTL_SECONDS = 600  # 10 minutes

RSS_FEEDS = [
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("MarketWatch",   "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Investopedia",  "https://www.investopedia.com/feedbuilder/feed/getfeed/?feedName=rss_headline"),
]

MAX_ITEMS_PER_FEED = 8
MAX_SUMMARIZE = 12


@dataclass
class NewsItem:
    title: str
    summary: str        # OpenAI-generated Traditional Chinese summary
    source: str
    url: str
    published_at: str


class InternationalNewsFetcher:
    def __init__(self) -> None:
        self._cache: list[NewsItem] = []
        self._cache_ts: float = 0.0
        self._client: Any = None

    # ── OpenAI ───────────────────────────────────────────────────────────────

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key or api_key.startswith("your_"):
            return None
        try:
            import openai
            self._client = openai.OpenAI(
                api_key=api_key,
                base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                timeout=float(os.environ.get("OPENAI_TIMEOUT_SECONDS", "30")),
            )
        except Exception as exc:
            logger.warning("OpenAI client init failed: %s", exc)
        return self._client

    def _summarize(self, headlines: list[dict]) -> list[NewsItem]:
        client = self._get_client()
        summaries: list[str] = []

        if client is not None:
            headlines_text = "\n".join(
                f"{i + 1}. [{h['source']}] {h['title']}"
                for i, h in enumerate(headlines)
            )
            prompt = (
                "以下是國際財經新聞標題，請用繁體中文為每則新聞提供一句摘要（25字以內），"
                "並在末尾加上對台股可能影響的簡短評語（用「→」符號開頭，例如：→ 利多半導體族群）。"
                "若無明顯關聯則寫「→ 影響中性」。\n"
                "格式：{編號}. {摘要} {→影響}\n\n"
                f"{headlines_text}"
            )
            try:
                model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=900,
                    temperature=0.3,
                )
                raw = resp.choices[0].message.content or ""
                for line in raw.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    # Strip leading "N. "
                    if line and line[0].isdigit() and ". " in line[:5]:
                        line = line.split(". ", 1)[1]
                    summaries.append(line)
            except Exception as exc:
                logger.warning("OpenAI summarize failed: %s", exc)

        items: list[NewsItem] = []
        for i, h in enumerate(headlines):
            summary = summaries[i] if i < len(summaries) else h["title"]
            items.append(NewsItem(
                title=h["title"],
                summary=summary,
                source=h["source"],
                url=h.get("link", ""),
                published_at=h.get("pubDate", ""),
            ))
        return items

    # ── RSS ──────────────────────────────────────────────────────────────────

    def _fetch_rss(self, source: str, url: str) -> list[dict]:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; newsfetcher/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            items: list[dict] = []
            for item in root.iter("item"):
                title = item.findtext("title", "").strip()
                link = item.findtext("link", "").strip()
                pub_date = item.findtext("pubDate", "").strip()
                if title:
                    items.append({"title": title, "link": link, "pubDate": pub_date, "source": source})
            return items[:MAX_ITEMS_PER_FEED]
        except Exception as exc:
            logger.debug("RSS fetch failed for %s: %s", url, exc)
            return []

    # ── public API ───────────────────────────────────────────────────────────

    def fetch(self, force: bool = False) -> list[NewsItem]:
        now = time.time()
        if not force and self._cache and (now - self._cache_ts) < CACHE_TTL_SECONDS:
            return self._cache

        all_headlines: list[dict] = []
        for source_name, url in RSS_FEEDS:
            all_headlines.extend(self._fetch_rss(source_name, url))

        if not all_headlines:
            logger.warning("No news fetched from any RSS source; returning stale cache")
            return self._cache

        # Deduplicate by title prefix
        seen: set[str] = set()
        unique: list[dict] = []
        for h in all_headlines:
            key = h["title"][:40].lower()
            if key not in seen:
                seen.add(key)
                unique.append(h)

        self._cache = self._summarize(unique[:MAX_SUMMARIZE])
        self._cache_ts = now
        logger.info("International news refreshed: %d items", len(self._cache))
        return self._cache

    def to_payload(self) -> dict:
        items = self.fetch()
        return {
            "type": "INTERNATIONAL_NEWS",
            "updatedAt": datetime.datetime.now(tz=_TZ_TW).isoformat(),
            "items": [asdict(item) for item in items],
        }
