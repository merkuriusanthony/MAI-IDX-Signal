# PLAN v2 — Deep Analysis + Foreign Flow di Dashboard Index

Status: PLAN ONLY. No code written. Mode: implement after approval.

Revisi dari `PLAN_deep_analysis.md`. Scope tambahan: **kolom Foreign + filter foreign di tabel dashboard index** (`GET /dashboard/`).

---

## 1. Summary perubahan dari v1

### Yang SAMA (tak berubah dari v1)
- T1–T11 semua tetap, tujuan & desain identik.
- Arsitektur deep-analysis (5-panel chart + fundamental table per signal) tak berubah.
- Sumber foreign tetap Stockbit `GET /company-price-feed/historical/summary/{SYMBOL}`.
- `foreign_net_5d` sudah diputuskan disimpan ke `snapshot_json` saat scan **di T5 v1** (`snap_dict["foreign_net_5d"]`). v2 hanya **menampilkan**-nya di tabel.
- Token/auth, edge-case Stockbit, compile gate v1 semua tetap.

### Yang BERUBAH / TAMBAH di v2
| Aspek | v1 | v2 |
|---|---|---|
| Task count | T1–T11 | T1–T12 (**+T12** dashboard index foreign kolom) |
| `/dashboard/` index table | hanya teknikal (Symbol…Waktu) | **+kolom Foreign** setelah Score |
| Filter dashboard index | search + action + board | **+dropdown FA Beli/FA Jual** |
| Sort dashboard index | symbol/board/action/score/entry/tp1/tp2/sl/ts | **+foreign (num)** |
| Sumber data foreign tabel | — | **Option A + C**: signal baru baca `snapshot_json["foreign_net_5d"]`; signal lama → `n/a`. **Tidak ada fetch realtime saat render** (Option B ditolak). |

### Keputusan sumber data (eksplisit)
**A + C dipilih.**
- A: `foreign_net_5d` ditulis ke `snapshot_json` saat scan (T5 v1). Tabel index tinggal parse.
- C: signal lama yang `snapshot_json` belum punya key → render `n/a` (abu). Tidak crash.
- B (fetch realtime saat render `/dashboard/`) **DITOLAK**: mahal + lambat (N row × HTTP call), tak dipakai.

---

## 2. Ordered Task List T1–T12

T1–T11 = identik v1 (lihat `PLAN_deep_analysis.md` §2 untuk detail penuh). Ringkas:

| T | File | Aksi |
|---|---|---|
| T1 | `app/data/stockbit_auth.py` (NEW) | token resolver + headers |
| T2 | `app/data/fetch_stockbit.py` (NEW) | `fetch_keystats` + `fetch_foreign_flow` (async httpx) |
| T3 | `app/analytics/indicators.py` (MOD) | +`trend_label`, +`foreign_net_5d`, `to_dict()` |
| T4 | `app/signals/chart.py` (MOD) | 5-panel + PE/PBV band + fundamental table + foreign overlay |
| T5 | `app/signals/generator.py` (MOD) | fetch Stockbit; set `snap.foreign_net_5d`; merge ke `snap_dict["foreign_net_5d"]` + `["fin"]`; expose `_df`/`_foreign_df` |
| T6 | `app/scanner.py` (MOD) | pass `fin`/`foreign_df` ke `generate_chart` |
| T7 | `app/dashboard/routes.py` — **detail** (MOD) | upgrade `/dashboard/signals/{id}` + regenerate route |
| T8 | `app/analytics/fundamentals.py` (NEW) | benchmark, `verdict`, `fmt`, `fund_score`, `grade` (shared) |
| T9 | Integration smoke + compile gate | — |
| T10 | `app/signals/routes.py` (MOD) | `POST /api/analyze/{symbol}` |
| T11 | `app/main.py` (MOD) | register `analyze_router` |
| **T12** | `app/dashboard/routes.py` — **index** (MOD) | **+kolom Foreign, +filter FA, +sort foreign** |

**Catatan dependency T12:**
- Depends pada **T5** (yang menulis `foreign_net_5d` ke `snapshot_json`). Tanpa T5, semua row tampil `n/a` (tetap valid, tak crash — Option C).
- T12 menyentuh file yang sama dengan T7 (`app/dashboard/routes.py`) tapi **fungsi berbeda**: T7 = `signal_detail`, T12 = `index`. Tak ada konflik logika; cukup koordinasi 1 file. Boleh dikerjakan setelah T7 untuk hindari edit bertumpuk.

