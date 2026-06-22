"""Phase 5.4: per-symbol news fetch for the AI sentiment layer.

Pulls recent Indonesian-language headlines for an IDX issuer from the
free Google News RSS endpoint (no API key). This feeds Claude *orthogonal*
information — corporate actions, earnings, M&A, lawsuits — that price
indicators cannot see (PHASE5_RESEARCH.md §3, rec #1).

Design notes:
  * Free + keyless: Google News RSS, locale id-ID. One HTTP GET per symbol.
  * Cheap: only called for the top-N candidates, behind a per-symbol cache.
  * Fails open: any error -> empty list, the scan never breaks on news.
  * Blocking httpx.get is fine — caller runs it in an executor.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional
from urllib.parse import quote
from xml.etree import ElementTree as ET

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_GOOGLE_NEWS = (
    "https://news.google.com/rss/search?q={q}&hl=id&gl=ID&ceid=ID:id"
)

# symbol -> (timestamp, items)
_cache: Dict[str, tuple] = {}


def _company_query(symbol: str) -> str:
    """Build a news query for an IDX ticker.

    We search the bare 4-letter code plus 'saham' (Indonesian for 'stock')
    to bias toward market coverage and away from unrelated acronyms.
    """
    code = symbol.replace(".JK", "").strip().upper()
    return quote(f'"{code}" saham BEI')


def _parse_rss(xml_text: str, max_items: int, lookback_days: int) -> List[Dict]:
    items: List[Dict] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        logger.debug("news rss parse error: %s", exc)
        return items

    cutoff = time.time() - lookback_days * 86400
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_el = item.find("{http://news.google.com}source") or item.find("source")
        source = (source_el.text.strip() if source_el is not None and source_el.text else "")
        if not title:
            continue
        ts = _parse_pubdate(pub)
        if ts and ts < cutoff:
            continue
        items.append({"title": title, "date": pub, "source": source, "link": link})
        if len(items) >= max_items:
            break
    return items


def _parse_pubdate(pub: str) -> Optional[float]:
    if not pub:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            import datetime as _dt
            return _dt.datetime.strptime(pub, fmt).timestamp()
        except Exception:
            continue
    return None


def fetch_news(symbol: str, use_cache: bool = True) -> List[Dict]:
    """Fetch recent headlines for a symbol. Returns [] on any failure."""
    now = time.time()
    if use_cache:
        cached = _cache.get(symbol)
        if cached and now - cached[0] < settings.NEWS_CACHE_TTL:
            return cached[1]

    url = _GOOGLE_NEWS.format(q=_company_query(symbol))
    try:
        resp = httpx.get(url, timeout=10.0, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (MAI-IDX-Signal)"})
        resp.raise_for_status()
        items = _parse_rss(resp.text, settings.NEWS_MAX_ITEMS,
                           settings.NEWS_LOOKBACK_DAYS)
    except Exception as exc:
        logger.debug("fetch_news failed for %s: %s", symbol, exc)
        items = []

    _cache[symbol] = (now, items)
    return items
