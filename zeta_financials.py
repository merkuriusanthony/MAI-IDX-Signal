#!/usr/bin/env python3
"""MAI IDX — Stockbit Findata financial ratios + mini statements.
Source: https://exodus.stockbit.com/keystats/ratio/v1/{SYMBOL}
Auth: Stockbit bearer via /opt/data/stockbit_token.py
"""
import sys, os, json, urllib.request, re, time, threading
sys.path.insert(0, __import__('os').environ.get('ZETA_ROOT', '/opt/data'))
import stockbit_token

BASE = 'https://exodus.stockbit.com'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36'

# Fundamentals change slowly (quarterly); cache ~1h. NEVER cache realtime price here.
CACHE_PATH = os.environ.get('ZETA_CACHE_DIR', os.environ.get('ZETA_ROOT', '/opt/data') + '/cache') + '/zeta_financials_cache.json'
CACHE_TTL = 3600  # seconds

_CACHE_LOCK = threading.Lock()
_RATE_SEM = threading.Semaphore(1)  # keystats endpoint: serialize all calls
_BURST_LOCK = threading.Lock()
_BURST_STATE = {'count': 0, 'window_start': 0.0}
_BURST_SIZE = 3         # observed: exactly 3 requests succeed per window, then empty-body
_BURST_COOLDOWN = 34.0  # observed: 30s recovers the burst quota; +margin for timing drift


def _cache_load():
    try:
        with open(CACHE_PATH) as fh:
            return json.load(fh)
    except Exception:
        return {}


def _cache_save(cache):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        tmp = f"{CACHE_PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, 'w') as fh:
            json.dump(cache, fh, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)
    except Exception as e:
        sys.stderr.write(f'[fin cache save failed: {str(e)[:80]}]\n')

def _headers():
    return {
        'Authorization': 'Bearer ' + stockbit_token.get_access(margin=300),
        'User-Agent': UA,
        'Accept': 'application/json',
        'Origin': 'https://stockbit.com',
        'Referer': 'https://stockbit.com/',
    }

def _parse_num(v):
    if v is None: return None
    if isinstance(v, (int,float)): return float(v)
    s = str(v).strip()
    if not s or s == '-': return None
    neg = s.startswith('(') and s.endswith(')')
    s = s.strip('()').replace(',', '').replace('%','').strip()
    mult = 1.0
    # Stockbit already reports B for billion IDR; preserve as billion unit
    s = re.sub(r'\s*B$', '', s, flags=re.I).strip()
    try:
        x = float(s) * mult
    except Exception:
        return None
    return -x if neg else x

def _flatten(raw):
    items = {}
    sections = {}
    for sec in raw.get('data',{}).get('closure_fin_items_results',[]) or []:
        name = sec.get('keystats_name') or 'Unknown'
        sections[name] = {}
        for it in sec.get('fin_name_results',[]) or []:
            f = it.get('fitem') or {}
            k, v = f.get('name'), f.get('value')
            if not k: continue
            items[k] = v
            sections[name][k] = v
    return items, sections

def fetch_financials(symbol, use_cache=True):
    """Cached fundamentals (~1h TTL). Safe fallback to live fetch on cache miss/corruption."""
    sym = symbol.upper().replace('.JK', '')
    if use_cache:
        try:
            with _CACHE_LOCK:
                cache = _cache_load()
                ent = cache.get(sym)
            if ent and (time.time() - ent.get('_ts', 0)) < CACHE_TTL and ent.get('data'):
                return ent['data']
        except Exception:
            pass
    data = _fetch_financials_live(sym)
    if use_cache:
        try:
            with _CACHE_LOCK:
                cache = _cache_load()
                cache[sym] = {'_ts': time.time(), 'data': data}
                _cache_save(cache)
        except Exception:
            pass
    return data


def _throttle():
    """Token-bucket gate: endpoint allows a burst of _BURST_SIZE calls, then needs
    _BURST_COOLDOWN seconds before the next call succeeds again."""
    with _BURST_LOCK:
        now = time.time()
        if now - _BURST_STATE['window_start'] >= _BURST_COOLDOWN:
            _BURST_STATE['window_start'] = now
            _BURST_STATE['count'] = 0
        if _BURST_STATE['count'] >= _BURST_SIZE:
            sleep_for = _BURST_COOLDOWN - (now - _BURST_STATE['window_start'])
            if sleep_for > 0:
                time.sleep(sleep_for)
            _BURST_STATE['window_start'] = time.time()
            _BURST_STATE['count'] = 0
        _BURST_STATE['count'] += 1


