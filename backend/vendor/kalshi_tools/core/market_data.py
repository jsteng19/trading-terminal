"""High-level market data helpers on top of `pykalshi`."""

from dataclasses import dataclass
from datetime import datetime
from math import floor
import time
from typing import Iterator, Optional
from urllib.parse import urlencode

import pandas as pd
from pykalshi import CandlestickPeriod, KalshiClient, MarketStatus
from pykalshi._utils import normalize_ticker


def _get_field(obj, field_name: str, default=None):
    if hasattr(obj, field_name):
        return getattr(obj, field_name)
    if isinstance(obj, dict):
        return obj.get(field_name, default)
    return default


def _to_record(obj):
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if hasattr(obj, "data") and hasattr(obj.data, "model_dump"):
        return obj.data.model_dump(mode="json")
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return {"value": obj}


def _normalize_trade(raw: dict) -> dict:
    """Normalize Kalshi trades API response to legacy field names.

    The API now returns ``count_fp``, ``yes_price_dollars``, and
    ``no_price_dollars`` (all strings) instead of the previous ``count``,
    ``yes_price``, and ``no_price`` (integers in cents).  Convert back to the
    integer-cents schema the rest of the codebase expects.
    """
    out = dict(raw)

    # count_fp -> count  (string "11.00" -> int 11)
    if "count" not in out and "count_fp" in out:
        out["count"] = int(float(out.pop("count_fp")))
    elif "count_fp" in out:
        out.pop("count_fp")

    # yes_price_dollars -> yes_price  (string "0.4900" -> int 49)
    if "yes_price" not in out and "yes_price_dollars" in out:
        out["yes_price"] = round(float(out.pop("yes_price_dollars")) * 100)
    elif "yes_price_dollars" in out:
        out.pop("yes_price_dollars")

    # no_price_dollars -> no_price  (string "0.5100" -> int 51)
    if "no_price" not in out and "no_price_dollars" in out:
        out["no_price"] = round(float(out.pop("no_price_dollars")) * 100)
    elif "no_price_dollars" in out:
        out.pop("no_price_dollars")

    return out


def _normalize_orderbook(raw: dict) -> dict:
    """Normalize Kalshi orderbook API response to legacy field names.

    The API now returns ``orderbook_fp`` with ``yes_dollars``/``no_dollars``
    (string pairs) instead of ``orderbook`` with ``yes``/``no`` (int pairs in
    cents).  Convert back to the integer-cents schema the rest of the codebase
    expects.
    """
    # Legacy format already present
    if "orderbook" in raw and "orderbook_fp" not in raw:
        book = raw["orderbook"]
        return {"yes": book.get("yes", []), "no": book.get("no", [])}

    book = raw.get("orderbook_fp", raw.get("orderbook", {}))
    yes_raw = book.get("yes_dollars", book.get("yes", []))
    no_raw = book.get("no_dollars", book.get("no", []))

    def _convert_levels(levels):
        out = []
        for pair in levels:
            price_cents = round(float(pair[0]) * 100)
            qty = int(float(pair[1]))
            out.append([price_cents, qty])
        return out

    return {"yes": _convert_levels(yes_raw), "no": _convert_levels(no_raw)}


def _normalize_market(raw: dict) -> dict:
    """Normalize Kalshi market API response to legacy field names.

    The API now returns dollar-string fields (``yes_bid_dollars``,
    ``volume_fp``, etc.) instead of the old integer-cents / integer fields.
    Convert to the schema the rest of the codebase expects.
    """
    out = dict(raw)

    def _cents(key_dollars: str, key_legacy: str):
        if key_legacy not in out and key_dollars in out:
            val = out.pop(key_dollars)
            out[key_legacy] = round(float(val) * 100) if val else None
        elif key_dollars in out:
            out.pop(key_dollars)

    def _int_fp(key_fp: str, key_legacy: str):
        if key_legacy not in out and key_fp in out:
            val = out.pop(key_fp)
            out[key_legacy] = int(float(val)) if val else None
        elif key_fp in out:
            out.pop(key_fp)

    _cents("yes_bid_dollars", "yes_bid")
    _cents("yes_ask_dollars", "yes_ask")
    _cents("no_bid_dollars", "no_bid")
    _cents("no_ask_dollars", "no_ask")
    _cents("last_price_dollars", "last_price")
    _cents("previous_price_dollars", "previous_price")
    _cents("previous_yes_bid_dollars", "previous_yes_bid")
    _cents("previous_yes_ask_dollars", "previous_yes_ask")
    _cents("notional_value_dollars", "notional_value")
    _cents("liquidity_dollars", "liquidity")
    _int_fp("volume_fp", "volume")
    _int_fp("volume_24h_fp", "volume_24h")
    _int_fp("open_interest_fp", "open_interest")
    _int_fp("yes_ask_size_fp", "yes_ask_size")
    _int_fp("yes_bid_size_fp", "yes_bid_size")

    return out


