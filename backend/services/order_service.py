"""Order management service wrapping kalshi_tools OrderManager.

All orders are strictly scoped to the configured SUBACCOUNT.

Fee structure (Kalshi as of 2025):
- Taker fee: ceil(0.07 * contracts * price * (1 - price))
- Maker fee: ZERO (no maker fees on standard markets)
- Post-only orders pay NO fees. Only crossing orders (taker) pay fees.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Optional

from backend.config import SUBACCOUNT, MAX_ORDER_CONTRACTS
from backend.dependencies import get_client, get_market_data
from backend.lazy_import import lazy_import

_om_mod = lazy_import("kalshi_tools.execution.order_manager")

OrderManager = _om_mod.OrderManager
LiveOrder = _om_mod.LiveOrder

logger = logging.getLogger(__name__)

# Singleton order manager
_order_manager: Optional[OrderManager] = None

# Kalshi taker fee coefficient
TAKER_FEE_COEFFICIENT = 0.07


def get_order_manager() -> OrderManager:
    global _order_manager
    if _order_manager is None:
        _order_manager = OrderManager(
            client=get_client(),
            subaccount=SUBACCOUNT,
            logger=logger,
        )
    return _order_manager


@dataclass
class OrderRequest:
    ticker: str
    side: str           # "yes" or "no"
    price: int          # cents (1-99)
    count: int          # contracts
    post_only: bool = True
    expiration_ts: Optional[int] = None


@dataclass
class CostEstimate:
    gross_cost_dollars: float
    fee_cents: int
    fee_dollars: float
    total_cost_dollars: float
    effective_price_cents: float
    is_taker: bool


def _calc_taker_fee_cents(contracts: int, price_cents: int) -> int:
    """Kalshi taker fee: ceil(0.07 * contracts * P * (1-P)) where P = price/100."""
    p = price_cents / 100
    return math.ceil(TAKER_FEE_COEFFICIENT * contracts * p * (1 - p) * 100)


def estimate_cost(side: str, price: int, count: int, post_only: bool = True) -> CostEstimate:
    """Estimate the cost of an order including fees.

    Post-only (maker) orders have ZERO fees.
    Only taker (crossing) orders pay the taker fee.
    """
    gross_cost = count * price / 100  # dollars

    if post_only:
        # Maker: no fees
        fee_cents = 0
    else:
        # Taker: standard fee
        fee_cents = _calc_taker_fee_cents(count, price)

    fee_dollars = fee_cents / 100
    total_cost = gross_cost + fee_dollars
    effective_price = (total_cost * 100) / count if count > 0 else 0

    return CostEstimate(
        gross_cost_dollars=gross_cost,
        fee_cents=fee_cents,
        fee_dollars=fee_dollars,
        total_cost_dollars=total_cost,
        effective_price_cents=effective_price,
        is_taker=not post_only,
    )


def place_order(req: OrderRequest) -> dict:
    """Place an order. Returns the order details."""
    om = get_order_manager()

    if req.price < 1 or req.price > 99:
        raise ValueError(f"Price must be 1-99 cents, got {req.price}")
    if req.count < 1:
        raise ValueError(f"Count must be >= 1, got {req.count}")
    if req.count > MAX_ORDER_CONTRACTS:
        raise ValueError(f"Count {req.count} exceeds max {MAX_ORDER_CONTRACTS}")
    if req.side.lower() not in ("yes", "no"):
        raise ValueError(f"Side must be 'yes' or 'no', got {req.side}")

    live_order = om.place_order(
        ticker=req.ticker,
        side=req.side.lower(),
        price=req.price,
        count=req.count,
        post_only=req.post_only,
        expiration_ts=req.expiration_ts,
        strategy_tag="terminal",
    )

    return _order_to_dict(live_order)


def cancel_order(order_id: str) -> dict:
    """Cancel an order by exchange order_id."""
    md = get_market_data()
    try:
        md.client.portfolio.cancel_order(
            order_id,
            subaccount=SUBACCOUNT if SUBACCOUNT else None,
        )
        return {"order_id": order_id, "status": "cancelled"}
    except Exception as e:
        err = str(e).lower()
        if "404" in err or "not found" in err:
            return {"order_id": order_id, "status": "already_closed"}
        raise


def cancel_all_orders(ticker: Optional[str] = None, event_ticker: Optional[str] = None) -> dict:
    """Cancel all resting orders, optionally filtered by ticker or event."""
    md = get_market_data()
    orders = md.get_orders(
        ticker=ticker,
        event_ticker=event_ticker,
        status="resting",
        subaccount=SUBACCOUNT if SUBACCOUNT else None,
    )

    cancelled = 0
    errors = 0
    for order in orders:
        oid = order.get("order_id")
        if not oid:
            continue
        try:
            md.client.portfolio.cancel_order(
                oid,
                subaccount=SUBACCOUNT if SUBACCOUNT else None,
            )
            cancelled += 1
        except Exception:
            errors += 1

    return {
        "cancelled": cancelled,
        "errors": errors,
        "total": len(orders),
    }


def _order_to_dict(order: LiveOrder) -> dict:
    return {
        "order_id": order.order_id,
        "client_order_id": order.client_order_id,
        "ticker": order.ticker,
        "side": order.side,
        "price": order.price,
        "count": order.count,
        "remaining": order.remaining,
        "status": order.status,
        "subaccount": order.subaccount,
        "post_only": order.post_only,
    }
