"""Helpers to resolve event cutoffs for live orchestration configs."""

from __future__ import annotations

import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from html import unescape
from typing import Any, Optional
from zoneinfo import ZoneInfo


PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

_FIXED_OFFSET_TZS = {
    "UTC": timezone.utc,
    "GMT": timezone.utc,
    "EST": timezone(timedelta(hours=-5)),
    "EDT": timezone(timedelta(hours=-4)),
    "CST": timezone(timedelta(hours=-6)),
    "CDT": timezone(timedelta(hours=-5)),
    "MST": timezone(timedelta(hours=-7)),
    "MDT": timezone(timedelta(hours=-6)),
    "PST": timezone(timedelta(hours=-8)),
    "PDT": timezone(timedelta(hours=-7)),
}

_REGION_TZS = {
    "ET": ZoneInfo("America/New_York"),
    "CT": ZoneInfo("America/Chicago"),
    "MT": ZoneInfo("America/Denver"),
    "PT": PACIFIC_TZ,
}

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

_TIMESTAMP_FIELDS = (
    "event_start_time",
    "start_time",
    "starts_at",
    "begins_at",
    "begin_time",
    "start_datetime",
)

_HTML_START_PATTERNS = (
    re.compile(r'"beginsAt"\s*:\s*"([^"]+)"', re.IGNORECASE),
    re.compile(r'"begins_at"\s*:\s*"([^"]+)"', re.IGNORECASE),
    re.compile(
        r"Begins(?:\s+in\s+[0-9dhms:\s]+)?\s+"
        r"([A-Za-z]{3}\s+\d{1,2},\s+\d{1,2}:\d{2}\s*[ap]m\s+[A-Za-z]{2,4})",
        re.IGNORECASE,
    ),
)


def _looks_like_challenge_page(html_text: str) -> bool:
    text = html_text.lower()
    return (
        "security checkpoint" in text
        or "verifying your browser" in text
        or "x-vercel-challenge-token" in text
    )


def _get_field(obj: Any, field_name: str, default: Any = None) -> Any:
    if hasattr(obj, field_name):
        return getattr(obj, field_name)
    if isinstance(obj, dict):
        return obj.get(field_name, default)
    return default


def _parse_iso8601_utc(value: str) -> datetime:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("missing datetime value")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _slugify(value: str) -> str:
    norm = unicodedata.normalize("NFKD", value or "")
    ascii_value = norm.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return cleaned


