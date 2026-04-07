"""Order placement and cancellation endpoints.

All mutating endpoints require the session token.
All orders are scoped to the configured SUBACCOUNT.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.security import require_token
from backend.services.order_service import (
    OrderRequest,
    cancel_all_orders,
    cancel_order,
    estimate_cost,
    place_order,
)

router = APIRouter(prefix="/api/orders", tags=["orders"])


class PlaceOrderBody(BaseModel):
    ticker: str
    side: str
    price: int
    count: int
    post_only: bool = True
    expiration_ts: Optional[int] = None


class CancelOrderBody(BaseModel):
    order_id: str


class CancelAllBody(BaseModel):
    ticker: Optional[str] = None
    event_ticker: Optional[str] = None


class EstimateCostBody(BaseModel):
    side: str
    price: int
    count: int
    post_only: bool = True


@router.post("/place", dependencies=[Depends(require_token)])
def api_place_order(body: PlaceOrderBody):
    """Place a new order."""
    req = OrderRequest(
        ticker=body.ticker,
        side=body.side,
        price=body.price,
        count=body.count,
        post_only=body.post_only,
        expiration_ts=body.expiration_ts,
    )
    try:
        result = place_order(req)
        return {"ok": True, "order": result}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/cancel", dependencies=[Depends(require_token)])
def api_cancel_order(body: CancelOrderBody):
    """Cancel a single order by exchange order_id."""
    try:
        result = cancel_order(body.order_id)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/cancel-all", dependencies=[Depends(require_token)])
def api_cancel_all(body: CancelAllBody):
    """Cancel all resting orders, optionally filtered."""
    try:
        result = cancel_all_orders(
            ticker=body.ticker,
            event_ticker=body.event_ticker,
        )
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/estimate")
def api_estimate_cost(body: EstimateCostBody):
    """Estimate cost of an order (no auth required, read-only)."""
    try:
        est = estimate_cost(body.side, body.price, body.count, body.post_only)
        return {
            "ok": True,
            "gross_cost": est.gross_cost_dollars,
            "fee_cents": est.fee_cents,
            "fee_dollars": est.fee_dollars,
            "total_cost": est.total_cost_dollars,
            "effective_price": est.effective_price_cents,
            "is_taker": est.is_taker,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
