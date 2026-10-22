#!/usr/bin/env bash
# Lab'i geliştirme modunda başlatır: FastAPI (8000, --reload) + Vite (5173, /api -> 8000).
# Ctrl+C ikisini birden kapatır.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate
python -m uvicorn backend.app.main:app --reload --port 8000 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT INT TERM
npm --prefix frontend run dev
