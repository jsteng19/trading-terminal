"""Market browsing endpoints."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, Query

from backend.dependencies import get_market_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets", tags=["markets"])

# Cache for mention series tickers (discovered once per restart)
_mention_series_cache: list[str] = []

# Cache for aggregated events (refreshed every 60s)
_events_cache: list[dict] = []
_events_cache_ts: float = 0
_EVENTS_CACHE_TTL = 60  # seconds


def _event_to_dict(event) -> dict:
    """Convert a pykalshi Event object to a JSON-serializable dict."""
    if isinstance(event, dict):
        return event
    if hasattr(event, "model_dump"):
        return event.model_dump(mode="json")
    if hasattr(event, "__dict__"):
        return {k: v for k, v in event.__dict__.items() if not k.startswith("_")}
    return {"value": str(event)}


def _get_field(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _discover_mention_series() -> list[str]:
    """Scan all Kalshi series and return those with 'mention' in the ticker."""
    global _mention_series_cache
    if _mention_series_cache:
        return _mention_series_cache

    md = get_market_data()
    try:
        all_series = md.get_series_list()
        _mention_series_cache = [
            _get_field(s, "ticker")
            for s in all_series
            if "mention" in (_get_field(s, "ticker") or "").lower()
        ]
        logger.info("Discovered %d mention series", len(_mention_series_cache))
    except Exception as exc:
        logger.error("Failed to discover mention series: %s", exc)
    return _mention_series_cache


def _fetch_events_for_series(series_ticker: str, status: str) -> list:
    """Fetch open events for one series (used in thread pool)."""
    md = get_market_data()
    try:
        return list(md.get_events(series_ticker=series_ticker, status=status, limit=50))
    except Exception:
        return []


def _get_mention_events(status: str = "open") -> list[dict]:
    """Get all mention events, with caching and parallel fetching."""
    global _events_cache, _events_cache_ts

    now = time.time()
    if _events_cache and (now - _events_cache_ts) < _EVENTS_CACHE_TTL:
        return _events_cache

    mention_series = _discover_mention_series()
    all_events = []
    seen = set()

    t0 = time.time()
    # Parallel fetch across all mention series (max 20 threads)
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {
            pool.submit(_fetch_events_for_series, st, status): st
            for st in mention_series
        }
        for future in as_completed(futures):
            for e in future.result():
                ticker = _get_field(e, "event_ticker")
                if ticker and ticker not in seen:
                    seen.add(ticker)
                    all_events.append(e)

    logger.info("Fetched %d mention events in %.1fs", len(all_events), time.time() - t0)

    # Sort by event_ticker descending (most recent first)
    all_events.sort(key=lambda e: _get_field(e, "event_ticker") or "", reverse=True)
    result = [_event_to_dict(e) for e in all_events]

    _events_cache = result
    _events_cache_ts = now
    return result


@router.get("/events")
def list_events(
    series_ticker: str = Query(None),
    status: str = Query("open"),
    limit: int = Query(200),
):
    """List mention events, aggregated across all discovered mention series."""
    if series_ticker:
        md = get_market_data()
        events = md.get_events(series_ticker=series_ticker, status=status, limit=limit)
        return {"events": [_event_to_dict(e) for e in events]}

    return {"events": _get_mention_events(status)}


@router.get("/event/{event_ticker}")
def get_event(event_ticker: str):
    """Get a single event."""
    md = get_market_data()
    event = md.get_event(event_ticker)
    return {"event": _event_to_dict(event)}


@router.get("/event/{event_ticker}/markets")
def list_markets(event_ticker: str):
    """List all markets for an event."""
    md = get_market_data()
    markets = md.get_markets(event_ticker=event_ticker)
    return {"markets": markets}


@router.get("/market/{ticker}")
def get_market(ticker: str):
    """Get a single market with stats."""
    md = get_market_data()
    return {"market": md.get_market_stats(ticker)}


@router.get("/market/{ticker}/orderbook")
def get_orderbook(ticker: str, depth: int = Query(20)):
    """Get orderbook snapshot for a market."""
    md = get_market_data()
    return {"orderbook": md.get_orderbook(ticker, depth=depth)}


@router.get("/market/{ticker}/trades")
def get_trades(
    ticker: str,
    limit: int = Query(200),
):
    """Get recent trades for a market."""
    md = get_market_data()
    trades = md.get_trades(ticker=ticker, limit=limit)
    return {"trades": trades}