def _fetch_financials_live(symbol, retries=2):
    sym = symbol.upper().replace('.JK','')
    url = f'{BASE}/keystats/ratio/v1/{sym}'
    for attempt in range(retries):
        with _RATE_SEM:
            _throttle()
            req = urllib.request.Request(url, headers=_headers())
            raw = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
        # Stockbit rate-limits by returning 200 OK with an EMPTY closure_fin_items_results
        # once the burst quota is exhausted, instead of a proper 429/503.
        if raw.get('data', {}).get('closure_fin_items_results'):
            break
        if attempt < retries - 1:
            with _BURST_LOCK:
                _BURST_STATE['count'] = _BURST_SIZE  # force cooldown before retry
            time.sleep(_BURST_COOLDOWN)
    items, sections = _flatten(raw)

    def g(name): return items.get(name)
    def n(name): return _parse_num(g(name))

    ratios = {
        'per_ttm': n('Current PE Ratio (TTM)'),
        'per_ann': n('Current PE Ratio (Annualised)'),
        'forward_pe': n('Forward PE Ratio'),
        'pbv': n('Current Price to Book Value'),
        'ps_ttm': n('Current Price to Sales (TTM)'),
        'ev_ebitda': n('EV to EBITDA (TTM)'),
        'peg': n('PEG Ratio'),
        'earnings_yield_pct': n('Earnings Yield (TTM)'),
        'dividend_yield_pct': n('Dividend Yield'),
        'eps_ttm': n('Current EPS (TTM)'),
        'bvps': n('Current Book Value Per Share'),
        'roe_pct': n('Return on Equity (TTM)'),
        'roa_pct': n('Return on Assets (TTM)'),
        'net_margin_pct': n('Net Profit Margin (Quarter)'),
        'gross_margin_pct': n('Gross Profit Margin (Quarter)'),
        'der': n('Debt to Equity Ratio (Quarter)'),
        'current_ratio': n('Current Ratio (Quarter)'),
        'piotroski': n('Piotroski F-Score'),
        'rs_rating_pct': n('Relative Strength Rating'),
    }
    pnl = {
        'revenue_ttm_b': n('Revenue (TTM)'),
        'gross_profit_ttm_b': n('Gross Profit (TTM)'),
        'ebitda_ttm_b': n('EBITDA (TTM)'),
        'net_income_ttm_b': n('Net Income (TTM)'),
        'revenue_yoy_pct': n('Revenue (Quarter YoY Growth)'),
        'net_income_yoy_pct': n('Net Income (Quarter YoY Growth)'),
    }
    bs = {
        'cash_q_b': n('Cash (Quarter)'),
        'total_assets_q_b': n('Total Assets (Quarter)'),
        'total_liabilities_q_b': n('Total Liabilities (Quarter)'),
        'total_equity_q_b': n('Total Equity'),
        'common_equity_b': n('Common Equity'),
        'financial_leverage': n('Financial Leverage (Quarter)'),
    }
    cf = {
        'ocf_ttm_b': n('Cash From Operations (TTM)'),
        'cfi_ttm_b': n('Cash From Investing (TTM)'),
        'cff_ttm_b': n('Cash From Financing (TTM)'),
        'capex_ttm_b': n('Capital expenditure (TTM)'),
        'fcf_ttm_b': n('Free cash flow (TTM)'),
        'fcf_q_b': n('Free cash flow (Quarter)'),
    }
    # Derived previous-period estimates when Stockbit only provides YoY growth.
    # Formula: previous = current / (1 + yoy_pct/100). These are marked derived.
    def prev_from_yoy(cur, yoy_pct):
        try:
            if cur is None or yoy_pct is None or (1 + yoy_pct/100.0) == 0:
                return None
            return cur / (1 + yoy_pct/100.0)
        except Exception:
            return None

    prev = {
        'pnl': {
            'revenue_ttm_b': prev_from_yoy(pnl.get('revenue_ttm_b'), pnl.get('revenue_yoy_pct')),
            'net_income_ttm_b': prev_from_yoy(pnl.get('net_income_ttm_b'), pnl.get('net_income_yoy_pct')),
        },
        'ratios': {},
        'bs': {},
        'cf': {},
        'source_note': 'derived from YoY growth where available; direct prior BS/CF not available in keystats endpoint',
    }
    try:
        cur_rev = pnl.get('revenue_ttm_b'); cur_ni = pnl.get('net_income_ttm_b')
        prev_rev = prev['pnl']['revenue_ttm_b']; prev_ni = prev['pnl']['net_income_ttm_b']
        prev['ratios']['net_margin_pct_calc'] = (prev_ni / prev_rev * 100.0) if prev_rev and prev_ni is not None else None
        ratios['net_margin_ttm_calc_pct'] = (cur_ni / cur_rev * 100.0) if cur_rev and cur_ni is not None else None
    except Exception:
        pass

    return {'symbol': sym, 'source': 'stockbit_keystats', 'ratios': ratios, 'pnl': pnl, 'bs': bs, 'cf': cf, 'prev': prev, 'raw_sections': sections}

def fmt_b(x):
    if x is None: return 'n/a'
    sign='-' if x<0 else ''
    x=abs(x)
    if x>=1_000_000: return f'{sign}{x/1_000_000:.2f}Q'
    if x>=1_000: return f'{sign}{x/1_000:.1f}T'
    return f'{sign}{x:.0f}B'

def compact_inline(fin):
    r,p,b,c = fin['ratios'], fin['pnl'], fin['bs'], fin['cf']
    return (
        f"PER {r.get('per_ttm') or 'n/a'} · PBV {r.get('pbv') or 'n/a'} · EV/EBITDA {r.get('ev_ebitda') or 'n/a'} · "
        f"ROE {r.get('roe_pct') or 'n/a'}% · DER {r.get('der') or 'n/a'} · DivY {r.get('dividend_yield_pct') or 'n/a'}%\n"
        f"P&L: Rev {fmt_b(p.get('revenue_ttm_b'))} ({p.get('revenue_yoy_pct') or 'n/a'}% YoY), NI {fmt_b(p.get('net_income_ttm_b'))} ({p.get('net_income_yoy_pct') or 'n/a'}% YoY)\n"
        f"BS: Assets {fmt_b(b.get('total_assets_q_b'))}, Equity {fmt_b(b.get('total_equity_q_b'))}, Cash {fmt_b(b.get('cash_q_b'))}\n"
        f"CF: OCF {fmt_b(c.get('ocf_ttm_b'))}, Capex {fmt_b(c.get('capex_ttm_b'))}, FCF {fmt_b(c.get('fcf_ttm_b'))}"
    )

if __name__ == '__main__':
    sym = sys.argv[1] if len(sys.argv)>1 else 'BBRI'
    fin = fetch_financials(sym)
    print(compact_inline(fin))
    print(json.dumps(fin, ensure_ascii=False, indent=2))
