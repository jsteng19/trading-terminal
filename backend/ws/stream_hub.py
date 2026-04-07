"""StreamHub: bridges Kalshi OrderBookStream to browser WebSocket clients.

Manages one OrderBookStream per event, reference-counted by connected clients.
Coalesces orderbook updates at a configurable rate; trades are forwarded immediately.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from backend.config import BOOK_UPDATE_RATE_HZ, STREAM_GRACE_PERIOD_S
from backend.lazy_import import lazy_import
from backend.ws.manager import ConnectionManager

logger = logging.getLogger(__name__)

_orderbook_mod = lazy_import("kalshi_tools.analysis.orderbook")
OrderBookStream = _orderbook_mod.OrderBookStream
OrderBook = _orderbook_mod.OrderBook


def _book_to_dict(book: OrderBook) -> dict:
    """Convert an OrderBook to a JSON-serializable dict."""
    return {
        "ticker": book.ticker,
        "yes_bids": [[l.price, l.quantity] for l in book.yes_bids],
        "no_bids": [[l.price, l.quantity] for l in book.no_bids],
        "best_yes_bid": book.best_yes_bid,
        "best_yes_ask": book.best_yes_ask,
        "best_no_bid": book.best_no_bid,
        "best_no_ask": book.best_no_ask,
        "spread": book.spread,
        "midpoint": book.midpoint,
        "ts": book.timestamp,
    }


@dataclass
class EventStream:
    """Tracks an OrderBookStream and its coalescing state for one event."""
    event_ticker: str
    tickers: list[str]
    stream: Optional[OrderBookStream] = None
    task: Optional[asyncio.Task] = None
    flush_task: Optional[asyncio.Task] = None
    latest_books: dict[str, dict] = field(default_factory=dict)
    dirty_tickers: set[str] = field(default_factory=set)
    last_flush: float = 0.0


class StreamHub:
    """Central manager for all OrderBookStream instances."""

    def __init__(self, ws_manager: ConnectionManager):
        self.ws_manager = ws_manager
        self._streams: dict[str, EventStream] = {}
        self._flush_interval = 1.0 / BOOK_UPDATE_RATE_HZ

    async def subscribe(self, event_ticker: str, tickers: list[str]):
        """Start streaming for an event if not already running."""
        if event_ticker in self._streams:
            return

        api_key_id = os.environ.get("KALSHI_API_KEY_ID", "")
        private_key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "")
        if not api_key_id or not private_key_path:
            logger.error("Missing Kalshi credentials for WebSocket stream")
            return

        from pathlib import Path
        key_path = Path(private_key_path).expanduser()
        private_key_pem = key_path.read_text()

        demo = os.environ.get("TERMINAL_DEMO", "0") == "1"

        es = EventStream(event_ticker=event_ticker, tickers=tickers)

        # Capture the running event loop NOW (we're in an async context)
        loop = asyncio.get_running_loop()

        def on_update(book: OrderBook):
            es.latest_books[book.ticker] = _book_to_dict(book)
            es.dirty_tickers.add(book.ticker)

        def on_trade(payload: dict):
            # Forward trades immediately (no coalescing)
            # Note: this callback runs in pykalshi's Feed thread, not the asyncio loop
            try:
                asyncio.run_coroutine_threadsafe(
                    self.ws_manager.broadcast(event_ticker, {
                        "type": "trade",
                        "ticker": payload.get("market_ticker", ""),
                        "data": {
                            "side": payload.get("taker_side", ""),
                            "yes_price": payload.get("yes_price"),
                            "no_price": payload.get("no_price"),
                            "count": payload.get("count"),
                            "ts": payload.get("ts", time.time()),
                        },
                    }),
                    loop,
                )
            except RuntimeError:
                pass  # Loop closed during shutdown

        es.stream = OrderBookStream(
            api_key_id=api_key_id,
            private_key_pem=private_key_pem,
            tickers=tickers,
            on_update=on_update,
            on_trade=on_trade,
            demo=demo,
        )

        self._streams[event_ticker] = es
        es.task = asyncio.create_task(self._run_stream(es))
        es.flush_task = asyncio.create_task(self._flush_loop(es))
        logger.info("Started stream for event=%s with %d tickers", event_ticker, len(tickers))

    async def _run_stream(self, es: EventStream):
        """Run the OrderBookStream in the current event loop."""
        try:
            await es.stream.run()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Stream error for event=%s", es.event_ticker)

    async def _flush_loop(self, es: EventStream):
        """Periodically flush coalesced book updates to WS clients."""
        try:
            while True:
                await asyncio.sleep(self._flush_interval)
                if not es.dirty_tickers:
                    continue

                dirty = list(es.dirty_tickers)
                es.dirty_tickers.clear()

                for ticker in dirty:
                    book_data = es.latest_books.get(ticker)
                    if book_data:
                        await self.ws_manager.broadcast(es.event_ticker, {
                            "type": "book",
                            "ticker": ticker,
                            "data": book_data,
                        })
        except asyncio.CancelledError:
            pass

    async def unsubscribe(self, event_ticker: str):
        """Stop streaming for an event."""
        es = self._streams.pop(event_ticker, None)
        if es is None:
            return
        if es.flush_task:
            es.flush_task.cancel()
        if es.task:
            es.task.cancel()
        if es.stream:
            es.stream._running = False
            es.stream._cleanup()
        logger.info("Stopped stream for event=%s", event_ticker)

    async def cleanup_unused(self):
        """Stop streams that have no connected clients."""
        for key in list(self._streams.keys()):
            if self.ws_manager.subscriber_count(key) == 0:
                logger.info("No subscribers for event=%s, stopping stream", key)
                await self.unsubscribe(key)

    def active_events(self) -> list[str]:
        return list(self._streams.keys())

    def get_latest_book(self, event_ticker: str, ticker: str) -> Optional[dict]:
        es = self._streams.get(event_ticker)
        if es:
            return es.latest_books.get(ticker)
        return None
