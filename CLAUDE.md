# Trading Terminal

## Overview
Personal Kalshi trading terminal — local web app for manual and automated trading of prediction markets (primarily mention markets).

## Architecture
- **Backend**: FastAPI (Python) — bridges kalshi_tools to the browser via REST + WebSocket
- **Frontend**: SvelteKit (SPA mode) + TypeScript + Tailwind CSS
- **Charts**: Lightweight Charts (TradingView open-source)
- **Launch**: `python run.py` (serves on localhost:8766)
- **Venv**: `.venv/` (Python 3.13) — separate from kalshi_tools venv

## Critical Gotchas
- **kalshi_tools imports MUST bypass `__init__.py`** — use `lazy_import()` from `backend/lazy_import.py`. The package's init imports Engine/WebSocket/asyncio code that hangs on Python 3.13.
- **sys.path setup** handled by `run.py` — adds `backend/`, `../kalshi_tools/src/`.
- **pykalshi objects**: Events are model objects (`getattr`), markets are dicts (`.get()`).
- **Price normalization**: API now returns dollar-string fields. MarketData normalizes to integer cents. All internal prices are in cents (1-99).
- **OrderBookStream** runs in a thread with its own asyncio loop. The StreamHub bridges it to FastAPI WebSocket endpoints.

## Security
- Local-only binding (127.0.0.1:8766)
- Session token generated at startup, required for mutating endpoints
- API keys stay server-side in .env, never sent to browser

## Project Structure
```
trading-terminal/
├── run.py              # Entry point
├── backend/
│   ├── app.py          # FastAPI app
│   ├── config.py       # Settings
│   ├── dependencies.py # Singletons (client, market_data)
│   ├── security.py     # Token auth middleware
│   ├── lazy_import.py  # Safe kalshi_tools imports
│   ├── ws/             # WebSocket handlers
│   ├── routes/         # REST API routes
│   └── services/       # Business logic wrappers
└── frontend/           # SvelteKit app (built → backend/static/)
```

## Key Commands
- `python run.py` — Start backend (serves frontend build + API)
- `cd frontend && npm run dev` — Frontend dev server with HMR (proxies API to :8766)
- `cd frontend && npm run build` — Build frontend → backend serves from dist/
