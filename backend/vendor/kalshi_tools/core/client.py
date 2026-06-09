"""Thin `pykalshi` client factory for this repo."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pykalshi import KalshiClient


def _resolve_api_key_id(api_key_id: Optional[str] = None) -> str:
    resolved = api_key_id or os.environ.get("KALSHI_API_KEY_ID")
    if not resolved:
        raise ValueError("Set KALSHI_API_KEY_ID or pass api_key_id explicitly.")
    return resolved


def _resolve_private_key_path(private_key_path: Optional[str] = None) -> str:
    candidate = private_key_path or os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    if not candidate:
        raise ValueError(
            "Set KALSHI_PRIVATE_KEY_PATH or pass private_key_path explicitly."
        )

    expanded = Path(candidate).expanduser()
    if expanded.exists():
        return str(expanded)

    cwd_path = Path.cwd() / expanded
    if cwd_path.exists():
        return str(cwd_path)

    raise FileNotFoundError(f"Private key file does not exist: {expanded}")


def get_client(
    api_key_id: Optional[str] = None,
    private_key_path: Optional[str] = None,
    demo: bool = False,
) -> KalshiClient:
    """Create a sync `pykalshi.KalshiClient`."""
    return KalshiClient(
        api_key_id=_resolve_api_key_id(api_key_id=api_key_id),
        private_key_path=_resolve_private_key_path(private_key_path=private_key_path),
        demo=demo,
    )