---

## 3. T12 — DETAIL (MODIFY `app/dashboard/routes.py`, fungsi `index`)

Target: fungsi `index()` (`routes.py:65`). Tabel sekarang: `Symbol | Board | Action | Score | Entry | TP1 | TP2 | SL | Waktu | detail`. Sisipkan **Foreign** tepat setelah **Score**.

### 3.1 Parse `snapshot_json` → ambil `foreign_net_5d`
`index()` query `Signal` rows tapi **belum** baca `snapshot_json`. Tambah di loop `for s in rows`:
```python
fnet = None
try:
    snap = json.loads(s.snapshot_json) if s.snapshot_json else {}
    fnet = snap.get("foreign_net_5d")   # bisa None (signal lama / Option C)
except Exception:
    fnet = None
```
`json` sudah di-import (`routes.py:4`). `Signal.snapshot_json` ada (`db.py:147`).

### 3.2 Helper format foreign (module-level, dekat `ACTION_COLOR`)
```python
def _fmt_foreign(v):
    """(html_cell_inner, data_value_str) untuk kolom Foreign."""
    if v is None:
        return ("<span class='text-gray-500'>n/a</span>", "0")
    try:
        n = float(v)
    except Exception:
        return ("<span class='text-gray-500'>n/a</span>", "0")
    a = abs(n)
    if a >= 1_000_000_000:
        amt = f"{a/1_000_000_000:.1f}B"
    elif a >= 1_000_000:
        amt = f"{a/1_000_000:.1f}M"
    else:
        amt = f"{a/1_000_000:.2f}M"   # kecil tetap M, 2 desimal
    if n > 0:
        return (f"<span style='color:#3fb950'>▲ Rp{amt}</span>", str(n))
    if n < 0:
        return (f"<span style='color:#f85149'>▼ Rp{amt}</span>", str(n))
    return ("<span class='text-gray-500'>Rp0</span>", "0")
```
- Positif hijau `#3fb950` `▲`; negatif merah `#f85149` `▼`; None abu `n/a`.
- `data-foreign` = nilai numerik mentah (None → `"0"`) untuk sort.
- Rupiah: `<1B → "12.5M"`, `≥1B → "1.2B"`.

### 3.3 Update `<tr>` data-* (tambah `data-foreign`)
Di builder `cells.append(...)` (`routes.py:113`), tambah ke baris `data-*`:
```python
f"... data-ts='{ts}' data-foreign='{fdata}'>"
```
dimana `inner_foreign, fdata = _fmt_foreign(fnet)`.

### 3.4 Update sel tabel (tambah `<td>` Foreign setelah Score)
Setelah `<td ...>{s.score:.1f}</td>` (`routes.py:121`) sisipkan:
```python
f"<td class='p-2' data-foreign='{fdata}'>{inner_foreign}</td>"
```
(Note: `data-foreign` cukup di `<tr>` untuk sort; menaruh juga di `<td>` opsional — **simpan di `<tr>` saja** agar konsisten dgn pola sort yang baca `data-<key>` dari row.)

### 3.5 Update header tabel `headers` list (`routes.py:154`)
Sisipkan setelah `("Score","score","num")`:
```python
("Foreign", "foreign", "num"),
```
`head_cells` builder otomatis render `<th onclick=sigSort('foreign','num')>`. `sigSort` sudah dukung `type==='num'` → **tak perlu ubah JS sort**, hanya tambah entri header.

### 3.6 Update filter dropdown (tambah FA Beli / FA Jual)
Di blok `controls` (`routes.py:132`), setelah dropdown board, tambah:
```python
"<select id='sig-foreign' onchange='sigFilter()' class='bg-gray-800 text-white text-sm rounded px-2 py-2'>"
"<option value=''>Semua FA</option>"
"<option value='buy'>FA Beli (net&gt;0)</option>"
"<option value='sell'>FA Jual (net&lt;0)</option>"
"</select>"
```

### 3.7 Update JS `sigFilter()` (tambah logika foreign)
Di `sig_js` (`routes.py:185`), dalam `sigFilter`:
```javascript
var f=document.getElementById('sig-foreign').value;
...
var fv=parseFloat(r.getAttribute('data-foreign'))||0;
var okF=(!f)||(f==='buy'&&fv>0)||(f==='sell'&&fv<0);
var ok=(...existing...)&&okF;
```
Catatan: row `n/a` punya `data-foreign='0'` → `fv=0` → **tak lolos** FA Beli maupun FA Jual (hanya muncul di "Semua FA"). Sesuai harapan (net 0/unknown bukan beli/jual).

