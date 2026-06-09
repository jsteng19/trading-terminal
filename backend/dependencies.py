"""Shared singletons for the terminal backend."""

from __future__ import annotations

from typing import Optional

from kalshi_tools.core.client import get_client as _make_client
from kalshi_tools.core.market_data import MarketData

from backend.config import DEMO

_client = None
_market_data = None


def get_client():
    """Get or create the shared KalshiClient singleton."""
    global _client
    if _client is None:
        _client = _make_client(demo=DEMO)
    return _client


def get_market_data():
    """Get or create the shared MarketData singleton."""
    global _market_data
    if _market_data is None:
        _market_data = MarketData(client=get_client())
    return _market_data


def reset():
    """Reset singletons (e.g., when switching demo/live mode)."""
    global _client, _market_data
    _client = None
    _market_data = None
