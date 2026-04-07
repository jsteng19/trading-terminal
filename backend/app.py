"""FastAPI application for the Trading Terminal."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend import config
from backend.routes import markets, orders, positions
from backend.ws.manager import ConnectionManager
from backend.ws.stream_hub import StreamHub

logger = logging.getLogger(__name__)

# ── Shared instances ──
ws_manager = ConnectionManager()
stream_hub = StreamHub(ws_manager)

# ── Cleanup task ──
_cleanup_task = None


async def _periodic_cleanup():
    """Periodically clean up streams with no subscribers."""
    while True:
        await asyncio.sleep(config.STREAM_GRACE_PERIOD_S)
        await stream_hub.cleanup_unused()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cleanup_task
    # Startup
    logger.info("Trading Terminal starting")
    logger.info("Mode: %s", "DEMO" if config.DEMO else "LIVE")
    logger.info("Session token: %s", config.SESSION_TOKEN)
    logger.info("Subaccount (enforced): %d", config.SUBACCOUNT)
    _cleanup_task = asyncio.create_task(_periodic_cleanup())
    yield
    # Shutdown
    if _cleanup_task:
        _cleanup_task.cancel()
    for event_ticker in list(stream_hub.active_events()):
        await stream_hub.unsubscribe(event_ticker)
    logger.info("Trading Terminal stopped")


app = FastAPI(title="Trading Terminal", lifespan=lifespan)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:8766", "http://127.0.0.1:5173", "http://127.0.0.1:8766"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── REST routes ──
app.include_router(markets.router)
app.include_router(orders.router)
app.include_router(positions.router)


# ── WebSocket endpoint ──
@app.websocket("/ws/{event_ticker}")
async def ws_event_stream(
    websocket: WebSocket,
    event_ticker: str,
    token: str = Query(None),
):
    """Stream orderbook + trade data for all markets in an event."""
    # Validate token
    if token != config.SESSION_TOKEN:
        await websocket.close(code=4003, reason="Invalid token")
        return

    # Get market tickers for this event
    from backend.dependencies import get_market_data
    md = get_market_data()
    try:
        event_markets = md.get_markets(event_ticker=event_ticker)
    except Exception as e:
        logger.error("Failed to fetch markets for %s: %s", event_ticker, e)
        await websocket.close(code=4004, reason="Failed to fetch markets")
        return

    tickers = [m.get("ticker") for m in event_markets if m.get("ticker")]
    if not tickers:
        await websocket.close(code=4004, reason="No markets found")
        return

    # Connect and start streaming
    await ws_manager.connect(event_ticker, websocket)
    await stream_hub.subscribe(event_ticker, tickers)

    # Send initial market list
    await websocket.send_json({
        "type": "markets",
        "data": event_markets,
    })

    try:
        while True:
            # Keep connection alive; handle client messages if needed
            data = await websocket.receive_text()
            # Could handle client commands here (e.g., subscribe to specific ticker)
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(event_ticker, websocket)


# ── Health check ──
@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "demo" if config.DEMO else "live",
        "subaccount": config.SUBACCOUNT,
        "active_streams": stream_hub.active_events(),
    }


# ── Session token (local-only, for frontend auto-auth) ──
@app.get("/api/auth/token")
def get_token():
    return {"token": config.SESSION_TOKEN}


# ── Terminal config (for frontend) ──
@app.get("/api/config")
def get_config():
    return {
        "mode": "demo" if config.DEMO else "live",
        "subaccount": config.SUBACCOUNT,
        "max_order_contracts": config.MAX_ORDER_CONTRACTS,
        "default_order_size": config.DEFAULT_ORDER_SIZE,
        "size_increment": config.SIZE_INCREMENT,
    }


# ── Serve frontend build (production) ──
_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "build"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