### 3.8 Update `sigSort()`
**Tak perlu ubah body JS** — sudah generik `data-<key>` + `type='num'`. Cukup entri header (3.5). Sort `foreign` baca `data-foreign` dari `<tr>`. n/a→0 ikut terurut di tengah. ✓

### 3.9 Update counter
Counter `sig-counter` ("Menampilkan X dari Y") sudah dihitung dari `shown` di `sigFilter()` → otomatis ikut filter foreign baru. **Tak ada perubahan** selain logika filter 3.7 sudah meng-update `shown`.

### 3.10 Colspan kosong / empty-state
Index tak pakai `colspan` di tbody (row asli saja). Header trailing `<th class='p-2'></th>` (kolom detail) tetap. Jumlah kolom bertambah 1 — tak ada colspan hardcoded yang perlu disesuaikan di index. ✓

---

## 4. Edge Cases (v2 tambahan)

### T12 / dashboard index foreign
- **Signal lama tanpa `foreign_net_5d`** di `snapshot_json`: `snap.get("foreign_net_5d")` → None → `_fmt_foreign(None)` → `n/a` abu, `data-foreign='0'`. Tak crash. (Option C)
- **`snapshot_json` korup / kosong / `"{}"`**: `try/except` di 3.1 → `fnet=None` → `n/a`.
- **`foreign_net_5d` non-numerik** (string aneh): `float()` di `_fmt_foreign` gagal → `n/a`.
- **Symbol tanpa token Stockbit saat scan**: T5 menulis `foreign_net_5d=None` (fetch return empty) → tabel `n/a`. Konsisten.
- **Filter FA Beli/Jual + row n/a**: `data-foreign='0'`, fv=0, tak lolos buy/sell → tersembunyi kecuali "Semua FA". Benar secara semantik.
- **Sort foreign dengan campuran n/a**: n/a=0 → diurut sebagai 0 (tengah antara negatif & positif). Acceptable; alternatif (push n/a ke bawah) tak diminta.
- **Nilai sangat kecil (<1M)**: format `"0.50M"` (2 desimal) — masih terbaca; tak menampilkan satuan ribuan agar kolom seragam.
- **HTML safety**: `data-foreign` = `str(float)` (aman, numerik); inner pakai span warna inline (controlled). `&gt;`/`&lt;` di label option sudah di-escape.

### Stockbit (carry-over v1, relevan ke isi kolom)
- Symbol suffix `.JK` di-strip sebelum call Stockbit (T2).
- 401/timeout → `{}`/empty → `foreign_net_5d=None` → `n/a`.

---

## 5. Compile gate (semua file disentuh, termasuk v2)

```
python3 -m py_compile \
  app/data/stockbit_auth.py app/data/fetch_stockbit.py \
  app/analytics/indicators.py app/analytics/fundamentals.py \
  app/signals/chart.py app/signals/generator.py \
  app/scanner.py app/dashboard/routes.py \
  app/signals/routes.py app/main.py
```
(`app/dashboard/routes.py` mencakup T7 detail + T12 index — satu file, satu compile.)

### Functional check tambahan v2
- [ ] `/dashboard/` render: kolom **Foreign** muncul setelah Score; header klik-able sort.
- [ ] Signal baru (post-T5): tampil `▲ RpX.XM` hijau / `▼ RpX.XB` merah sesuai net.
- [ ] Signal lama: tampil `n/a` abu, tak crash.
- [ ] Dropdown **FA Beli** → hanya row net>0; **FA Jual** → hanya net<0; counter update.
- [ ] Klik header Foreign → urut numerik asc/desc, n/a di tengah.
- [ ] Kombinasi filter (search + action + board + FA) bekerja bersama (AND).

---

## Appendix — File change summary v2 (delta dari v1)

| File | Action | Task |
|---|---|---|
| app/dashboard/routes.py | MODIFY — `index`: +kolom Foreign, +`_fmt_foreign`, +filter FA, +header sort entry, +JS foreign filter | **T12** |

Semua entri lain identik Appendix A `PLAN_deep_analysis.md`.
