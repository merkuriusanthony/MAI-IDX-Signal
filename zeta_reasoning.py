#!/usr/bin/env python3
"""Zeta IDX — AI Reasoning engine.
Generates contextual, evidence-backed answers to follow-up questions like
"kenapa?", "worth invest?", "layak gak?", etc.

Model: cc/claude-opus-4-8 via 9router.
"""
import sys, json, math
sys.path.insert(0, __import__('os').environ.get('ZETA_ROOT', '/opt/data'))
import zeta_stockbit_data as zd
import zeta_features as zf
import zeta_signal as zs
import zeta_financials as zfin
import zeta_llm as llm


# ── Data helpers ─────────────────────────────────────────────────────────────

def _safe(v, fmt='{:.1f}', fallback='N/A'):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return fallback
        return fmt.format(float(v))
    except Exception:
        return str(v) if v is not None else fallback


def _trend_emoji(trend):
    return {'above': '✅', 'below': '❌'}.get(trend, '⚪')


def build_evidence_block(symbol: str) -> dict:
    """Fetch all data, return structured evidence dict for LLM prompt."""
    data = zd.fetch_symbol(symbol)
    feats = zf.build_features(data)
    sig = zs.analyze(symbol, make_chart=False)

    fin = None
    try:
        fin = zfin.fetch_financials(symbol)
    except Exception:
        pass

    ratios = (fin or {}).get('ratios', {})
    pnl    = (fin or {}).get('pnl', {})
    bs     = (fin or {}).get('bs', {})
    cf     = (fin or {}).get('cf', {})

    return {
        'symbol': symbol,
        'signal': sig.get('signal', 'N/A'),
        'confidence': sig.get('confidence', 0),
        'horizon': sig.get('horizon', 'swing'),
        'reasoning_base': sig.get('reasoning', ''),
        'key_flags': sig.get('key_flags', []),

        # price / technical
        'last_close': feats.get('last_close'),
        'change_pct': feats.get('change_pct'),
        'ma5': feats.get('ma5_value'),
        'ma20': feats.get('ma20_value'),
        'ma50': feats.get('ma50_value'),
        'ma100': feats.get('ma100_value'),
        'ma200': feats.get('ma200_value'),
        'rsi14': feats.get('rsi14'),
        'macd_hist': feats.get('macd_hist'),
        'stoch_k': feats.get('stoch_k'),
        'vol_ratio_20d': feats.get('vol_ratio_20d'),
        'trend_regime': feats.get('trend_regime'),
        'trend_vs_ma50': feats.get('trend_vs_ma50'),
        'trend_vs_ma100': feats.get('trend_vs_ma100'),
        'trend_vs_ma200': feats.get('trend_vs_ma200'),
        'support': feats.get('support'),
        'resistance': feats.get('resistance'),
        'entry_low': feats.get('entry_low'),
        'entry_high': feats.get('entry_high'),
        'tp1': feats.get('tp1'),
        'stop_loss': feats.get('stop_loss'),
        'risk_reward_tp1': feats.get('risk_reward_tp1'),

        # bandarmologi
        'net_foreign_5d': feats.get('net_foreign_5d'),
        'foreign_trend': feats.get('foreign_trend'),
        'top_buyers': feats.get('top_buyers', []),
        'foreign_broker_buying': feats.get('foreign_broker_buying'),

        # valuasi
        'per_ttm': ratios.get('per_ttm'),
        'pbv': ratios.get('pbv'),
        'roe_pct': ratios.get('roe_pct'),
        'roa_pct': ratios.get('roa_pct'),
        'net_margin_pct': ratios.get('net_margin_pct'),
        'gross_margin_pct': ratios.get('gross_margin_pct'),
        'der': ratios.get('der'),
        'current_ratio': ratios.get('current_ratio'),
        'piotroski': ratios.get('piotroski'),
        'rs_rating_pct': ratios.get('rs_rating_pct'),

        # P&L
        'revenue_ttm_b': pnl.get('revenue_ttm_b'),
        'net_income_ttm_b': pnl.get('net_income_ttm_b'),
        'revenue_yoy_pct': pnl.get('revenue_yoy_pct'),
        'net_income_yoy_pct': pnl.get('net_income_yoy_pct'),

        # Balance sheet
        'cash_b': bs.get('cash_q_b'),
        'total_assets_b': bs.get('total_assets_q_b'),
        'total_equity_b': bs.get('total_equity_q_b'),
        'financial_leverage': bs.get('financial_leverage'),

        # Cashflow
        'ocf_ttm_b': cf.get('ocf_ttm_b'),
        'fcf_ttm_b': cf.get('fcf_ttm_b'),
        'capex_ttm_b': cf.get('capex_ttm_b'),
    }


