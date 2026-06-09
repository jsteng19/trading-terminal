"""Live order CRUD via the Kalshi REST API."""

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any
from typing import Optional

from pykalshi import Action, KalshiClient, OrderStatus, Side
from pykalshi.exceptions import InsufficientFundsError

from kalshi_tools.core.market_data import _normalize_order
from kalshi_tools.execution.log import LogEvent, log_event


@dataclass
class LiveOrder:
    """Local representation of an order on the exchange."""

    order_id: str
    client_order_id: str
    ticker: str
    side: str
    price: int
    count: int
    remaining: int
    status: str
    subaccount: int = 0
    post_only: bool = True
    expiration_ts: Optional[int] = None
    strategy_tag: Optional[str] = None


def _normalize_status(status: object) -> str:
    raw = str(getattr(status, "value", status)).lower()
    if raw == "canceled":
        return "cancelled"
    if raw == "executed":
        return "filled"
    return raw


def _extract_api_error_detail(exc: Exception) -> tuple[Optional[str], Optional[str], Optional[int], str]:
    """Extract structured API error context when available."""
    status_code = getattr(exc, "status_code", None)
    response_body = getattr(exc, "response_body", None)
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    if isinstance(response_body, dict):
        err: Any = response_body.get("error")
        if isinstance(err, dict):
            error_code = err.get("code")
            error_message = err.get("message")

    parts: list[str] = []
    if status_code is not None:
        parts.append(f"status={status_code}")
    if error_code:
        parts.append(f"code={error_code}")
    if error_message:
        parts.append(f"message={error_message}")
    if not parts:
        parts.append(str(exc))
    detail = " ".join(parts)

    return error_code, error_message, status_code, detail


