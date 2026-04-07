"""Lazy import for kalshi_tools submodules — bypasses __init__.py.

The kalshi_tools __init__.py imports Engine/WebSocket/asyncio code that
hangs on Python 3.13. This module provides a safe way to import individual
submodules directly without triggering the top-level init.
"""

import importlib
import os
import sys
import types


def lazy_import(module_path: str):
    """Import a kalshi_tools submodule WITHOUT triggering __init__.py."""
    if module_path in sys.modules:
        return sys.modules[module_path]

    parts = module_path.split(".")
    for i in range(len(parts)):
        partial = ".".join(parts[: i + 1])
        if partial not in sys.modules:
            if i == 0 and partial == "kalshi_tools":
                pkg = types.ModuleType(partial)
                pkg.__path__ = []
                for p in sys.path:
                    candidate = os.path.join(p, "kalshi_tools")
                    if os.path.isdir(candidate):
                        pkg.__path__ = [candidate]
                        pkg.__file__ = os.path.join(candidate, "__init__.py")
                        break
                sys.modules[partial] = pkg
            else:
                importlib.import_module(partial)

    return sys.modules[module_path]