def _format_evidence_for_prompt(ev: dict) -> str:
    """Serialize evidence into a structured text block for the LLM."""
    s = _safe
    lines = [
        f"SYMBOL: {ev['symbol']}",
        f"SIGNAL (rule-based): {ev['signal']} | Confidence: {ev['confidence']}% | Horizon: {ev['horizon']}",
        f"KEY FLAGS: {', '.join(ev['key_flags']) or 'none'}",
        "",
        "=== HARGA & TEKNIKAL ===",
        f"Last Close  : {s(ev['last_close'], '{:.0f}')} | Change: {s(ev['change_pct'], '{:+.1f}')}%",
        f"MA5/20/50   : {s(ev['ma5'],'{:.0f}')} / {s(ev['ma20'],'{:.0f}')} / {s(ev['ma50'],'{:.0f}')}",
        f"MA100/200   : {s(ev['ma100'],'{:.0f}')} / {s(ev['ma200'],'{:.0f}')}",
        f"Trend regime: {ev.get('trend_regime','N/A')}",
        f"vs MA50/100/200: {ev.get('trend_vs_ma50','?')}/{ev.get('trend_vs_ma100','?')}/{ev.get('trend_vs_ma200','?')}",
        f"RSI14       : {s(ev['rsi14'])} | MACD hist: {s(ev['macd_hist'])} | Stoch-K: {s(ev['stoch_k'])}",
        f"Vol ratio 20d: {s(ev['vol_ratio_20d'],'{}x')}",
        f"Support/Resist: {s(ev['support'],'{:.0f}')} / {s(ev['resistance'],'{:.0f}')}",
        f"Entry zone  : {s(ev['entry_low'],'{:.0f}')} - {s(ev['entry_high'],'{:.0f}')}",
        f"TP1 / SL    : {s(ev['tp1'],'{:.0f}')} / {s(ev['stop_loss'],'{:.0f}')}  (RR: {s(ev['risk_reward_tp1'],'{}x')})",
        "",
        "=== BANDARMOLOGI ===",
        f"Net Foreign 5d: {s(ev.get('net_foreign_5d'), '{:.1f}', 'N/A')} (raw IDR)",
        f"Foreign trend : {ev.get('foreign_trend','N/A')}",
        f"Top buyers    : {', '.join(b.get('code','?')+' ('+b.get('type','?')+')' for b in ev.get('top_buyers',[])[:5]) or 'N/A'}",
        f"Foreign broker buying: {ev.get('foreign_broker_buying','N/A')}",
        "",
        "=== VALUASI ===",
        f"PER TTM : {s(ev['per_ttm'],'{}x')} | PBV: {s(ev['pbv'],'{}x')}",
        f"ROE     : {s(ev['roe_pct'],'{:.1f}')}% | ROA: {s(ev['roa_pct'],'{:.1f}')}%",
        f"Net margin: {s(ev['net_margin_pct'],'{:.1f}')}% | Gross margin: {s(ev['gross_margin_pct'],'{:.1f}')}%",
        f"DER     : {s(ev['der'])} | Current ratio: {s(ev['current_ratio'])}",
        f"Piotroski F: {s(ev['piotroski'],'{}')}/9 | RS Rating: {s(ev['rs_rating_pct'],'{:.0f}')}th %ile",
        "",
        "=== P&L (TTM, IDR Miliar) ===",
        f"Revenue     : {s(ev['revenue_ttm_b'],'{:.1f}')}B  YoY: {s(ev['revenue_yoy_pct'],'{:+.1f}')}%",
        f"Net Income  : {s(ev['net_income_ttm_b'],'{:.1f}')}B  YoY: {s(ev['net_income_yoy_pct'],'{:+.1f}')}%",
        "",
        "=== BALANCE SHEET ===",
        f"Cash: {s(ev['cash_b'],'{:.1f}')}B | Total Assets: {s(ev['total_assets_b'],'{:.1f}')}B",
        f"Equity: {s(ev['total_equity_b'],'{:.1f}')}B | Leverage: {s(ev['financial_leverage'],'{:.2f}')}x",
        "",
        "=== CASHFLOW (TTM) ===",
        f"OCF: {s(ev['ocf_ttm_b'],'{:.1f}')}B | FCF: {s(ev['fcf_ttm_b'],'{:.1f}')}B | Capex: {s(ev['capex_ttm_b'],'{:.1f}')}B",
        "",
        "=== REASONING (rule-based engine) ===",
        ev.get('reasoning_base', ''),
    ]
    return '\n'.join(lines)