class OrderManager:
    """Manages live orders on the Kalshi exchange."""

    def __init__(
        self,
        client: KalshiClient,
        subaccount: int = 0,
        logger: Optional[logging.Logger] = None,
    ):
        self.client = client
        self.subaccount = subaccount
        self.logger = logger
        self._orders: dict[str, LiveOrder] = {}

    def place_order(
        self,
        ticker: str,
        side: str,
        price: int,
        count: int,
        post_only: bool = True,
        expiration_ts: Optional[int] = None,
        strategy_tag: Optional[str] = None,
    ) -> LiveOrder:
        client_order_id = self._build_client_order_id(strategy_tag)
        side_enum = Side.YES if side.lower() == "yes" else Side.NO

        try:
            order = self.client.portfolio.place_order(
                ticker=ticker,
                action=Action.BUY,
                side=side_enum,
                count_fp=f"{count}.00",
                yes_price_dollars=f"{price / 100:.2f}" if side_enum == Side.YES else None,
                no_price_dollars=f"{price / 100:.2f}" if side_enum == Side.NO else None,
                client_order_id=client_order_id,
                post_only=post_only,
                expiration_ts=expiration_ts,
                subaccount=self.subaccount if self.subaccount else None,
            )
        except InsufficientFundsError as exc:
            if self.logger:
                log_event(
                    self.logger,
                    LogEvent(
                        event="INSUFFICIENT_FUNDS",
                        ticker=ticker,
                        data={
                            "side": side,
                            "price": price,
                            "count": count,
                            "subaccount": self.subaccount,
                            "strategy_tag": strategy_tag,
                        },
                    ),
                )
            raise
        except Exception as exc:
            error_code, error_message, status_code, detail = _extract_api_error_detail(exc)
            if self.logger:
                log_event(
                    self.logger,
                    LogEvent(
                        event="ORDER_REJECTED",
                        ticker=ticker,
                        data={
                            "side": side,
                            "price": price,
                            "count": count,
                            "strategy_tag": strategy_tag,
                            "status_code": status_code,
                            "error_code": error_code,
                            "error_message": error_message,
                            "detail": detail,
                        },
                    ),
                )
            raise RuntimeError(f"order_rejected {detail}") from exc

        remaining = int(float(order.remaining_count_fp)) if order.remaining_count_fp is not None else count
        live_order = LiveOrder(
            order_id=order.order_id,
            client_order_id=client_order_id,
            ticker=ticker,
            side=side.lower(),
            price=price,
            count=count,
            remaining=remaining,
            status=_normalize_status(order.status),
            subaccount=self.subaccount,
            post_only=post_only,
            expiration_ts=expiration_ts,
            strategy_tag=strategy_tag,
        )
        self._orders[client_order_id] = live_order

        if self.logger:
            log_event(
                self.logger,
                LogEvent(
                    event="ORDER_PLACED",
                    ticker=ticker,
                    data={
                        "side": side,
                        "price": price,
                        "count": count,
                        "client_order_id": client_order_id,
                        "order_id": order.order_id,
                        "post_only": post_only,
                        "expiration_ts": expiration_ts,
                        "strategy_tag": strategy_tag,
                    },
                ),
            )

        return live_order

    def cancel_order(self, client_order_id: str) -> bool:
        order = self._orders.get(client_order_id)
        if order is None:
            return False

        try:
            self.client.portfolio.cancel_order(
                order.order_id,
                subaccount=self.subaccount if self.subaccount else None,
            )
        except Exception as e:
            # Exchange can return 404 when the order was just filled/cancelled.
            # Treat as already-closed to avoid noisy false failures.
            err = str(e).lower()
            if "404" in err or "not found" in err:
                order.status = "cancelled"
                order.remaining = 0
                if self.logger:
                    log_event(
                        self.logger,
                        LogEvent(
                            event="ORDER_CANCELLED",
                            ticker=order.ticker,
                            data={
                                "client_order_id": client_order_id,
                                "detail": "already_closed",
                                "strategy_tag": order.strategy_tag,
                            },
                        ),
                    )
                return True
            if self.logger:
                log_event(
                    self.logger,
                    LogEvent(
                        event="CANCEL_FAILED",
                        ticker=order.ticker,
                        data={
                            "client_order_id": client_order_id,
                            "error": str(e),
                            "strategy_tag": order.strategy_tag,
                        },
                    ),
                )
            return False

        order.status = "cancelled"
        order.remaining = 0

        if self.logger:
            log_event(
                self.logger,
                LogEvent(
                    event="ORDER_CANCELLED",
                    ticker=order.ticker,
                    data={"client_order_id": client_order_id, "strategy_tag": order.strategy_tag},
                ),
            )

        return True

    def cancel_all(self, ticker: Optional[str] = None) -> int:
        cancelled = 0
        for cid, order in list(self._orders.items()):
            if order.status not in ("resting", "pending"):
                continue
            if ticker and order.ticker != ticker:
                continue
            if self.cancel_order(cid):
                cancelled += 1
        return cancelled

    def cancel_all_exchange(self, ticker: Optional[str] = None) -> int:
        try:
            from pykalshi._utils import normalize_ticker

            params: dict = {"limit": 200, "status": "resting"}
            if ticker:
                params["ticker"] = normalize_ticker(ticker)
            if self.subaccount:
                params["subaccount"] = self.subaccount
            raw_orders = self.client.paginated_get(
                "/portfolio/orders", "orders", params, True,
            )
            orders = [_normalize_order(o) for o in raw_orders]
        except Exception as e:
            if self.logger:
                log_event(
                    self.logger,
                    LogEvent(
                        event="CANCEL_ALL_EXCHANGE_FETCH_FAILED",
                        ticker=ticker or "",
                        data={"error": str(e)},
                    ),
                )
            return 0

        cancelled = 0
        for exchange_order in orders or []:
            try:
                self.client.portfolio.cancel_order(
                    exchange_order["order_id"],
                    subaccount=self.subaccount if self.subaccount else None,
                )
                cancelled += 1
            except Exception:
                continue

        for local in self._orders.values():
            if local.status in ("resting", "pending") and (ticker is None or local.ticker == ticker):
                local.status = "cancelled"
                local.remaining = 0

        if self.logger and cancelled > 0:
            log_event(
                self.logger,
                LogEvent(
                    event="CANCEL_ALL_EXCHANGE",
                    ticker=ticker or "",
                    data={"cancelled": cancelled},
                ),
            )

        return cancelled

    def get_resting_orders(self, ticker: Optional[str] = None) -> list[LiveOrder]:
        return [
            order
            for order in self._orders.values()
            if order.status in ("resting", "pending") and (ticker is None or order.ticker == ticker)
        ]

    def get_order(self, client_order_id: str) -> Optional[LiveOrder]:
        return self._orders.get(client_order_id)

    def sync_with_exchange(self) -> None:
        try:
            params: dict = {"limit": 200, "status": "resting"}
            if self.subaccount:
                params["subaccount"] = self.subaccount
            raw_orders = self.client.paginated_get(
                "/portfolio/orders", "orders", params, True,
            )
            exchange_orders = [_normalize_order(o) for o in raw_orders]
        except Exception:
            return

        exchange_by_id = {o["order_id"]: o for o in exchange_orders}
        for local in self._orders.values():
            if local.status not in ("resting", "pending"):
                continue

            if local.order_id in exchange_by_id:
                remote = exchange_by_id[local.order_id]
                remaining = remote.get("remaining_count")
                local.remaining = remaining if remaining is not None else local.remaining
                local.status = _normalize_status(remote.get("status", local.status))
                if local.remaining == 0:
                    local.status = "filled"
            else:
                local.status = "filled" if local.remaining == 0 else "cancelled"

    @staticmethod
    def _build_client_order_id(strategy_tag: Optional[str]) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(strategy_tag or "").strip()).strip("-")
        if slug:
            slug = slug[:40]
            return f"{slug}-{uuid.uuid4()}"
        return str(uuid.uuid4())
