#!/opt/hermes/.venv/bin/python
"""MAI IDX Signal — orchestrator v3 with fundamentals.
Pipeline: data -> features -> financials -> rank(tech+fund) -> Claude -> chart
"""
import sys, json, importlib
sys.path.insert(0, "/opt/data")
import zeta_stockbit_data as zd
import zeta_features as zf
import zeta_llm as zl
import zeta_rank as zr
try:
    import zeta_chart as zc
except Exception:
    zc = None
import zeta_financials as zfin
try:
    import zeta_industry as zind
except Exception:
    zind = None

MODEL = "Test-Combo"

SYS = (
    "Kamu analis teknikal, bandarmologi, dan fundamental saham IDX. "
    "Diberi indikator teknikal, data smart-money (foreign flow, broker), dan rasio keuangan (PER, PBV, ROE, dll). "
    "Hasilkan sinyal trading objektif berbasis konfluensi semua faktor. "
    "JANGAN mengarang data yang tidak diberikan. Pakai level entry/support/TP/SL dari fitur bila tersedia. "
    "Output HANYA JSON valid:\n"
    '{"signal":"BUY|HOLD|SELL","confidence":0-100,"entry":<harga>,'
    '"target":<harga>,"stop_loss":<harga>,"horizon":"intraday|swing|posisi",'
    '"reasoning":"<2-3 kalimat Indonesia, sebut teknikal+fundamental kunci>",'
    '"key_flags":["<flag singkat>",...]}\n'
    "confidence cerminkan kekuatan konfluensi. Fundamental buruk (PER>50, ROE<5%, NI negatif) turunkan grade meski teknikal ok."
)


_INDEX_SYMBOLS = {"IHSG", "JCI", "LQ45", "IDX30"}

def analyze(symbol, model=MODEL, make_chart=False, with_fundamentals=True):
    is_index = symbol.upper() in _INDEX_SYMBOLS
    if is_index:
        data = zd.fetch_index(symbol)
        with_fundamentals = False
    else:
        data = zd.fetch_symbol(symbol)
    feats = zf.build_features(data)
    if feats.get("error"):
        return {"symbol": symbol, "error": feats["error"]}

    fin = None
    if with_fundamentals:
        try:
            fin = zfin.fetch_financials(symbol)
        except Exception as e:
            fin = None

    rank = zr.score(feats, fin)

    fin_txt = ""
    if fin:
        fin_txt = "\n\nRasio Keuangan:\n" + zfin.compact_inline(fin)

    user = (f"Saham {symbol}. Sumber data: {feats.get('source')}.\n"
            f"Indikator teknikal & bandarmologi:\n{json.dumps(feats, ensure_ascii=False)}"
            f"{fin_txt}\n"
            f"\nSkor kuantitatif internal: {json.dumps(rank, ensure_ascii=False)}\n\n"
            "Beri sinyal JSON sesuai format. Gunakan skor sebagai referensi, "
            "tapi keputusan final tetap berdasarkan konfluensi data.")
    try:
        sig = zl.chat_json([{"role": "system", "content": SYS},
                            {"role": "user", "content": user}],
                           model=model, max_tokens=1200)
    except Exception as e:
        return {"symbol": symbol, "error": f"llm: {str(e)[:150]}", "features": feats, "rank": rank}
    sig["symbol"] = symbol
    sig["_features"] = feats
    sig["_data_source"] = feats.get("source")
    sig["_rank"] = rank
    if fin:
        sig["_financials"] = fin
    if make_chart and zc:
        try:
            sig["_chart"] = zc.make_chart(symbol, data, feats, sig, fin=fin)
        except Exception as e:
            sig["_chart_error"] = str(e)[:160]
    elif make_chart and not zc:
        sig["_chart_error"] = "matplotlib not installed"
    return sig


_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}


