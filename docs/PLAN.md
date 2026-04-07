# Kalshi Trading Terminal — Implementation Plan

## Context

You trade mention markets on Kalshi using CLI scripts, YAML configs, and a separate signals dashboard. The existing `kalshi_tools` library (~12K LOC) handles API connectivity, order management, smart execution, position tracking, and analytics. The goal is a local web-based trading terminal that provides a better UI for manual and automated trading than the Kalshi website, with full keyboard-driven order entry, live market data, and execution management — all backed by your existing Python infrastructure.

## Architecture

**Standalone project** at `/Users/jstenger/Documents/repos/trading/trading-terminal/` that imports `kalshi_tools` (same pattern as mentions-dashboard).

**Stack:**
- **Backend:** FastAPI (Python) — bridges kalshi_tools to the browser via REST + WebSocket
- **Frontend:** SvelteKit (SPA mode) + TypeScript + Tailwind CSS
- **Charts:** Lightweight Charts (TradingView open-source, ~40KB)
- **Runs on:** `localhost:8766` (backend serves built frontend + API)

**Why Svelte over HTMX:** The terminal needs sub-second orderbook rendering (10+ updates/sec), complex keyboard shortcut handling, interactive order entry, and multiple simultaneous WebSocket streams. Svelte compiles to imperative DOM mutations (no virtual DOM overhead) and its reactive stores map naturally to streaming data.

**Keep separate from mentions-dashboard.** The dashboard is read-only analysis; the terminal is real-time execution. Different concerns, different update cadences. They share `kalshi_tools` as the common dependency. Cross-linking via URLs (Phase 2+) lets you jump between them without coupling their codebases.

## Data Flow

```
Kalshi WS Feed → OrderBookStream (kalshi_tools) → StreamHub (backend)
    → coalesced at 10Hz → FastAPI WS /ws/{event} → Svelte stores → UI

Browser order entry → POST /api/orders → OrderService → OrderManager → Kalshi REST API
```

The `StreamHub` manages one `OrderBookStream` per active event (supports multi-ticker subscription), reference-counted by connected browser clients. Orderbook updates are coalesced (latest state per ticker at 10Hz); trades are forwarded immediately for the tape.

## Security

- **Local-only binding** (`127.0.0.1:8766`)
- **API keys stay server-side** — browser never sees credentials
- **Session token** — generated at startup, printed to console, required as Bearer token for all mutating endpoints and WS auth
- **Rate limiting** on order endpoints (10/sec default)
- **Confirmation dialogs** for batch cancel-all and large orders
- **Demo/live mode** toggle prominently displayed, switch requires confirmation

## Project Structure

```
trading-terminal/
├── run.py                     # Entry point (uvicorn, sys.path, .env)
├── pyproject.toml
├── CLAUDE.md
├── configs/defaults.yaml      # Terminal-specific defaults
├── backend/
│   ├── app.py                 # FastAPI app, CORS, lifespan, static mount
│   ├── config.py              # Settings
│   ├── dependencies.py        # Singletons: KalshiClient, MarketData, OrderManager
│   ├── security.py            # Token auth, local-only middleware
│   ├── ws/
│   │   ├── manager.py         # WS connection fan-out manager
│   │   └── stream_hub.py      # OrderBookStream lifecycle + coalescing
│   ├── routes/
│   │   ├── markets.py         # Events, markets, search
│   │   ├── orders.py          # Place, cancel, batch, resting
│   │   ├── positions.py       # Positions, fills, PNL
│   │   ├── execution.py       # Start/stop SmartOrder, batch, flow
│   │   └── analytics.py       # VWAP, flow, skew, candles
│   └── services/
│       ├── order_service.py   # Validation + OrderManager wrapper
│       ├── position_service.py# PNL computation + PositionTracker wrapper
│       └── execution_service.py # SmartOrder/Batch/Flow lifecycle
├── frontend/
│   ├── package.json
│   ├── svelte.config.js
│   ├── vite.config.ts
│   ├── src/
│   │   ├── lib/
│   │   │   ├── stores/        # orderbook, trades, positions, orders, hotkeys
│   │   │   ├── ws/client.ts   # WS client with reconnect
│   │   │   └── api/client.ts  # REST fetch wrapper
│   │   ├── routes/
│   │   │   ├── +layout.svelte # Shell: header + sidebar + global hotkeys
│   │   │   ├── +page.svelte   # Main trading view
│   │   │   ├── portfolio/     # Portfolio/PNL page
│   │   │   └── execution/     # Execution management page
│   │   └── components/
│   │       ├── OrderBook.svelte       # Depth ladder
│   │       ├── OrderEntry.svelte      # Order form + hotkeys
│   │       ├── TradeTape.svelte       # Scrolling trades
│   │       ├── MarketSelector.svelte  # Event/market picker
│   │       ├── PriceChart.svelte      # Lightweight Charts
│   │       ├── PositionCard.svelte    # Per-market position
│   │       ├── RestingOrders.svelte   # Active orders list
│   │       ├── StatsBar.svelte        # VWAP, spread, volume, flow
│   │       ├── ExecutionPanel.svelte  # SmartOrder controls
│   │       ├── BatchPanel.svelte      # Multi-market batch
│   │       ├── LadderEntry.svelte     # Multi-level order builder
│   │       └── FlowBar.svelte        # Yes/No flow indicator
│   └── static/sounds/fill.mp3
└── tests/
```

