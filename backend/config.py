"""Terminal configuration."""

import os
import secrets
from pathlib import Path

import yaml


# Session token for authenticating browser requests
SESSION_TOKEN = secrets.token_hex(32)

# Kalshi environment
DEMO = os.environ.get("TERMINAL_DEMO", "0") == "1"

# Subaccount for all trading operations.
# STRICT: all positions, orders, and fills are scoped to this subaccount.
# Set to 0 to use main account (dangerous — avoid in production).
SUBACCOUNT = int(os.environ.get("TERMINAL_SUBACCOUNT", "1"))

# StreamHub settings
BOOK_UPDATE_RATE_HZ = 10  # Max orderbook updates per second to browser
STREAM_GRACE_PERIOD_S = 30  # Keep stream alive after last client disconnects

# ── Load config file ──
_config_path = Path(__file__).resolve().parent.parent / "configs" / "defaults.yaml"
_file_config: dict = {}
if _config_path.exists():
    with open(_config_path) as f:
        _file_config = yaml.safe_load(f) or {}

MAX_ORDER_CONTRACTS = int(_file_config.get("max_order_contracts", 500))
DEFAULT_ORDER_SIZE = int(_file_config.get("default_order_size", 100))
SIZE_INCREMENT = int(_file_config.get("size_increment", 100))
