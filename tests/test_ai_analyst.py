"""Tests for Phase 5.4 AI analyst layer: news fetch + acted-upon verdict gate."""
import app.ai.news as news_mod
from app.ai.analyst import apply_ai_gate, build_analyst_prompt
from app.config import settings


# --- AI verdict gate (the core "make the AI count" behavior) ---------------

def _ai(verdict="valid", sentiment="neutral", materiality="low", fallback=False):
    d = {
        "verdict": verdict,
        "news_sentiment": sentiment,
        "materiality": materiality,
        "no_trade_reason": "test reason",
    }
    if fallback:
        d["_fallback"] = True
    return d


def test_reject_downgrades_buy():
    action, gated, note = apply_ai_gate("BUY", _ai(verdict="reject"))
    assert action == "WATCH"
    assert gated
    assert "reject" in note.lower()


def test_caution_plus_negative_material_downgrades_buy():
    ai = _ai(verdict="caution", sentiment="negative", materiality="high")
    action, gated, _ = apply_ai_gate("BUY", ai)
    assert action == "WATCH" and gated


def test_caution_alone_does_not_downgrade():
    ai = _ai(verdict="caution", sentiment="neutral", materiality="low")
    action, gated, _ = apply_ai_gate("BUY", ai)
    assert action == "BUY" and not gated


def test_negative_high_materiality_downgrades_even_without_reject():
    ai = _ai(verdict="valid", sentiment="negative", materiality="high")
    action, gated, _ = apply_ai_gate("BUY", ai)
    assert action == "WATCH" and gated


def test_valid_signal_unchanged():
    action, gated, _ = apply_ai_gate("BUY", _ai(verdict="valid"))
    assert action == "BUY" and not gated


def test_gate_only_affects_buy():
    for act in ("WATCH", "HOLD", "AVOID"):
        action, gated, _ = apply_ai_gate(act, _ai(verdict="reject"))
        assert action == act and not gated


def test_fallback_never_gates():
    ai = _ai(verdict="reject", fallback=True)
    action, gated, _ = apply_ai_gate("BUY", ai)
    assert action == "BUY" and not gated


def test_gate_respects_disable_flag(monkeypatch):
    monkeypatch.setattr(settings, "AI_VERDICT_ENABLED", False)
    action, gated, _ = apply_ai_gate("BUY", _ai(verdict="reject"))
    assert action == "BUY" and not gated


# --- prompt construction ---------------------------------------------------

def test_analyst_prompt_includes_news_and_schema():
    news = [{"title": "Emiten X rights issue dilutif", "date": "x", "source": "y"}]
    score_dict = {"score": 70, "action": "BUY", "reason_codes": ["BREAKOUT_20D"]}
    prompt = build_analyst_prompt("XXXX", score_dict, {"close": 1000, "rsi": 65}, news)
    assert "verdict" in prompt
    assert "rights issue" in prompt
    assert "XXXX" in prompt


def test_analyst_prompt_handles_no_news():
    prompt = build_analyst_prompt("YYYY", {"score": 60, "action": "WATCH"}, {}, [])
    assert "tidak ada berita relevan" in prompt


# --- news RSS parsing (no network) -----------------------------------------

_SAMPLE_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Saham AAAA naik 5%</title>
    <pubDate>Mon, 16 Jun 2025 10:00:00 GMT</pubDate>
    <link>http://x/1</link></item>
  <item><title>AAAA bagikan dividen</title>
    <pubDate>Tue, 17 Jun 2025 09:00:00 GMT</pubDate>
    <link>http://x/2</link></item>
</channel></rss>"""


def test_parse_rss_extracts_items():
    items = news_mod._parse_rss(_SAMPLE_RSS, max_items=10, lookback_days=100000)
    assert len(items) == 2
    assert items[0]["title"].startswith("Saham AAAA")


def test_parse_rss_respects_max_items():
    items = news_mod._parse_rss(_SAMPLE_RSS, max_items=1, lookback_days=100000)
    assert len(items) == 1


def test_parse_rss_bad_xml_returns_empty():
    assert news_mod._parse_rss("<<not xml", max_items=5, lookback_days=7) == []


def test_company_query_strips_suffix():
    q = news_mod._company_query("BBCA.JK")
    assert "BBCA" in q


# --- two-stage model routing (haiku classify -> opus decision) -------------

def test_news_classify_prompt_has_schema():
    from app.ai.analyst import build_news_classify_prompt
    news = [{"title": "BBCA rights issue", "date": "x", "source": "y"}]
    p = build_news_classify_prompt("BBCA", news)
    assert "aggregate_sentiment" in p
    assert "rights issue" in p
    assert "BBCA" in p


def test_analyst_prompt_includes_classification():
    score_dict = {"score": 70, "action": "BUY"}
    cls = {"aggregate_sentiment": "negative", "max_materiality": "high"}
    p = build_analyst_prompt("XXXX", score_dict, {"close": 1}, [], news_classification=cls)
    assert "news_classification" in p
    assert "negative" in p
