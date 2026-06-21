"""Prompt builders for the Claude reasoning layer."""
from __future__ import annotations

import json
from typing import Dict


SYSTEM_INSTRUCTION = (
    "Anda adalah analis teknikal saham Bursa Efek Indonesia (BEI).\n"
    "ATURAN KETAT:\n"
    "1. Gunakan HANYA data yang diberikan dalam payload. JANGAN mengarang angka harga, volume, atau indikator.\n"
    "2. Jika ada data yang tidak tersedia, katakan 'data tidak tersedia'.\n"
    "3. JANGAN mengubah entry, TP, atau SL yang sudah dihitung secara deterministik.\n"
    "4. Balas HANYA dalam format JSON valid. TIDAK boleh ada teks di luar JSON.\n"
)

RESPONSE_SCHEMA = """{
  "verdict": "valid" | "caution" | "reject",
  "summary_id": string (max 2 kalimat Bahasa Indonesia),
  "key_drivers": [string] (max 5 item),
  "risks": [string] (max 5 item),
  "no_trade_reason": string | null
}"""


def build_signal_prompt(symbol: str, score_dict: Dict, indicators: Dict) -> str:
    """Build a strict-JSON prompt for signal reasoning."""
    payload = {
        "symbol": symbol,
        "score": score_dict.get("score"),
        "action": score_dict.get("action", score_dict.get("label")),
        "reason_codes": score_dict.get("reason_codes", []),
        "indicators": {
            "close": indicators.get("close"),
            "ma5": indicators.get("ma5"),
            "ma20": indicators.get("ma20"),
            "ma50": indicators.get("ma50"),
            "ma100": indicators.get("ma100"),
            "ma200": indicators.get("ma200"),
            "rsi": indicators.get("rsi"),
            "macd_hist": indicators.get("macd_hist"),
            "atr_pct": indicators.get("atr_pct"),
            "stoch_k": indicators.get("stoch_k"),
            "volume_spike": indicators.get("volume_spike"),
            "support_resistance": indicators.get("support_resistance"),
            "breakout_20d": indicators.get("breakout_20d"),
            "breakdown_20d": indicators.get("breakdown_20d"),
        },
    }

    return (
        f"{SYSTEM_INSTRUCTION}\n"
        f"Skema respons yang harus diikuti:\n{RESPONSE_SCHEMA}\n\n"
        f"Data metrik saham:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Jawab dalam Bahasa Indonesia. Output JSON saja."
    )


def build_why_prompt(symbol: str, signal: Dict, indicators: Dict) -> str:
    """Build a why-explanation prompt for /why command."""
    payload = {
        "symbol": symbol,
        "action": signal.get("action", signal.get("label")),
        "score": signal.get("score"),
        "entry": signal.get("entry"),
        "tp1": signal.get("tp1"),
        "stop_loss": signal.get("stop_loss", signal.get("sl")),
        "reason_codes": signal.get("reason_codes", []),
        "indicators": {
            k: indicators.get(k)
            for k in ("close", "ma20", "ma50", "ma200", "rsi", "macd_hist",
                      "volume_spike", "atr_pct", "breakout_20d")
        },
    }

    return (
        f"{SYSTEM_INSTRUCTION}\n"
        "Jelaskan mengapa saham ini mendapat sinyal tersebut berdasarkan indikator teknikal.\n"
        "Format respons:\n"
        '{"summary_id": string, "key_drivers": [string], "risks": [string]}\n\n'
        f"Data:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Jawab dalam Bahasa Indonesia. Output JSON saja."
    )