def _decode_js_escapes(text: str) -> str:
    if not text:
        return text
    decoded = text.replace(r"\/", "/").replace(r"\\", "\\").replace(r"\'", "'").replace(r"\"", '"')

    def _replace_unicode(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    return re.sub(r"\\u([0-9a-fA-F]{4})", _replace_unicode, decoded)


def _search_text_candidates(html_text: str) -> list[str]:
    unescaped = unescape(html_text)
    decoded = _decode_js_escapes(unescaped)
    if decoded == unescaped:
        return [unescaped]
    return [unescaped, decoded]


def _choose_year(month: int, day: int, tzinfo, now_utc: datetime) -> int:
    local_now = now_utc.astimezone(tzinfo)
    candidate = datetime(local_now.year, month, day, tzinfo=tzinfo)
    if candidate < local_now - timedelta(days=180):
        return local_now.year + 1
    if candidate > local_now + timedelta(days=185):
        return local_now.year - 1
    return local_now.year


def _parse_month_day_time_token(token: str, now_utc: Optional[datetime] = None) -> Optional[datetime]:
    match = re.search(
        r"(?P<month>[A-Za-z]{3})\s+"
        r"(?P<day>\d{1,2}),\s+"
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*"
        r"(?P<ampm>[ap]m)\s+"
        r"(?P<tz>[A-Za-z]{2,4})",
        token,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    month = _MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    day = int(match.group("day"))
    hour12 = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = match.group("ampm").lower()
    tz_abbr = match.group("tz").upper()

    if hour12 < 1 or hour12 > 12 or minute < 0 or minute > 59:
        return None

    hour = hour12 % 12
    if ampm == "pm":
        hour += 12

    tzinfo = _FIXED_OFFSET_TZS.get(tz_abbr) or _REGION_TZS.get(tz_abbr)
    if tzinfo is None:
        return None

    now = now_utc or datetime.now(timezone.utc)
    year = _choose_year(month, day, tzinfo, now)
    try:
        local_dt = datetime(year, month, day, hour, minute, tzinfo=tzinfo)
    except ValueError:
        return None
    return local_dt.astimezone(timezone.utc)


def _extract_event_start_from_milestones(
    search_text: str,
    event_ticker: Optional[str],
) -> Optional[datetime]:
    target = (event_ticker or "").strip().upper()
    start_pattern = re.compile(r'"start_date"\s*:\s*"([^"]+)"', re.IGNORECASE)
    related_pattern = re.compile(r'"related_event_tickers"\s*:\s*\[([^\]]*)\]', re.IGNORECASE)
    ticker_pattern = re.compile(r'"([A-Z0-9-]+)"')

    for start_match in start_pattern.finditer(search_text):
        start_token = (start_match.group(1) or "").strip()
        if not start_token:
            continue

        if target:
            window = search_text[start_match.end(): start_match.end() + 1800]
            related_match = related_pattern.search(window)
            if related_match is None:
                continue
            related_tickers = {m.group(1).upper() for m in ticker_pattern.finditer(related_match.group(1))}
            if target not in related_tickers:
                continue

        try:
            return _parse_iso8601_utc(start_token)
        except ValueError:
            continue
    return None


def parse_event_start_time_from_html(
    html_text: str,
    now_utc: Optional[datetime] = None,
    event_ticker: Optional[str] = None,
) -> Optional[datetime]:
    if not html_text:
        return None
    if _looks_like_challenge_page(html_text):
        return None

    for search_text in _search_text_candidates(html_text):
        for pattern in _HTML_START_PATTERNS:
            match = pattern.search(search_text)
            if not match:
                continue
            token = (match.group(1) or "").strip()
            if not token:
                continue
            try:
                parsed = _parse_iso8601_utc(token)
                return parsed
            except ValueError:
                parsed = _parse_month_day_time_token(token, now_utc=now_utc)
                if parsed is not None:
                    return parsed

        milestone_start = _extract_event_start_from_milestones(search_text, event_ticker=event_ticker)
        if milestone_start is not None:
            return milestone_start
    return None


def build_event_page_urls(event_ticker: str, event: Any, series: Any = None) -> list[str]:
    event_slug = _slugify(event_ticker)
    series_slug = _slugify(str(_get_field(event, "series_ticker", "") or ""))
    title_slug = _slugify(str(_get_field(event, "title", "") or ""))
    subtitle_slug = _slugify(str(_get_field(event, "sub_title", "") or ""))
    series_title_slug = _slugify(str(_get_field(series, "title", "") or ""))

    urls: list[str] = []
    if series_slug and title_slug and event_slug:
        urls.append(f"https://kalshi.com/markets/{series_slug}/{title_slug}/{event_slug}")
    if series_slug and series_title_slug and event_slug:
        urls.append(f"https://kalshi.com/markets/{series_slug}/{series_title_slug}/{event_slug}")
    if series_slug and subtitle_slug and event_slug:
        urls.append(f"https://kalshi.com/markets/{series_slug}/{subtitle_slug}/{event_slug}")
    if series_slug and event_slug:
        urls.append(f"https://kalshi.com/markets/{series_slug}/{event_slug}")
    if event_slug:
        urls.append(f"https://kalshi.com/markets/{event_slug}")

    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped


def _fetch_url_text(url: str, timeout_seconds: float = 8.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return body.decode(charset, errors="replace")


def resolve_event_start_cutoff_utc(md, event_ticker: str) -> tuple[Optional[datetime], dict[str, Any]]:
    event = md.get_event(event_ticker)
    series = None
    series_ticker = str(_get_field(event, "series_ticker", "") or "").strip()
    if series_ticker:
        try:
            series = md.get_series(series_ticker)
        except Exception:  # noqa: BLE001
            series = None

    for field_name in _TIMESTAMP_FIELDS:
        raw = _get_field(event, field_name)
        if not raw:
            continue
        try:
            parsed = _parse_iso8601_utc(str(raw))
            return parsed, {"source": f"event_field:{field_name}"}
        except ValueError:
            continue

    urls = build_event_page_urls(event_ticker, event, series=series)
    errors: list[str] = []
    for url in urls:
        try:
            html_text = _fetch_url_text(url)
        except urllib.error.HTTPError as exc:
            errors.append(f"{url} -> HTTP {exc.code}")
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url} -> {type(exc).__name__}: {exc}")
            continue

        parsed = parse_event_start_time_from_html(html_text, event_ticker=event_ticker)
        if parsed is not None:
            return parsed, {"source": "event_page", "url": url}

        if _looks_like_challenge_page(html_text):
            errors.append(f"{url} -> vercel_security_checkpoint")
        else:
            errors.append(f"{url} -> begins_time_not_found")

    return None, {"source": "unresolved", "candidate_urls": urls, "errors": errors}


def parse_cutoff_time_pt(value: str) -> time:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("cutoff time is empty")
    return datetime.strptime(raw, "%H:%M").time()


def parse_cutoff_date_pt(value: str, now_utc: Optional[datetime] = None) -> date:
    raw = (value or "").strip().lower()
    if not raw or raw == "today":
        now = now_utc or datetime.now(timezone.utc)
        return now.astimezone(PACIFIC_TZ).date()
    return date.fromisoformat(raw)


def build_fallback_cutoff_utc(
    fallback_time_pt: str = "14:00",
    fallback_date_pt: str = "today",
    now_utc: Optional[datetime] = None,
) -> datetime:
    cutoff_time = parse_cutoff_time_pt(fallback_time_pt)
    cutoff_date = parse_cutoff_date_pt(fallback_date_pt, now_utc=now_utc)
    cutoff_local = datetime.combine(cutoff_date, cutoff_time, tzinfo=PACIFIC_TZ)
    return cutoff_local.astimezone(timezone.utc)


@dataclass(frozen=True)
class CutoffResolution:
    cutoff_time_utc: datetime
    source: str
    details: dict[str, Any]


def resolve_cutoff_time_utc(
    md,
    event_ticker: str,
    *,
    fallback_time_pt: str = "14:00",
    fallback_date_pt: str = "today",
    require_event_start: bool = False,
) -> CutoffResolution:
    event_start_utc, details = resolve_event_start_cutoff_utc(md, event_ticker)
    if event_start_utc is not None:
        return CutoffResolution(
            cutoff_time_utc=event_start_utc,
            source=str(details.get("source", "event_start")),
            details=details,
        )

    if require_event_start:
        raise RuntimeError(
            "Could not resolve event start cutoff from API/page. "
            f"Details: {details}"
        )

    fallback_utc = build_fallback_cutoff_utc(
        fallback_time_pt=fallback_time_pt,
        fallback_date_pt=fallback_date_pt,
    )
    return CutoffResolution(
        cutoff_time_utc=fallback_utc,
        source="fallback_pt",
        details={
            "fallback_time_pt": fallback_time_pt,
            "fallback_date_pt": fallback_date_pt,
            "event_start_resolution": details,
        },
    )
