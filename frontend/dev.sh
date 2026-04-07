#!/bin/bash
cd "$(dirname "$0")"
exec node_modules/.bin/vite dev --port "${1:-5173}"
