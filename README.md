# Trading Terminal

A local web terminal for trading Kalshi prediction markets. It runs on your own
machine, talks to the Kalshi API, and puts a keyboard-driven order ticket, a live
order book, and resting-order management on one screen — faster to trade from than
the Kalshi website when you're watching several markets at once.

Everything is local: the backend holds your API keys and the browser only talks to
`127.0.0.1`.

![Trading terminal](docs/screenshot.png)

## Features

- **Live order book ladder** streamed over WebSocket. Top-of-book pushes in real
  time (coalesced to 10 updates/sec); full depth is polled from REST so the ladder
  stays complete.
- **Click-to-trade** — click any price level to load it into the ticket.
- **Keyboard order entry** — set side, price, size and fire without the mouse.
- **Resting orders** with one-key cancel, plus cancel-all by market or by event.
- **Live trade tape**.
- **Market list** that auto-discovers open events and shows your position per market.
- **Maker/taker fee preview** before you send.
- **Demo or live** mode, with every order scoped to a chosen subaccount.

## Order types

- **YES / NO**, limit price 1–99¢.
- **Maker** (post-only, no fee) or **crossing/taker** (pays the Kalshi taker fee).
- **Time in force:** GTC, 10-minute, end-of-day (4pm ET), event-start (resolved from
  the event page), or a custom minute count.

## Stack

- **Backend:** FastAPI. Wraps the Kalshi REST/WebSocket API via [`pykalshi`](https://pypi.org/project/pykalshi/)
  and relays the order-book feed to the browser.
- **Frontend:** SvelteKit (SPA) + TypeScript + Tailwind.
- The generic Kalshi plumbing (auth, market data, order placement, order-book stream,
  event-time resolver) is vendored under `backend/vendor/kalshi_tools/`, so the repo
  runs standalone.

## Security

- Binds to `127.0.0.1` only.
- A session token is generated at startup and required for every place/cancel call.
- API keys stay in `.env` on the server; the browser never receives them.

## Setup

```bash
git clone https://github.com/jsteng19/trading-terminal.git
cd trading-terminal

python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env          # add KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH

cd frontend && npm install && npm run build && cd ..   # backend serves the build

python run.py                 # opens http://127.0.0.1:8766
```

`python run.py --demo` uses Kalshi's demo environment; `--port N` changes the port.
For frontend hot-reload during development: `cd frontend && npm run dev` (proxies the
API to `:8766`).

## API

All endpoints are under `http://127.0.0.1:8766`. Reads are open (local-only); placing
and cancelling orders requires the session token as a `Bearer` header — fetch it from
`GET /api/auth/token` (the frontend does this automatically).

**Markets**
- `GET /api/markets/events` — open events
- `GET /api/markets/event/{event}/markets` — markets in an event
- `GET /api/markets/market/{ticker}` — market + stats
- `GET /api/markets/market/{ticker}/orderbook?depth=20`
- `GET /api/markets/market/{ticker}/trades?limit=200`
- `GET /api/markets/event/{event}/start-time` — resolved event start (UTC)

**Orders** (Bearer token required for place/cancel)
- `POST /api/orders/place` — `{ticker, side, price, count, post_only, expiration_ts?}`
- `POST /api/orders/cancel` — `{order_id}`
- `POST /api/orders/cancel-all` — `{ticker?, event_ticker?}`
- `POST /api/orders/estimate` — cost + fee preview (no auth)

**Portfolio**
- `GET /api/positions/` · `GET /api/positions/orders` · `GET /api/positions/fills`

**Stream**
- `WS /ws/{event}?token=...` — order-book + trade stream for every market in the event

```bash
# read an order book
curl -s localhost:8766/api/markets/market/<TICKER>/orderbook | jq

# place a post-only YES order for 50 @ 42c
TOKEN=$(curl -s localhost:8766/api/auth/token | jq -r .token)
curl -s -X POST localhost:8766/api/orders/place \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"ticker":"<TICKER>","side":"yes","price":42,"count":50,"post_only":true}'
```

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Y` / `N` | Set side YES / NO |
| `↑` / `↓` | Price ±1¢ |
| `Shift+↑` / `Shift+↓` | Price ±5¢ |
| `]` / `[` | Size ± increment |
| `Enter` | Place order |
| `Esc` | Cancel all on current market |
| `Shift+Esc` | Cancel all in event |
| `Tab` / `Shift+Tab` | Next / previous market |
| `1`–`9` | Quick-select market |
| `?` | Toggle shortcut help |

## Notes

- The market list filters to Kalshi `mention` series by default (one line in
  `backend/routes/markets.py`) — change it to trade other categories.
- Configurable defaults (max order size, default size, increment) live in
  `configs/defaults.yaml`.
