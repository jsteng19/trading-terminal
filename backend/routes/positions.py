"""Position and PNL endpoints.

All queries are strictly scoped to the configured SUBACCOUNT.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.config import SUBACCOUNT
from backend.dependencies import get_market_data

router = APIRouter(prefix="/api/positions", tags=["positions"])


def _sub_param() -> int | None:
    """Return the subaccount param for API calls (None if main account)."""
    return SUBACCOUNT if SUBACCOUNT > 0 else None


@router.get("/")
def list_positions(
    event_ticker: str = Query(None),
):
    """List portfolio positions (subaccount enforced server-side)."""
    md = get_market_data()
    positions = md.get_positions(
        event_ticker=event_ticker,
        subaccount=_sub_param(),
    )
    return {"positions": positions, "subaccount": SUBACCOUNT}


@router.get("/orders")
def list_orders(
    event_ticker: str = Query(None),
    ticker: str = Query(None),
    status: str = Query("resting"),
):
    """List portfolio orders (subaccount enforced server-side)."""
    md = get_market_data()
    orders = md.get_orders(
        event_ticker=event_ticker,
        ticker=ticker,
        status=status,
        subaccount=_sub_param(),
    )
    return {"orders": orders, "subaccount": SUBACCOUNT}


@router.get("/fills")
def list_fills(
    ticker: str = Query(None),
):
    """List portfolio fills (subaccount enforced server-side)."""
    md = get_market_data()
    fills = md.get_fills(
        ticker=ticker,
        subaccount=_sub_param(),
    )
    return {"fills": fills, "subaccount": SUBACCOUNT}
