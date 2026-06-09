"""Order book utilities and WebSocket streaming."""

import asyncio
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pykalshi import Feed, KalshiClient, OrderbookDeltaMessage, OrderbookSnapshotMessage

# Monkey-patch pykalshi's Feed._dispatch to handle Kalshi WS API serving `ts`
# as an ISO 8601 string (e.g. "2026-04-11T23:15:45.921388Z") instead of an int.
# Without this, Feed raises ValueError on every message and enters a reconnect
# loop. Patch is idempotent and runs once at import time.
def _install_pykalshi_ts_patch() -> None:
    import pykalshi.feed as _pkf

    if getattr(_pkf.Feed, "_ts_patch_installed", False):
        return

    def _coerce_ts(ts):
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return int(ts)
        if isinstance(ts, str):
            try:
                return int(ts)
            except ValueError:
                pass
            try:
                from datetime import datetime
                s = ts.rstrip("Z")
                dt = datetime.fromisoformat(s)
                return int(dt.timestamp())
            except Exception:
                return None
        return None

    def _patched_dispatch(self, raw):
        receive_time = time.time()
        with self._metrics_lock:
            self._last_message_at = receive_time
            self._message_count += 1

        msg_type, channel, parsed, data = _pkf._parse_message(raw)
        if msg_type is None:
            if not data:
                _pkf.logger.warning("Malformed message: %.200s", raw)
            return

        if msg_type == "subscribed":
            inner = data.get("msg", {})
            sid = inner.get("sid") if isinstance(inner, dict) else None
            if sid is not None:
                with self._lock:
                    params = self._pending_subs.pop(data.get("id"), None)
                    if params is not None:
                        self._sids[sid] = params
            return

        payload = data.get("msg", data)
        if isinstance(payload, dict):
            ts = payload.get("ts")
            coerced = _coerce_ts(ts)
            if coerced is not None:
                with self._metrics_lock:
                    self._last_server_ts = coerced

        handlers = self._handlers.get(channel)
        if not handlers:
            return

        for handler in handlers:
            try:
                handler(parsed)
            except Exception:
                _pkf.logger.exception("Handler error on channel %s", channel)

    _pkf.Feed._dispatch = _patched_dispatch
    _pkf.Feed._ts_patch_installed = True


_install_pykalshi_ts_patch()


@dataclass
class OrderBookLevel:
    """Single price level in the order book."""

    price: int
    quantity: int


@dataclass
class OrderBook:
    """Order book snapshot with analysis utilities."""

    ticker: str
    yes_bids: list[OrderBookLevel] = field(default_factory=list)
    no_bids: list[OrderBookLevel] = field(default_factory=list)
    timestamp: Optional[float] = None

    @classmethod
    def from_api_response(cls, ticker: str, data: dict) -> "OrderBook":
        yes_bids = [OrderBookLevel(price=level[0], quantity=level[1]) for level in (data.get("yes") or [])]
        yes_bids.sort(key=lambda x: x.price, reverse=True)

        no_bids = [OrderBookLevel(price=level[0], quantity=level[1]) for level in (data.get("no") or [])]
        no_bids.sort(key=lambda x: x.price, reverse=True)

        return cls(ticker=ticker, yes_bids=yes_bids, no_bids=no_bids, timestamp=time.time())

    @property
    def best_yes_bid(self) -> Optional[int]:
        return self.yes_bids[0].price if self.yes_bids else None

    @property
    def best_yes_ask(self) -> Optional[int]:
        if not self.no_bids:
            return None
        return 100 - self.no_bids[0].price

    @property
    def best_no_bid(self) -> Optional[int]:
        return self.no_bids[0].price if self.no_bids else None

    @property
    def best_no_ask(self) -> Optional[int]:
        if not self.yes_bids:
            return None
        return 100 - self.yes_bids[0].price

    @property
    def spread(self) -> Optional[int]:
        if self.best_yes_bid is None or self.best_yes_ask is None:
            return None
        return self.best_yes_ask - self.best_yes_bid

    @property
    def midpoint(self) -> Optional[float]:
        if self.best_yes_bid is None or self.best_yes_ask is None:
            return None
        return (self.best_yes_bid + self.best_yes_ask) / 2

    def yes_ask_levels(self) -> list[OrderBookLevel]:
        """Convert NO bids to YES ask levels (price = 100 - no_bid_price)."""
        levels = [
            OrderBookLevel(price=(100 - level.price), quantity=level.quantity)
            for level in self.no_bids
        ]
        levels.sort(key=lambda level: level.price)
        return levels


