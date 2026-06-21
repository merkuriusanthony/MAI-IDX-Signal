"""Minimal IDX ticker → sector mapping. Expand as needed."""
from __future__ import annotations

SECTOR_MAP = {
    # Perbankan
    "BBCA": "Perbankan", "BBRI": "Perbankan", "BMRI": "Perbankan", "BBNI": "Perbankan",
    # Konsumer
    "UNVR": "Konsumer", "ICBP": "Konsumer", "INDF": "Konsumer", "MYOR": "Konsumer",
    # Telekomunikasi
    "TLKM": "Telekomunikasi", "EXCL": "Telekomunikasi", "ISAT": "Telekomunikasi",
    # Energi
    "ADRO": "Energi", "PTBA": "Energi", "ITMG": "Energi", "BUMI": "Energi",
    # Properti
    "BSDE": "Properti", "SMRA": "Properti", "CTRA": "Properti",
    # Infrastruktur
    "JSMR": "Infrastruktur", "WSKT": "Infrastruktur",
}


def get_sector(symbol: str) -> str:
    """Return the IDX sector for a ticker, or 'Lainnya' if unknown."""
    return SECTOR_MAP.get(symbol.upper(), "Lainnya")
