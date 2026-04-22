"""
Fetches a complete symbol → sector mapping from TWSE / TPEX public APIs.

TWSE: https://openapi.twse.com.tw/v1/opendata/t187ap03_L
TPEX: https://www.tpex.org.tw/openapi/v1/tpex_mainboard_companies_information

Results are cached to disk with a 7-day TTL so restarts don't re-fetch.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

try:
    import urllib.request as _urllib
except ImportError:
    _urllib = None  # type: ignore

logger = logging.getLogger(__name__)

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_companies_information"

SECTOR_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_REQUEST_TIMEOUT = 15

# TWSE 産業別代碼 → 中文名稱（2021 年重分類後版本）
# 驗證依據：2330 TSMC=24(半導體), 2303 UMC=24, 2454 MediaTek=24,
#           2357 Asus=25(電腦及週邊), 2382 Quanta=25,
#           2409 AUO=26(光電業), 3481 Innolux=26,
#           2412 CHT=27(通信網路業), 2308 Delta=28(電子零組件業),
#           2317 Hon Hai=31(其他電子業), 2882 Cathay=17(金融保險),
#           2002 China Steel=10(鋼鐵工業), 2618 EVA Air=15(航運業),
#           1301 Formosa Plastics=03(塑膠工業)
_TWSE_SECTOR_NAMES: dict[str, str] = {
    "01": "水泥工業",
    "02": "食品工業",
    "03": "塑膠工業",
    "04": "紡織纖維",
    "05": "電機機械",
    "06": "電器電纜",
    "07": "化學工業",
    "08": "玻璃陶瓷",
    "09": "造紙工業",
    "10": "鋼鐵工業",
    "11": "橡膠工業",
    "12": "汽車工業",
    "13": "電子工業",
    "14": "建材營造",
    "15": "航運業",
    "16": "觀光餐旅",
    "17": "金融保險",
    "18": "貿易百貨",
    "19": "油電燃氣",
    # 2021 新增四類（代碼 20–23）
    "20": "綠能環保",
    "21": "數位雲端",
    "22": "運動休閒",
    "23": "居家生活",
    # 電子次產業（原 20–27 整體後移 +4）
    "24": "半導體",
    "25": "電腦及週邊設備",
    "26": "光電業",
    "27": "通信網路業",
    "28": "電子零組件業",
    "29": "電子通路業",
    "30": "資訊服務業",
    "31": "其他電子業",
    # 其他
    "32": "文化創意業",
    "33": "農業科技業",
    "34": "電子商務",
    "80": "管理股票",
    "90": "存託憑證",
}


def fetch_sector_map(cache_path: Optional[str] = None) -> dict[str, str]:
    """Return a complete {symbol: sector} dict for all TWSE + TPEX stocks.

    If *cache_path* is given and the cached file is fresh (< 7 days old),
    returns the cached data without making network requests.
    """
    if cache_path and _cache_is_fresh(cache_path):
        loaded = _load_cache(cache_path)
        if loaded:
            logger.info("sector_data: loaded %d symbols from cache %s", len(loaded), cache_path)
            return loaded

    sector_map: dict[str, str] = {}

    twse = _fetch_twse()
    sector_map.update(twse)
    logger.info("sector_data: TWSE %d symbols fetched", len(twse))

    tpex = _fetch_tpex()
    sector_map.update(tpex)
    logger.info("sector_data: TPEX %d symbols fetched", len(tpex))

    if cache_path and sector_map:
        _save_cache(cache_path, sector_map)

    return sector_map


# ── TWSE ───────────────────────────────────────────────────────────────────


def _fetch_twse() -> dict[str, str]:
    try:
        rows = _get_json(TWSE_URL)
    except Exception as exc:
        logger.warning("sector_data: TWSE fetch failed: %s", exc)
        return {}

    result: dict[str, str] = {}
    for row in rows:
        code = str(row.get("公司代號", "")).strip()
        raw_sector = str(row.get("產業別", "")).strip()
        if not code or not raw_sector:
            continue
        # Map numeric code (e.g. "20") to human-readable name; keep raw if unknown
        sector = _TWSE_SECTOR_NAMES.get(raw_sector, raw_sector)
        result[code] = sector
    return result


# ── TPEX ───────────────────────────────────────────────────────────────────


def _fetch_tpex() -> dict[str, str]:
    try:
        rows = _get_json(TPEX_URL)
    except Exception as exc:
        logger.warning("sector_data: TPEX fetch failed: %s", exc)
        return {}

    result: dict[str, str] = {}
    for row in rows:
        code = str(
            row.get("SecuritiesCompanyCode")
            or row.get("公司代號")
            or row.get("股票代號")
            or ""
        ).strip()
        sector = str(
            row.get("IndustryType")
            or row.get("Industry")
            or row.get("產業別")
            or row.get("類別")
            or ""
        ).strip()
        if code and sector:
            result[code] = sector
    return result


# ── helpers ────────────────────────────────────────────────────────────────


def _get_json(url: str) -> list[dict]:
    req = _urllib.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with _urllib.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    # Some endpoints wrap in {"data": [...]}
    if isinstance(data, dict):
        for key in ("data", "Data", "result", "Result"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _cache_is_fresh(path: str) -> bool:
    try:
        return (time.time() - os.path.getmtime(path)) < SECTOR_CACHE_TTL_SECONDS
    except OSError:
        return False


def _load_cache(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(path: str, data: dict[str, str]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        logger.info("sector_data: saved %d symbols to %s", len(data), path)
    except Exception as exc:
        logger.warning("sector_data: failed to save cache: %s", exc)