def _normalize_position(raw: dict) -> dict:
    """Normalize Kalshi position API response to legacy field names."""
    out = dict(raw)
    if "position" not in out and "position_fp" in out:
        out["position"] = int(float(out.pop("position_fp")))
    elif "position_fp" in out:
        out.pop("position_fp")
    return out


def _normalize_fill(raw: dict) -> dict:
    """Normalize Kalshi fill API response to legacy field names."""
    out = dict(raw)

    if "count" not in out and "count_fp" in out:
        out["count"] = int(float(out.pop("count_fp")))
    elif "count_fp" in out:
        out.pop("count_fp")

    if "yes_price" not in out and "yes_price_dollars" in out:
        out["yes_price"] = round(float(out.pop("yes_price_dollars")) * 100)
    elif "yes_price_dollars" in out:
        out.pop("yes_price_dollars")

    if "no_price" not in out and "no_price_dollars" in out:
        out["no_price"] = round(float(out.pop("no_price_dollars")) * 100)
    elif "no_price_dollars" in out:
        out.pop("no_price_dollars")

    # Also normalize yes_price_fixed / no_price_fixed if present
    if "yes_price_fixed" in out:
        out.pop("yes_price_fixed")
    if "no_price_fixed" in out:
        out.pop("no_price_fixed")

    return out


def _normalize_order(raw: dict) -> dict:
    """Normalize Kalshi order API response to legacy field names."""
    out = dict(raw)

    if "yes_price" not in out and "yes_price_dollars" in out:
        out["yes_price"] = round(float(out.pop("yes_price_dollars")) * 100)
    elif "yes_price_dollars" in out:
        out.pop("yes_price_dollars")

    if "no_price" not in out and "no_price_dollars" in out:
        out["no_price"] = round(float(out.pop("no_price_dollars")) * 100)
    elif "no_price_dollars" in out:
        out.pop("no_price_dollars")

    def _int_fp(key_fp: str, key_legacy: str):
        if key_legacy not in out and key_fp in out:
            val = out.pop(key_fp)
            out[key_legacy] = int(float(val)) if val else None
        elif key_fp in out:
            out.pop(key_fp)

    _int_fp("initial_count_fp", "initial_count")
    _int_fp("remaining_count_fp", "remaining_count")
    _int_fp("fill_count_fp", "fill_count")

    return out


def _coerce_market_status(status: Optional[str | MarketStatus]) -> Optional[MarketStatus]:
    if status is None:
        return None
    if isinstance(status, MarketStatus):
        return status
    return MarketStatus(str(status).lower())


def _coerce_period(period_interval: int | CandlestickPeriod) -> CandlestickPeriod:
    if isinstance(period_interval, CandlestickPeriod):
        return period_interval
    mapping = {
        1: CandlestickPeriod.ONE_MINUTE,
        60: CandlestickPeriod.ONE_HOUR,
        1440: CandlestickPeriod.ONE_DAY,
    }
    return mapping.get(int(period_interval), CandlestickPeriod.ONE_HOUR)