def _dollars_to_cents_levels(levels):
    """Convert dollar-priced levels [[price_dollars, qty], ...] to cents."""
    if not levels:
        return []
    out = []
    for p, q in levels:
        p_float = float(p)
        if p_float < 1.01:  # dollar-priced (0.01 - 1.00)
            out.append([int(round(p_float * 100)), int(q)])
        else:  # already in cents
            out.append([int(p), int(q)])
    return out


def _parse_price(msg) -> int:
    """Extract price in cents from a delta message."""
    if hasattr(msg, "price_dollars"):
        return int(round(float(msg.price_dollars) * 100))
    return int(getattr(msg, "price", 0))


def _parse_delta(msg) -> int:
    """Extract quantity delta from a delta message."""
    if hasattr(msg, "delta_fp"):
        return int(round(float(msg.delta_fp)))
    return int(getattr(msg, "delta", 0))


class OrderBookStream:
    """WebSocket client for streaming order book updates."""

    def __init__(
        self,
        api_key_id: str,
        private_key_pem: str,
        tickers: list[str],
        on_update: Callable[[OrderBook], Any],
        on_trade: Optional[Callable[[dict], Any]] = None,
        on_raw_snapshot: Optional[Callable] = None,
        on_raw_delta: Optional[Callable] = None,
        on_raw_trade: Optional[Callable] = None,
        demo: bool = False,
    ):
        self.api_key_id = api_key_id
        self.private_key_pem = private_key_pem
        self.tickers = tickers
        self.on_update = on_update
        self.on_trade = on_trade
        self.on_raw_snapshot = on_raw_snapshot
        self.on_raw_delta = on_raw_delta
        self.on_raw_trade = on_raw_trade
        self.demo = demo

        self._books: dict[str, OrderBook] = {}
        self._books_lock = threading.Lock()
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._feed: Optional[Feed] = None
        self._key_path: Optional[str] = None

    def _ensure_client(self) -> KalshiClient:
        if self._key_path is None:
            handle = tempfile.NamedTemporaryFile("w", delete=False, suffix=".pem")
            handle.write(self.private_key_pem)
            handle.flush()
            handle.close()
            os.chmod(handle.name, 0o600)
            self._key_path = handle.name

        return KalshiClient(
            api_key_id=self.api_key_id,
            private_key_path=self._key_path,
            demo=self.demo,
        )

    def _cleanup(self) -> None:
        if self._key_path and os.path.exists(self._key_path):
            try:
                os.remove(self._key_path)
            except OSError:
                pass
        self._key_path = None

    def _apply_snapshot(self, ticker: str, yes_levels, no_levels) -> None:
        yes_bids = [OrderBookLevel(price=p, quantity=q) for p, q in (yes_levels or [])]
        yes_bids.sort(key=lambda x: x.price, reverse=True)
        no_bids = [OrderBookLevel(price=p, quantity=q) for p, q in (no_levels or [])]
        no_bids.sort(key=lambda x: x.price, reverse=True)
        with self._books_lock:
            self._books[ticker] = OrderBook(
                ticker=ticker,
                yes_bids=yes_bids,
                no_bids=no_bids,
                timestamp=time.time(),
            )

    def _apply_delta(self, ticker: str, side: str, price: int, delta: int) -> None:
        with self._books_lock:
            book = self._books.get(ticker)
            if book is None:
                return

            side = side.lower()
            levels = book.yes_bids if side == "yes" else book.no_bids
            for index, level in enumerate(levels):
                if level.price == price:
                    updated_qty = level.quantity + delta
                    if updated_qty <= 0:
                        levels.pop(index)
                    else:
                        level.quantity = updated_qty
                    break
            else:
                if delta > 0:
                    levels.append(OrderBookLevel(price=price, quantity=delta))
                    levels.sort(key=lambda x: x.price, reverse=True)

            book.timestamp = time.time()

    def _emit_update(self, ticker: str) -> None:
        with self._books_lock:
            book = self._books.get(ticker)

        if book is None:
            return

        if asyncio.iscoroutinefunction(self.on_update):
            if self._loop:
                asyncio.run_coroutine_threadsafe(self.on_update(book), self._loop)
        else:
            self.on_update(book)

    def _emit_trade(self, payload: dict) -> None:
        if self.on_trade is None:
            return
        if asyncio.iscoroutinefunction(self.on_trade):
            if self._loop:
                asyncio.run_coroutine_threadsafe(self.on_trade(payload), self._loop)
        else:
            self.on_trade(payload)

    async def run(self):
        client = self._ensure_client()
        feed = Feed(client)
        self._feed = feed
        self._running = True
        self._loop = asyncio.get_running_loop()

        @feed.on("orderbook_delta")
        def _on_orderbook(msg):
            if isinstance(msg, OrderbookSnapshotMessage):
                ticker = getattr(msg, "market_ticker", None)
                if not ticker:
                    return
                if self.on_raw_snapshot is not None:
                    self.on_raw_snapshot(msg)
                # SDK uses yes_dollars/no_dollars with dollar-priced levels
                yes_raw = getattr(msg, "yes_dollars", None) or getattr(msg, "yes", None)
                no_raw = getattr(msg, "no_dollars", None) or getattr(msg, "no", None)
                yes_levels = _dollars_to_cents_levels(yes_raw)
                no_levels = _dollars_to_cents_levels(no_raw)
                self._apply_snapshot(ticker, yes_levels, no_levels)
                self._emit_update(ticker)
            elif isinstance(msg, OrderbookDeltaMessage):
                ticker = getattr(msg, "market_ticker", None)
                if not ticker:
                    return
                if self.on_raw_delta is not None:
                    self.on_raw_delta(msg)
                # SDK uses price_dollars/delta_fp
                price = _parse_price(msg)
                delta = _parse_delta(msg)
                side = getattr(msg, "side", "yes")
                self._apply_delta(ticker, side, price, delta)
                self._emit_update(ticker)
            elif isinstance(msg, dict):
                # Kalshi WS API may send dicts with price_dollars/delta_fp
                # when pykalshi model validation fails on the new format
                ticker = msg.get("market_ticker")
                if not ticker:
                    return
                if "yes" in msg or "no" in msg:
                    # Snapshot dict
                    if self.on_raw_snapshot is not None:
                        self.on_raw_snapshot(msg)
                    self._apply_snapshot(
                        ticker,
                        msg.get("yes"),
                        msg.get("no"),
                    )
                    self._emit_update(ticker)
                elif "price_dollars" in msg or "price" in msg:
                    # Delta dict (new format: price_dollars + delta_fp)
                    if "price_dollars" in msg:
                        price = int(round(float(msg["price_dollars"]) * 100))
                        delta = int(round(float(msg.get("delta_fp", 0))))
                    else:
                        price = int(msg["price"])
                        delta = int(msg.get("delta", 0))
                    side = msg.get("side", "yes")
                    if self.on_raw_delta is not None:
                        self.on_raw_delta(msg)
                    self._apply_delta(ticker, side, price, delta)
                    self._emit_update(ticker)

        @feed.on("trade")
        def _on_trade(msg):
            if self.on_raw_trade is not None:
                self.on_raw_trade(msg)
            if hasattr(msg, "model_dump"):
                payload = msg.model_dump(mode="json")
            elif hasattr(msg, "__dict__"):
                payload = {k: v for k, v in msg.__dict__.items() if not k.startswith("_")}
            else:
                payload = {"message": str(msg)}
            self._emit_trade(payload)

        for ticker in self.tickers:
            feed.subscribe("orderbook_delta", market_ticker=ticker)
            if self.on_trade is not None or self.on_raw_trade is not None:
                feed.subscribe("trade", market_ticker=ticker)

        feed.start()
        try:
            while self._running:
                await asyncio.sleep(0.25)
        finally:
            try:
                feed.stop()
            finally:
                self._feed = None
                self._loop = None
                self._running = False
                self._cleanup()

    def stop(self):
        self._running = False
        if self._feed is not None:
            self._feed.stop()

    def get_book(self, ticker: str) -> Optional[OrderBook]:
        with self._books_lock:
            return self._books.get(ticker)