# ── LLM prompt ───────────────────────────────────────────────────────────────

_SYSTEM = """\
Kamu adalah Zeta AI, analis saham IDX profesional yang menggabungkan analisa teknikal, \
fundamental, dan bandarmologi. Jawab dengan bahasa Indonesia yang ringkas, langsung, \
dan evidence-based. Jangan terlalu panjang — maksimal ~350 kata. \
Gunakan emoji secukupnya untuk readability. \
Format: heading bold dengan **, list item dengan •. \
Jangan ada table, cukup bullet list per section.\
"""

def ask_reasoning(symbol: str, question: str, evidence: dict | None = None) -> str:
    """Generate AI reasoning for a follow-up question about a symbol.
    
    Args:
        symbol: IDX ticker e.g. 'BUVA'
        question: user's follow-up question
        evidence: pre-fetched evidence dict (skip re-fetch if provided)
    
    Returns:
        Formatted Telegram-ready Markdown text
    """
    if evidence is None:
        evidence = build_evidence_block(symbol)

    ev_text = _format_evidence_for_prompt(evidence)

    prompt = f"""\
User bertanya tentang saham {symbol}: "{question}"

Berikut data lengkap {symbol}:
{ev_text}

Jawab pertanyaan user secara spesifik berdasarkan data di atas. \
Sertakan evidence konkret (angka). \
Tutup dengan decision/rekomendasi actionable yang jelas (BUY/HOLD/AVOID/WAIT + kondisi entry jika ada).\
"""

    messages = [
        {'role': 'system', 'content': _SYSTEM},
        {'role': 'user', 'content': prompt},
    ]

    try:
        text = llm.chat(messages, model='Test-Combo', max_tokens=1200, timeout=90)
        return f"🧠 *Analisa AI — {symbol}*\n\n{text}"
    except Exception as e:
        # Fallback: rule-based summary
        return _fallback_reasoning(symbol, evidence, str(e))


def _fallback_reasoning(symbol: str, ev: dict, err: str) -> str:
    """Rule-based reasoning if LLM fails."""
    s = _safe
    sig = ev.get('signal', 'N/A')
    conf = ev.get('confidence', 0)
    flags = ev.get('key_flags', [])
    regime = ev.get('trend_regime', 'N/A')
    rsi = ev.get('rsi14')
    per = ev.get('per_ttm')
    pbv = ev.get('pbv')
    roe = ev.get('roe_pct')
    ni_yoy = ev.get('net_income_yoy_pct')
    ft = ev.get('foreign_trend', 'N/A')
    rr = ev.get('risk_reward_tp1')

    lines = [
        f"🧠 *Analisa — {symbol}* _(AI fallback)_\n",
        f"**Signal:** {sig} ({conf}% confidence)",
        f"**Trend Regime:** {regime}",
        f"\n**📊 Teknikal:**",
        f"• RSI14: {s(rsi)} {'(overbought ⚠️)' if rsi and float(rsi) > 70 else '(oversold 💡)' if rsi and float(rsi) < 30 else ''}",
        f"• vs MA50/100/200: {ev.get('trend_vs_ma50','?')}/{ev.get('trend_vs_ma100','?')}/{ev.get('trend_vs_ma200','?')}",
        f"• Support/Resist: {s(ev.get('support'),'{:.0f}')} / {s(ev.get('resistance'),'{:.0f}')}",
        f"• Risk-Reward TP1: {s(rr,'{}x')}",
        f"\n**💹 Valuasi:**",
        f"• PER TTM: {s(per,'{}x')} | PBV: {s(pbv,'{}x')}",
        f"• ROE: {s(roe,'{:.1f}')}% | NI YoY: {s(ni_yoy,'{:+.1f}')}%",
        f"\n**🏦 Bandarmologi:**",
        f"• Foreign trend: {ft}",
        f"\n**⚑ Key Flags:**",
    ]
    for fl in flags:
        lines.append(f"• {fl}")
    lines.append(f"\n_(LLM unavailable: {err[:80]})_")
    return '\n'.join(lines)


if __name__ == '__main__':
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else 'BUVA'
    q   = sys.argv[2] if len(sys.argv) > 2 else 'Worth invest gak?'
    print(ask_reasoning(sym, q))