@dataclass
class MarketData:
    """Convenience layer for series/events/markets/trades/orderbook/candles."""

    client: KalshiClient

    def get_series_list(self, category: Optional[str] = None) -> list:
        return list(self.client.get_all_series(category=category, fetch_all=True))

    def get_series(self, series_ticker: str):
        return self.client.get_series(series_ticker)

    def get_events(
        self,
        series_ticker: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> list:
        return list(
            self.client.get_events(
                series_ticker=series_ticker,
                status=_coerce_market_status(status),
                limit=limit,
            )
        )

    def get_event(self, event_ticker: str):
        return self.client.get_event(event_ticker)

    def get_markets(
        self,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        fetch_all: bool = False,
    ) -> list[dict]:
        params = {
            "event_ticker": normalize_ticker(event_ticker),
            "series_ticker": normalize_ticker(series_ticker),
            "status": _coerce_market_status(status).value if status else None,
            "limit": limit,
        }
        raw = self.client.paginated_get("/markets", "markets", params, fetch_all=fetch_all)
        return [_normalize_market(m) for m in raw]

    def get_markets_paginated(
        self,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 500,
        max_pages: int = 5,
        page_sleep: float = 0.35,
    ) -> list[dict]:
        """Fetch markets with explicit page and delay controls.

        This is safer for broad universe scans than ``fetch_all=True`` because
        open-market enumeration can span enough pages to trip REST rate limits.
        """
        if max_pages <= 0:
            return []

        params = {
            "event_ticker": normalize_ticker(event_ticker),
            "series_ticker": normalize_ticker(series_ticker),
            "status": _coerce_market_status(status).value if status else None,
            "limit": limit,
        }
        raw: list[dict] = []
        cursor: Optional[str] = None

        for page_idx in range(max_pages):
            if cursor:
                params["cursor"] = cursor
            filtered = {k: v for k, v in params.items() if v is not None}
            endpoint = f"/markets?{urlencode(filtered)}"
            response = self.client.get(endpoint)
            raw.extend(response.get("markets", []))
            cursor = response.get("cursor") or None
            if not cursor:
                break
            if page_sleep > 0 and page_idx < max_pages - 1:
                time.sleep(page_sleep)

        return [_normalize_market(m) for m in raw]

    def get_market(self, ticker: str) -> dict:
        raw = self.client.get(f"/markets/{normalize_ticker(ticker)}")
        market_data = raw.get("market", raw)
        return _normalize_market(market_data)

    def _raw_trades(
        self,
        ticker: Optional[str] = None,
        min_ts: Optional[int] = None,
        max_ts: Optional[int] = None,
        limit: int = 1000,
        fetch_all: bool = False,
    ) -> list[dict]:
        """Fetch trades via raw paginated GET, bypassing pykalshi TradeModel."""
        params = {
            "limit": limit,
            "ticker": normalize_ticker(ticker),
            "min_ts": min_ts,
            "max_ts": max_ts,
        }
        raw = self.client.paginated_get(
            "/markets/trades", "trades", params, fetch_all,
        )
        return [_normalize_trade(t) for t in raw]

    def get_trades(
        self,
        ticker: Optional[str] = None,
        min_ts: Optional[int] = None,
        max_ts: Optional[int] = None,
        limit: int = 1000,
    ) -> list[dict]:
        return self._raw_trades(
            ticker=ticker, min_ts=min_ts, max_ts=max_ts, limit=limit,
        )

    def get_all_trades(
        self,
        ticker: str,
        min_ts: Optional[int] = None,
        max_ts: Optional[int] = None,
    ) -> Iterator[dict]:
        yield from self._raw_trades(
            ticker=ticker, min_ts=min_ts, max_ts=max_ts,
            limit=1000, fetch_all=True,
        )

    def get_trades_df(
        self,
        ticker: str,
        min_ts: Optional[int] = None,
        max_ts: Optional[int] = None,
    ) -> pd.DataFrame:
        trades = list(self.get_all_trades(ticker, min_ts, max_ts))
        if not trades:
            return pd.DataFrame()
        records = [_to_record(t) for t in trades]
        df = pd.DataFrame(records)
        if "created_time" in df.columns:
            df["created_time"] = pd.to_datetime(df["created_time"], errors="coerce", utc=True)
        return df

    def get_market_stats(self, ticker: str) -> dict:
        market = self.get_market(ticker)
        yes_bid = _get_field(market, "yes_bid")
        yes_ask = _get_field(market, "yes_ask")
        return {
            "ticker": _get_field(market, "ticker"),
            "open_interest": _get_field(market, "open_interest"),
            "volume": _get_field(market, "volume"),
            "volume_24h": _get_field(market, "volume_24h"),
            "last_price": _get_field(market, "last_price"),
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": _get_field(market, "no_bid"),
            "no_ask": _get_field(market, "no_ask"),
            "spread": yes_ask - yes_bid if yes_bid is not None and yes_ask is not None else None,
            "liquidity": _get_field(market, "liquidity"),
        }

    def get_positions(
        self,
        ticker: Optional[str] = None,
        event_ticker: Optional[str] = None,
        subaccount: Optional[int] = None,
        fetch_all: bool = True,
    ) -> list[dict]:
        """Fetch portfolio positions via raw API."""
        params: dict = {"limit": 1000}
        if ticker:
            params["ticker"] = normalize_ticker(ticker)
        if event_ticker:
            params["event_ticker"] = normalize_ticker(event_ticker)
        if subaccount is not None:
            params["subaccount"] = subaccount
        raw = self.client.paginated_get(
            "/portfolio/positions", "market_positions", params, fetch_all,
        )
        return [_normalize_position(p) for p in raw]

    def get_fills(
        self,
        ticker: Optional[str] = None,
        min_ts: Optional[int] = None,
        subaccount: Optional[int] = None,
        fetch_all: bool = True,
    ) -> list[dict]:
        """Fetch portfolio fills via raw API."""
        params: dict = {"limit": 200}
        if ticker:
            params["ticker"] = normalize_ticker(ticker)
        if min_ts is not None:
            params["min_ts"] = min_ts
        if subaccount is not None:
            params["subaccount"] = subaccount
        raw = self.client.paginated_get(
            "/portfolio/fills", "fills", params, fetch_all,
        )
        return [_normalize_fill(f) for f in raw]

    def get_orders(
        self,
        ticker: Optional[str] = None,
        event_ticker: Optional[str] = None,
        status: Optional[str] = None,
        subaccount: Optional[int] = None,
        fetch_all: bool = True,
    ) -> list[dict]:
        """Fetch portfolio orders via raw API."""
        params: dict = {"limit": 200}
        if ticker:
            params["ticker"] = normalize_ticker(ticker)
        if event_ticker:
            params["event_ticker"] = normalize_ticker(event_ticker)
        if status:
            params["status"] = status
        if subaccount is not None:
            params["subaccount"] = subaccount
        raw = self.client.paginated_get(
            "/portfolio/orders", "orders", params, fetch_all,
        )
        return [_normalize_order(o) for o in raw]

    def get_orderbook(self, ticker: str, depth: int = 10) -> dict:
        endpoint = f"/markets/{normalize_ticker(ticker)}/orderbook?depth={depth}"
        raw = self.client.get(endpoint)
        return _normalize_orderbook(raw)

    def get_candlesticks(
        self,
        ticker: str,
        period_interval: int = 60,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> list:
        if start_ts is None or end_ts is None:
            return []
        market = self.client.get_market(ticker=ticker)
        return list(
            market.get_candlesticks(
                start_ts=start_ts,
                end_ts=end_ts,
                period=_coerce_period(period_interval),
            ).candlesticks
        )

    def get_candlesticks_df(
        self,
        ticker: str,
        period_interval: int = 60,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> pd.DataFrame:
        candles = self.get_candlesticks(ticker, period_interval, start_ts, end_ts)
        if not candles:
            return pd.DataFrame()
        records = [_to_record(c) for c in candles]
        df = pd.DataFrame(records)
        if "end_period_ts" in df.columns:
            df["timestamp"] = pd.to_datetime(df["end_period_ts"], unit="s", utc=True, errors="coerce")
        return df

    def get_event_markets(self, event_ticker: str) -> list:
        markets = self.get_markets(event_ticker=event_ticker)
        return sorted(markets, key=lambda m: _get_field(m, "volume", 0) or 0, reverse=True)

    def find_markets_by_subtitle(self, event_ticker: str, subtitle_contains: str) -> list:
        markets = self.get_markets(event_ticker=event_ticker)
        query = subtitle_contains.lower()
        filtered = []
        for market in markets:
            subtitle = (_get_field(market, "yes_sub_title", "") or "").lower()
            title = (_get_field(market, "title", "") or "").lower()
            if query in f"{subtitle} {title}":
                filtered.append(market)
        return filtered

    def get_active_markets(self, limit: int = 100) -> list:
        markets = self.get_markets(status="open", limit=limit)
        return sorted(markets, key=lambda m: _get_field(m, "volume", 0) or 0, reverse=True)

    def timestamp_to_datetime(self, ts: int) -> datetime:
        return datetime.fromtimestamp(ts)
