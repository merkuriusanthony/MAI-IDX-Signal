"""IDX board classification: RG (Regular), NG (Negotiated), TN (Tunai).

Most liquid symbols trade on the Regular (RG) board. A small set of low-liquidity
or special-condition tickers trade only on the Negotiated (NG) or Cash (TN) board.
Source: IDX public board data — static list, update quarterly.
"""
from __future__ import annotations

# Symbols known to trade primarily on the Negotiated board.
NG_SYMBOLS: set[str] = {
    "DNAR",
    "OCAP",
    "MPRO",
    "POLA",
    "SKYB",
}

# Symbols restricted to the Cash board.
TN_SYMBOLS: set[str] = set()


def get_board(symbol: str) -> str:
    """Return board code for a symbol: RG, NG, or TN."""
    s = symbol.upper().replace(".JK", "")
    if s in NG_SYMBOLS:
        return "NG"
    if s in TN_SYMBOLS:
        return "TN"
    return "RG"