def confidence_label(signal, confidence, composite=None):
    """Map signal + confidence (+ composite score) to Indonesian strength label."""
    c = confidence if isinstance(confidence, (int, float)) else 0
    comp = composite if isinstance(composite, (int, float)) else c
    strong = c >= 70 and comp >= 65
    weak = c < 55 or comp < 50
    sig = (signal or "").upper()
    if sig == "BUY":
        return "BUY KUAT" if strong else ("BUY LEMAH" if weak else "BUY MODERAT")
    if sig == "SELL":
        return "SELL KUAT" if strong else ("SELL LEMAH" if weak else "SELL MODERAT")
    if sig == "HOLD":
        return "HOLD NETRAL" if weak else "HOLD CONDONG"
    return sig or "n/a"


def format_signal(sig):
    if sig.get("error"):
        return f"*{sig['symbol']}* ⚠️ {sig['error']}"
    e = _EMOJI.get(sig.get("signal"), "⚪")
    f = sig.get("_features", {})
    r = sig.get("_rank", {})
    fin = sig.get("_financials")

    # ── helpers ──────────────────────────────────────────────────────────
    def _p(v):
        return f"{int(v):,}" if v and v == int(v) else f"{v:,.0f}" if v else "n/a"

    def _pct(v):
        return f"{v:.1f}%" if v is not None else "n/a"

    def _v(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "n/a"

    # ── scores ───────────────────────────────────────────────────────────
    tech_s = r.get("technical_score")
    fund_s = r.get("fundamental_score")
    comp_s = r.get("composite_score", r.get("total", 0))

    tech_bar = "█" * int((tech_s or 0) // 10) + "░" * (10 - int((tech_s or 0) // 10))
    fund_bar = "█" * int((fund_s or 0) // 10) + "░" * (10 - int((fund_s or 0) // 10)) if fund_s is not None else "n/a"

    # ── price levels ─────────────────────────────────────────────────────
    price = f.get("last_close") or sig.get("entry")
    chg   = f.get("change_pct")
    chg_txt = (f" ({'+' if chg >= 0 else ''}{chg:.1f}%)" if chg is not None else "")

    sup   = f.get("support")
    res   = f.get("resistance")
    tp1   = f.get("tp1") or sig.get("target")
    tp2   = f.get("tp2")
    sl    = f.get("stop_loss") or sig.get("stop_loss")
    entry_lo = f.get("entry_low") or sig.get("entry")
    entry_hi = f.get("entry_high")
    rrr   = f.get("risk_reward_tp1")
    f382  = f.get("fib_38_2")
    f500  = f.get("fib_50_0")
    f618  = f.get("fib_61_8")

    # ── bandar / smart money ──────────────────────────────────────────────
    ft = f.get("foreign_trend")
    nf = f.get("net_foreign_5d")
    nf_txt = ""
    if nf is not None:
        nf_txt = f" {nf/1e12:.2f}T" if abs(nf) >= 1e12 else f" {nf/1e9:.0f}B"
    bandar_icon = {"accum": "🟢", "distrib": "🔴", "neutral": "🟡"}.get(ft, "⚪")
    bandar_lbl = ft or "n/a"
    broker_txt = " | foreign broker aktif ✅" if f.get("foreign_broker_buying") else ""

    # ── trend regime label ────────────────────────────────────────────────────
    trend_regime = f.get("trend_regime", "")
    _trend_emoji = {"UPTREND": "📈", "DOWNTREND": "📉", "SIDEWAYS": "↔️"}
    trend_lbl = f" | {_trend_emoji.get(trend_regime,'')} D:{trend_regime}" if trend_regime else ""
    wk = f.get("weekly_trend")
    if wk:
        trend_lbl += f" {_trend_emoji.get(wk,'')} W:{wk}"

    # ── layout ────────────────────────────────────────────────────────────
    conf_lbl = confidence_label(sig.get("signal"), sig.get("confidence"), comp_s)
    lines = [
        f"{e} *{sig['symbol']}* — {sig.get('signal')} ({sig.get('confidence')}%) → *{conf_lbl}*{trend_lbl}",
        f"Grade: *{r.get('grade','?')} {r.get('rank_label','?')}* | Composite: *{comp_s}/100* | R/R: *{_v(rrr, 'x') if rrr else 'n/a'}*",
        "Legend: 🟢 lebih bagus dari benchmark | 🔴 lebih buruk | ⚪️ inline/dekat benchmark",
        "",
        "📈 *TECHNICAL* ({}/100)".format(tech_s if tech_s is not None else "n/a"),
        f"`Tech  [{tech_bar}] {tech_s}/100`",
    ]
    if fin is not None:
        lines.append("📊 *FUNDAMENTAL* ({}/100)".format(fund_s if fund_s is not None else "n/a"))
        lines.append(f"`Fund  [{fund_bar}] {fund_s}/100`")
    lines += [
        "",
        f"💰 *Harga:* Rp {_p(price)}{chg_txt}  _[{f.get('price_source','?')}]_",
        f"🟩 Entry zona: Rp {_p(entry_lo)}{' – ' + _p(entry_hi) if entry_hi and entry_hi != entry_lo else ''}",
        f"🛡 Support: Rp {_p(sup)}   |   🚧 Resistance: Rp {_p(res)}",
        f"🎯 TP1: Rp {_p(tp1)}   |   🎯 TP2: Rp {_p(tp2)}",
        f"🔴 Stop Loss: Rp {_p(sl)}   |   R/R: {_v(rrr, 'x') if rrr else 'n/a'}",
    ]
    if f382 or f500 or f618:
        lines.append(
            f"📐 Fib: 38.2%=Rp {_p(f382)} | 50%=Rp {_p(f500)} | 61.8%=Rp {_p(f618)}"
        )

    # MA stack
    ma5v  = f.get("ma5_value")
    ma20v = f.get("ma20_value")
    ma50v = f.get("ma50_value")
    ma100v = f.get("ma100_value")
    ma200v = f.get("ma200_value")
    ma5s  = f.get("trend_vs_ma5")  or f.get("ma5")
    ma20s = f.get("trend_vs_ma20") or f.get("ma20")
    ma50s = f.get("trend_vs_ma50") or f.get("ma50")
    ma100s = f.get("trend_vs_ma100")
    ma200s = f.get("trend_vs_ma200")
    def _ma_icon(s): return "⬆" if s=="above" else "⬇" if s else "–"
    lines.append(
        f"📉 MA: 5={_p(ma5v)}{_ma_icon(ma5s)} | 20={_p(ma20v)}{_ma_icon(ma20s)} | 50={_p(ma50v)}{_ma_icon(ma50s)} | 100={_p(ma100v)}{_ma_icon(ma100s)} | 200={_p(ma200v)}{_ma_icon(ma200s)}"
    )
    lines.append(
        f"⚡ RSI: {_v(f.get('rsi14'))} | MACD hist: {_v(f.get('macd_hist'))} | Stoch: {_v(f.get('stoch_k'))}"
    )
    lines.append(
        f"{bandar_icon} Smart money: {bandar_lbl}{nf_txt}{broker_txt}"
    )

    # ── bandarmologi: top brokers ─────────────────────────────────────────
    def _bamt(a):
        if not a: return ""
        a = float(a)
        return f"{a/1e9:.1f}B" if abs(a) >= 1e9 else f"{a/1e6:.0f}M"
    tb = f.get("top_buyers") or []
    ts = f.get("top_sellers") or []
    if tb or ts:
        def _bk(b): return f"{b.get('code','?')}({b.get('type','')[:3]}) {_bamt(b.get('amount'))}"
        bias = f.get("broker_bias", "")
        fnet = f.get("broker_foreign_net_value")
        fnet_txt = f" | Asing net {_bamt(fnet)}" if fnet else ""
        lines.append("🏦 *Bandarmologi:*" + (f" bias *{bias}*{fnet_txt}" if bias else ""))
        if tb:
            lines.append("  Buy:  " + " · ".join(_bk(b) for b in tb[:5]))
        if ts:
            lines.append("  Sell: " + " · ".join(_bk(b) for b in ts[:5]))

    # Fundamental detail block
    if fin:
        rat = fin.get("ratios",{}); pnl = fin.get("pnl",{}); bs = fin.get("bs",{}); cf = fin.get("cf",{})
        # industry benchmark
        ind = zind.get(sig.get('symbol','')) if zind else {}
        ind_label = ind.get('label','') if ind else ''

        def _fi(metric, value, suffix='x'):
            """Format value with industry comparison."""
            if value is None:
                return 'n/a'
            val_str = f'{value:.2f}{suffix}'
            if not ind or not zind:
                return val_str
            iv = ind.get(metric)
            if iv is None:
                return val_str
            iv_str = f'{iv:.2f}{suffix}'
            v = zind.verdict(metric, value, iv)
            icon = '🟢' if ('murah' in v or 'di atas' in v) else '🔴' if ('mahal' in v or 'di bawah' in v) else '⚪'
            return f'{val_str} {icon} (Ind.={iv_str})'

        def _fipct(metric, value):
            return _fi(metric, value, suffix='%')

        # previous period helper
        prev = fin.get('prev', {})
        pp  = prev.get('pnl', {})
        pr2 = prev.get('ratios', {})

        def _delta(cur, prev_val, is_pct=False):
            """arrow + diff vs previous period."""
            if cur is None or prev_val is None:
                return ""
            d = cur - prev_val
            sign = "+" if d >= 0 else ""
            if is_pct:
                return f" ({'↑' if d>=0 else '↓'}{sign}{d:.1f}pp vs prev)"
            return f" ({'↑' if d>=0 else '↓'}{sign}{zfin.fmt_b(d)} vs prev)"

        # net margin TTM derived (NI/Rev calculated)
        nm_calc = rat.get('net_margin_ttm_calc_pct')  # current TTM derived
        nm_prev = pr2.get('net_margin_pct_calc')       # previous TTM derived

        lines += [
            "",
            f"📊 *Fundamental detail:*" + (f" _{ind_label}_" if ind_label else ""),
            "",
            "**Valuation**",
            "_Legend: 🟢 murah/baik vs industri | 🔴 mahal/buruk vs industri | ⚪️ inline_",
            f"PER {_fi('per_ttm', rat.get('per_ttm'))} | PBV {_fi('pbv', rat.get('pbv'))} | EV/EBITDA {_fi('ev_ebitda', rat.get('ev_ebitda'))}",
            f"Forward PE: {_v(rat.get('forward_pe'),'x')} | PEG: {_v(rat.get('peg'),'x')} | Div Yield: {_fipct('dividend_yield_pct', rat.get('dividend_yield_pct'))}",
            "",
            "**Profitability**",
            "_Legend: 🟢 di atas rata-rata industri | 🔴 di bawah | ⚪️ inline_",
            f"ROE {_fipct('roe_pct', rat.get('roe_pct'))} | ROA {_fipct('roa_pct', rat.get('roa_pct'))}",
            f"Net Margin {_fipct('net_margin_pct', rat.get('net_margin_pct'))}"
            + (f" | TTM calc {nm_calc:.1f}%{_delta(nm_calc, nm_prev, is_pct=True)}" if nm_calc else ""),
            "",
            "**P&L (TTM)**",
            "_Legend: ↑ tumbuh vs periode lalu | ↓ turun vs periode lalu_",
            (f"Rev: {zfin.fmt_b(pnl.get('revenue_ttm_b'))}"
             + (f" (prev ~{zfin.fmt_b(pp.get('revenue_ttm_b'))})" if pp.get('revenue_ttm_b') else "")
             + f" YoY {_pct(pnl.get('revenue_yoy_pct'))}"),
            (f"NI:  {zfin.fmt_b(pnl.get('net_income_ttm_b'))}"
             + (f" (prev ~{zfin.fmt_b(pp.get('net_income_ttm_b'))})" if pp.get('net_income_ttm_b') else "")
             + f" YoY {_pct(pnl.get('net_income_yoy_pct'))}"),
            "",
            "**Balance Sheet (Q)**",
            "_Legend: DER 🟢 <1x | CR 🟢 >1.5x — berlaku untuk non-bank_",
            f"Assets: {zfin.fmt_b(bs.get('total_assets_q_b'))} | Equity: {zfin.fmt_b(bs.get('total_equity_q_b'))} | Cash: {zfin.fmt_b(bs.get('cash_q_b'))}",
            f"DER: {_v(rat.get('der'))} | CR: {_v(rat.get('current_ratio'))} | Liabilities: {zfin.fmt_b(bs.get('total_liabilities_q_b'))}",
            "",
            "**Cash Flow (TTM)**",
            "_Legend: 🟢 OCF positif & FCF positif = sehat | 🔴 FCF negatif = hati-hati_",
            f"OCF: {zfin.fmt_b(cf.get('ocf_ttm_b'))} | CFI: {zfin.fmt_b(cf.get('cfi_ttm_b'))} | CFF: {zfin.fmt_b(cf.get('cff_ttm_b'))}",
            f"Capex: {zfin.fmt_b(cf.get('capex_ttm_b'))} | FCF: {zfin.fmt_b(cf.get('fcf_ttm_b'))}",
        ]

    # Score breakdown
    b = r.get("breakdown", {})
    tech_parts = []
    for k, label in [("technical_trend","Trend"),("technical_momentum","Momentum"),
                     ("technical_volume","Vol"),("technical_smart_money","Smart$"),
                     ("technical_risk_reward","R/R")]:
        if k in b: tech_parts.append(f"{label}:{b[k]}")
    fund_parts = []
    for k, label in [("fundamental_valuation","Val"),("fundamental_profitability","Prof"),
                     ("fundamental_growth","Growth"),("fundamental_balance","BS"),
                     ("fundamental_cashflow","CF"),("fundamental_dividend","Div")]:
        if k in b: fund_parts.append(f"{label}:{b[k]}")
    if tech_parts:
        lines.append("🔬 Tech breakdown: " + " | ".join(tech_parts))
    if fund_parts:
        lines.append("🔬 Fund breakdown: " + " | ".join(fund_parts))

    lines.append(f"_{sig.get('reasoning','')}_")
    if sig.get("key_flags"):
        lines.append("Flags: " + ", ".join(sig["key_flags"][:5]))
    if sig.get("_chart"):
        lines.append(f"Chart: {sig['_chart']}")
    lines.append(f"Horizon: {sig.get('horizon','n/a')}")
    return "\n".join(lines)


def run_watchlist(symbols, model=MODEL, make_chart=True):
    out = []
    for s in symbols:
        sys.stderr.write(f"[analyzing {s}]\n")
        out.append(analyze(s, model=model, make_chart=make_chart))
    return out


def rank_table(sigs):
    """Compact ranking summary sorted by composite score desc."""
    def key(s):
        return (s.get("_rank", {}) or {}).get("composite_score", -1)
    rows = sorted([s for s in sigs if not s.get("error")], key=key, reverse=True)
    errs = [s for s in sigs if s.get("error")]
    lines = ["*WATCHLIST RANKING*", "`#  SYM    SIG   CONF  COMP  GRD  PRICE`"]
    for i, s in enumerate(rows, 1):
        r = s.get("_rank", {}) or {}
        f = s.get("_features", {}) or {}
        price = f.get("realtime_price") or f.get("last_close")
        lines.append(
            f"`{i:<2} {s.get('symbol',''):<6} {str(s.get('signal','?')):<5} "
            f"{str(s.get('confidence','?')):>4}  {str(r.get('composite_score','?')):>4}  "
            f"{str(r.get('grade','?')):<3}  {price if price else 'n/a'}`"
        )
    for s in errs:
        lines.append(f"`-- {s.get('symbol',''):<6} ERROR: {s.get('error','')[:40]}`")
    return "\n".join(lines)


if __name__ == "__main__":
    argv = sys.argv[1:]
    watchlist_mode = False
    syms = []
    rest = []
    for a in argv:
        if a in ("--watchlist", "-w"):
            watchlist_mode = True
        elif a.startswith("--watchlist="):
            watchlist_mode = True
            rest.append(a.split("=", 1)[1])
        else:
            rest.append(a)
    for a in rest:
        syms += [x.strip().upper() for x in a.split(",") if x.strip()]
    syms = syms or ["BBRI"]

    if watchlist_mode:
        # Concise ranking: skip per-symbol charts for speed.
        sigs = run_watchlist(syms, make_chart=False)
        print(rank_table(sigs))
    else:
        sigs = run_watchlist(syms)
        print("\n\n".join(format_signal(s) for s in sigs))
