#!/usr/bin/env python3
"""Launch the Trading Terminal.

Usage:
    python run.py
    python run.py --no-browser
    python run.py --port 8766
    python run.py --demo
"""

import argparse
import os
import sys
import threading
import webbrowser
from pathlib import Path

# ── Ensure sys.path includes all needed source dirs ──
_root = Path(__file__).resolve().parent.parent
_paths = [
    str(Path(__file__).resolve().parent),           # backend package
    str(_root / "kalshi_tools" / "src"),             # kalshi_tools
]
for p in _paths:
    if p not in sys.path:
        sys.path.insert(0, p)

# Load .env from kalshi_tools
_env = _root / "kalshi_tools" / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    parser = argparse.ArgumentParser(description="Kalshi Trading Terminal")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true", help="Use Kalshi demo environment")
    args = parser.parse_args()

    os.environ["TERMINAL_DEMO"] = "1" if args.demo else "0"

    if not args.no_browser:
        def _open():
            import time
            time.sleep(1.5)
            webbrowser.open(f"http://{args.host}:{args.port}")
        threading.Thread(target=_open, daemon=True).start()

    import uvicorn
    uvicorn.run(
        "backend.app:app",
        host=args.host,
        port=args.port,
        reload=True,
        reload_dirs=[str(Path(__file__).resolve().parent / "backend")],
        log_level="info",
    )


if __name__ == "__main__":
    main()
