"""Phase 5.4: Claude as a real analyst (not a text formatter).

PHASE5_RESEARCH.md §3 diagnosis: today Claude is handed the finished
verdict and asked to narrate it — net alpha zero. This module makes Claude's
judgment *count* in two ways:

  1. News/filing sentiment (rec #1): feed recent IDX headlines + the
     technical context to Claude; it classifies materiality, directional
     sentiment, and event type. This is orthogonal to price indicators.

  2. Acted-upon verdict (rec #4): Claude returns verdict ∈
     {valid, caution, reject}. ``apply_ai_gate`` turns a ``reject`` (or a
     materially-negative news event on a BUY) into a downgrade — the AI can
     now veto a deterministic BUY, and the reason is surfaced.

Everything fails open: no token, API error, or unparseable reply -> the
deterministic action stands unchanged.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)

ANALYST_SYSTEM = (
    "Anda analis ekuitas Bursa Efek Indonesia (BEI). Tugas: menilai dampak "
    "berita/aksi korporasi terhadap sebuah sinyal teknikal yang SUDAH dihitung.\n"
    "ATURAN:\n"
    "1. Gunakan HANYA berita & data yang diberikan. JANGAN mengarang.\n"
    "2. JANGAN mengubah angka entry/TP/SL.\n"
    "3. Nilai materialitas & arah berita secara independen dari sinyal teknikal.\n"
    "4. Balas HANYA JSON valid sesuai skema. Tanpa teks lain.\n"
)

ANALYST_SCHEMA = """{
  "verdict": "valid" | "caution" | "reject",
  "news_sentiment": "positive" | "neutral" | "negative" | "none",
  "event_type": "earnings" | "ma" | "rights_issue" | "dividend" | "lawsuit" | "regulatory" | "other" | "none",
  "materiality": "high" | "medium" | "low" | "none",
  "summary_id": string (max 2 kalimat Bahasa Indonesia),
  "key_drivers": [string] (max 4),
  "risks": [string] (max 4),
  "no_trade_reason": string | null
}"""


def build_analyst_prompt(
    symbol: str,
    score_dict: Dict,
    indicators: Dict,
    news: List[Dict],
    news_classification: Optional[Dict] = None,
) -> str:
    """Prompt Claude to judge a signal in light of recent news."""
    news_lines = [
        {"title": n.get("title"), "date": n.get("date"), "source": n.get("source")}
        for n in (news or [])
    ]
    payload = {
        "symbol": symbol,
        "technical": {
            "score": score_dict.get("score"),
            "action": score_dict.get("action", score_dict.get("label")),
            "reason_codes": score_dict.get("reason_codes", []),
            "close": indicators.get("close"),
            "rsi": indicators.get("rsi"),
            "ma20": indicators.get("ma20"),
            "ma50": indicators.get("ma50"),
            "ma200": indicators.get("ma200"),
            "macd_hist": indicators.get("macd_hist"),
            "atr_pct": indicators.get("atr_pct"),
        },
        "recent_news": news_lines or "tidak ada berita relevan",
    }
    if news_classification:
        payload["news_classification"] = news_classification
    return (
        f"{ANALYST_SYSTEM}\n"
        f"Skema respons:\n{ANALYST_SCHEMA}\n\n"
        f"Data:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Tentukan verdict berdasarkan keselarasan sinyal teknikal dengan "
        "berita. Jika ada berita NEGATIF material (mis. rights issue dilutif, "
        "gugatan, laba anjlok) pada sinyal BUY, beri verdict 'reject' atau "
        "'caution'. Output JSON saja."
    )


NEWS_CLASSIFY_SYSTEM = (
    "Anda asisten riset BEI. Ringkas & klasifikasi berita mentah untuk satu "
    "emiten. JANGAN beri rekomendasi beli/jual — hanya fakta & klasifikasi. "
    "Balas HANYA JSON valid.\n"
)

NEWS_CLASSIFY_SCHEMA = """{
  "items": [
    {"headline_id": string (ringkas 1 kalimat),
     "event_type": "earnings"|"ma"|"rights_issue"|"dividend"|"lawsuit"|"regulatory"|"other"|"none",
     "sentiment": "positive"|"neutral"|"negative",
     "materiality": "high"|"medium"|"low"}
  ],
  "aggregate_sentiment": "positive"|"neutral"|"negative"|"none",
  "max_materiality": "high"|"medium"|"low"|"none"
}"""


def build_news_classify_prompt(symbol: str, news: List[Dict]) -> str:
    """Haiku stage: cheap per-symbol news classification (no decision)."""
    raw = [{"title": n.get("title"), "date": n.get("date"), "source": n.get("source")}
           for n in (news or [])]
    return (
        f"{NEWS_CLASSIFY_SYSTEM}\n"
        f"Skema:\n{NEWS_CLASSIFY_SCHEMA}\n\n"
        f"Emiten: {symbol}\n"
        f"Berita mentah:\n{json.dumps(raw, ensure_ascii=False, indent=2)}\n\n"
        "Klasifikasi tiap berita lalu agregasi. Output JSON saja."
    )


async def classify_news(symbol: str, news: List[Dict]) -> Dict:
    """Haiku stage. Returns classification dict (or fallback)."""
    from app.ai.claude_client import call_claude

    if not news:
        return {"items": [], "aggregate_sentiment": "none", "max_materiality": "none"}
    prompt = build_news_classify_prompt(symbol, news)
    return await call_claude(prompt, model=settings.CLAUDE_HAIKU_MODEL, max_tokens=800)


async def analyze_signal(
    symbol: str,
    score_dict: Dict,
    indicators: Dict,
    news: Optional[List[Dict]] = None,
) -> Dict:
    """Two-stage AI analyst.

    Stage 1 (HAIKU): cheap per-symbol news classification fan-out.
    Stage 2 (OPUS):  high-stakes decision — verdict + final analysis,
                     fed the pre-classified news. Decisions MUST use opus.

    Returns the parsed decision dict (or deterministic fallback).
    """
    from app.ai.claude_client import call_claude

    # Stage 1 — haiku classifies the raw headlines (orthogonal signal prep).
    news_class: Dict = {}
    if news:
        try:
            news_class = await classify_news(symbol, news)
        except Exception:
            news_class = {}

    # Stage 2 — opus makes the actual call, given technicals + classified news.
    prompt = build_analyst_prompt(symbol, score_dict, indicators, news or [],
                                  news_classification=news_class)
    result = await call_claude(prompt, model=settings.CLAUDE_DECISION_MODEL,
                               max_tokens=1024)
    if isinstance(result, dict) and not result.get("_fallback"):
        # surface the haiku aggregate for transparency / gate fallbacks
        result.setdefault("news_sentiment",
                          news_class.get("aggregate_sentiment", "none"))
        result.setdefault("materiality",
                          news_class.get("max_materiality", "none"))
    return result


# ---------------------------------------------------------------------------
# Acted-upon gate — the AI verdict actually moves the action
# ---------------------------------------------------------------------------

def apply_ai_gate(action: str, ai: Dict) -> Tuple[str, bool, str]:
    """Let Claude's verdict downgrade a BUY.

    Rules (only BUY is ever suppressed; nothing is ever upgraded):
      * verdict == reject               -> BUY downgraded to WATCH
      * verdict == caution AND news is
        negative & material (high/med)  -> BUY downgraded to WATCH
      * negative+high materiality news
        even if verdict missing         -> BUY downgraded to WATCH

    Fails open: fallback responses (``_fallback``) never gate.
    Returns (new_action, gated, note).
    """
    if not ai or ai.get("_fallback"):
        return action, False, ""
    if action != "BUY":
        return action, False, ""

    if not settings.AI_VERDICT_ENABLED:
        return action, False, ""

    verdict = (ai.get("verdict") or "").lower()
    sentiment = (ai.get("news_sentiment") or "").lower()
    materiality = (ai.get("materiality") or "").lower()
    reason = ai.get("no_trade_reason") or ai.get("summary_id") or ""

    negative_material = sentiment == "negative" and materiality in ("high", "medium")

    if verdict == "reject":
        return "WATCH", True, f"BUY → WATCH (AI reject): {reason}".strip()
    if verdict == "caution" and negative_material:
        return "WATCH", True, f"BUY → WATCH (AI caution + berita negatif): {reason}".strip()
    if negative_material and materiality == "high":
        return "WATCH", True, f"BUY → WATCH (berita negatif material): {reason}".strip()

    return action, False, ""