## Main Trading View Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ TERMINAL   [Event ▼]  [/ Search]   Sub:1 | LIVE      Bal: $2,450   │
├────────────────────┬──────────────────────┬──────────────────────────┤
│  MARKET LIST       │  ORDER BOOK LADDER   │  ORDER ENTRY             │
│  □ TARI  42/44  +50│  Price|Yes|No|Mine   │  Side: [YES] Y/N        │
│  ■ CHIN  33/36  -  │  ...depth ladder...  │  Price: 42  ↑↓          │
│  □ TAX   38/40  +25│                      │  Size: 50   +/-         │
│  (pos, pnl color)  │──────────────────────│  Type: PostOnly         │
│                    │  TRADE TAPE           │  [PLACE ⏎] [CANCEL ⎋]  │
│                    │  42 x50 YES ▲         │──────────────────────── │
│                    │  41 x25 NO  ▼         │  RESTING ORDERS         │
│                    │  42 x100 YES ▲        │  42c YES x50 [X]       │
├────────────────────┴──────────────────────┴──────────────────────────┤
│ VWAP 41.2 | uPx 42.3 | Spread 2c | Vol 12.5K | Flow 68% YES       │
├──────────────────────────────────────────────────────────────────────┤
│ PRICE CHART (Lightweight Charts)                    [1m] [5m] [1h]  │
└──────────────────────────────────────────────────────────────────────┘
```

Market list shows open positions and PNL color-coded. Selecting a market updates the ladder, tape, chart, and stats. Orderbook ladder is click-to-trade.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Y` / `N` | Set side YES / NO |
| `↑↓` | Price ±1c |
| `Shift+↑↓` | Price ±5c |
| `+/-` or `]/[` | Size ±10 |
| `Enter` | Place order |
| `Escape` | Cancel all (current ticker) |
| `Shift+Escape` | Cancel all (all tickers) |
| `Tab` / `Shift+Tab` | Next/prev market |
| `1-9` | Quick-select market |
| `Ctrl+L` | Ladder order builder |
| `Ctrl+B` | Batch panel |
| `Ctrl+S` | Start SmartOrder |
| `/` | Focus search |
| `?` | Show shortcut help |

## kalshi_tools Reuse Map

| kalshi_tools class | Backend wrapper |
|---|---|
| `get_client()` → `dependencies.py` singleton |
| `MarketData` → `dependencies.py` singleton, used by routes |
| `OrderBookStream` → `StreamHub` (one per event, ref-counted) |
| `OrderManager` → `OrderService` (adds validation, fee estimation) |
| `PositionTracker` → `PositionService` (adds PNL, event aggregation) |
| `SmartOrder` / `BatchExecutor` / `FlowOrchestrator` → `ExecutionService` |
| `calculate_vwap`, `calculate_flows` → analytics route |
| `calculate_fee` → order preview in OrderService |

**Import pattern:** Use selective imports from submodules (e.g., `from kalshi_tools.core.client import get_client`) to avoid the `__init__.py` hang on Python 3.13 (same issue as mentions-dashboard).

## Build Phases

### Phase 1: Foundation
Set up project scaffolding, FastAPI backend with market browsing endpoints, SvelteKit frontend, StreamHub with live orderbook WebSocket relay, and the main layout with `MarketSelector` + `OrderBook` (read-only ladder).

**Deliverable:** Browse events, select markets, see live orderbook updating.

### Phase 2: Order Entry + Management
`OrderService` + REST endpoints for place/cancel/batch-cancel. Session token security. `OrderEntry` component with form validation, click-to-trade on ladder, `RestingOrders` list, keyboard shortcuts.

**Deliverable:** Place and cancel orders with keyboard shortcuts.

### Phase 3: Positions, PNL, Trade Tape
`PositionService` with PNL computation. Trade stream relay. `TradeTape`, `PositionCard`, `StatsBar`, `PortfolioTable`. Subaccount threading through all queries.

**Deliverable:** Full trading view with positions, PNL, and tape.

### Phase 4: Charts + Analytics
Price chart via Lightweight Charts with real-time updates. `FlowBar`, analytics endpoint.

### Phase 5: Advanced Orders
Ladder orders, batch orders across markets, IOC support, order expiry times.

### Phase 6: Automated Execution
`ExecutionService` managing SmartOrder/Batch/Flow lifecycles. `ExecutionPanel` mirroring what `display.py` shows. Config file load/save through UI.

### Phase 7: Polish
Audio fill alerts, toast notifications, confirmation dialogs, WS reconnection, demo/live toggle, performance profiling.

## Verification Plan

After each phase:
1. Start backend: `python run.py` → verify API responses with curl
2. Start frontend dev server → verify components render
3. For Phase 1+: verify live orderbook updates via WebSocket (connect to a real event)
4. For Phase 2+: place test orders in demo mode, verify they appear on Kalshi
5. For Phase 3+: verify positions match Kalshi portfolio API
6. For Phase 6: start SmartOrder from UI, verify it executes (demo mode)

End-to-end: run both servers, open browser, select a live mentions event, verify orderbook streams, place a demo order, see it in resting orders, cancel it.
