"""Public landing page for MAI-IDX-Signal."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"])


LANDING_HTML = """<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MAI-IDX-Signal — Scanner Saham BEI Real-Time</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-950 text-gray-100">
  <header class="max-w-5xl mx-auto px-6 py-20 text-center">
    <h1 class="text-4xl md:text-6xl font-extrabold mb-4 text-white">
      Scanner Saham BEI 963 Simbol</h1>
    <p class="text-xl md:text-2xl text-blue-400 mb-8">Real-Time AI Signal</p>
    <p class="text-gray-400 max-w-2xl mx-auto mb-10">
      Pantau seluruh universe Bursa Efek Indonesia dengan skoring teknikal
      otomatis, anti-gorengan, dan sinyal entry/TP/SL langsung ke Telegram.</p>
    <a href="/dashboard" class="inline-block bg-blue-600 hover:bg-blue-700 text-white
      px-8 py-3 rounded-lg font-semibold mr-3">Buka Dashboard</a>
    <a href="#tiers" class="inline-block border border-gray-700 hover:bg-gray-900
      px-8 py-3 rounded-lg font-semibold">Lihat Paket</a>
    <nav class="mt-8 flex flex-wrap justify-center gap-4 text-sm text-blue-400">
      <a href="/dashboard" class="hover:underline">Dashboard</a>
      <a href="/dashboard/status" class="hover:underline">Status</a>
      <a href="/dashboard/backtest" class="hover:underline">Backtest</a>
      <a href="/member" class="hover:underline">Member</a>
      <a href="/admin" class="hover:underline">Admin</a>
    </nav>
  </header>

  <section class="max-w-5xl mx-auto px-6 py-12">
    <h2 class="text-2xl font-bold mb-8 text-center">Fitur</h2>
    <div class="grid md:grid-cols-4 gap-6">
      <div class="bg-gray-900 p-6 rounded-lg"><p class="text-lg font-semibold mb-2">🔍 Scan</p>
        <p class="text-sm text-gray-400">963 saham dipindai tiap sesi market.</p></div>
      <div class="bg-gray-900 p-6 rounded-lg"><p class="text-lg font-semibold mb-2">📈 Chart</p>
        <p class="text-sm text-gray-400">Chart teknikal otomatis per sinyal.</p></div>
      <div class="bg-gray-900 p-6 rounded-lg"><p class="text-lg font-semibold mb-2">🤖 Telegram Bot</p>
        <p class="text-sm text-gray-400">Sinyal & analisa langsung di chat.</p></div>
      <div class="bg-gray-900 p-6 rounded-lg"><p class="text-lg font-semibold mb-2">📊 Performa</p>
        <p class="text-sm text-gray-400">Tracker PnL & backtest historis.</p></div>
    </div>
  </section>

  <section class="max-w-5xl mx-auto px-6 py-12">
    <div class="grid md:grid-cols-3 gap-6 text-center">
      <div class="bg-gray-900 p-6 rounded-lg"><p class="text-3xl font-bold text-blue-400">963</p>
        <p class="text-sm text-gray-400">Saham BEI</p></div>
      <div class="bg-gray-900 p-6 rounded-lg"><p class="text-3xl font-bold text-blue-400">92%</p>
        <p class="text-sm text-gray-400">Sektor coverage</p></div>
      <div class="bg-gray-900 p-6 rounded-lg"><p class="text-3xl font-bold text-blue-400">5</p>
        <p class="text-sm text-gray-400">Sinyal / hari</p></div>
    </div>
  </section>

  <section id="tiers" class="max-w-5xl mx-auto px-6 py-12">
    <h2 class="text-2xl font-bold mb-8 text-center">Paket</h2>
    <div class="grid md:grid-cols-2 gap-6">
      <div class="bg-gray-900 p-8 rounded-lg border border-gray-800">
        <p class="text-xl font-bold mb-2">Free</p>
        <p class="text-3xl font-extrabold mb-4">Rp0</p>
        <ul class="text-sm text-gray-400 space-y-2">
          <li>• 2 sinyal / hari</li><li>• Dashboard publik</li>
          <li>• Bot /signal & /why</li></ul></div>
      <div class="bg-gray-900 p-8 rounded-lg border-2 border-blue-600">
        <p class="text-xl font-bold mb-2 text-blue-400">Pro</p>
        <p class="text-3xl font-extrabold mb-4">Unlimited</p>
        <ul class="text-sm text-gray-300 space-y-2">
          <li>• Sinyal tanpa batas</li><li>• Backtest engine</li>
          <li>• Data papan RG/NG/TN</li><li>• Member area & PnL pribadi</li></ul></div>
    </div>
  </section>

  <section class="max-w-5xl mx-auto px-6 py-16 text-center">
    <a href="https://t.me/" class="inline-block bg-blue-600 hover:bg-blue-700 text-white
      px-10 py-4 rounded-lg font-semibold text-lg">Join Telegram Group</a>
    <p class="text-xs text-gray-600 mt-8">⚠️ Bukan ajakan beli/jual. Risiko ditanggung sendiri.</p>
  </section>
</body></html>"""


@router.get("/", response_class=HTMLResponse)
async def landing():
    return HTMLResponse(LANDING_HTML)
