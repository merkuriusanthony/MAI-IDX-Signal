"""Prompt builders for the Claude reasoning layer."""
from __future__ import annotations

import json
from typing import Dict


def build_signal_prompt(
    symbol: str, score_dict: Dict, indicators: Dict
) -> str:
    """Build a strict-JSON prompt for signal reasoning.

    Claude must only reason over the supplied computed metrics and must not
    invent any price levels.
    """
    payload = {
        "symbol": symbol,
        "score": score_dict.get("score"),
        "label": score_dict.get("label"),
        "reasons": score_dict.get("reasons", []),
        "indicators": {
            "close": indicators.get("close"),
            "ma20": indicators.get("ma20"),
            "ma50": indicators.get("ma50"),
            "ma200": indicators.get("ma200"),
            "rsi": indicators.get("rsi"),
            "macd_hist": indicators.get("macd_hist"),
            "stoch_k": indicators.get("stoch_k"),
            "support_resistance": indicators.get("support_resistance"),
            "fib": indicators.get("fib"),
            "volume_spike": indicators.get("volume_spike"),
        },
    }

    return (
        "Anda adalah analis teknikal saham Bursa Efek Indonesia (BEI).\n"
        "Gunakan HANYA metrik yang diberikan. JANGAN mengarang angka harga "
        "yang tidak ada dalam data.\n"
        "Balas HANYA dalam format JSON valid dengan skema persis:\n"
        "{\n"
        '  "summary": string,\n'
        '  "key_reasons": [string],\n'
        '  "risks": [string],\n'
        '  "invalidation_note": string,\n'
        '  "retail_message": string\n'
        "}\n\n"
        f"Data metrik:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Jawab dalam Bahasa Indonesia. Output JSON saja, tanpa teks lain."
    )
