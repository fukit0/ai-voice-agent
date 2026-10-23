#!/usr/bin/env bash
# Demo / ölçüm modu (ADR 0001): arayüzü derler, backend'i --reload OLMADAN tek süreçte çalıştırır.
# Dosya değişikliği backend'i yeniden başlatmaz, "Hazırla" ile ısıtılan modeller bellekte kalır.
# Arayüz ve API: http://localhost:8000
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck disable=SC1091
source .venv/bin/activate
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"   # modeller önbellekten; indirme gerekiyorsa MODELS_ONLINE=1
[ "${MODELS_ONLINE:-0}" = "1" ] && unset HF_HUB_OFFLINE
npm --prefix frontend run build --silent
echo "==> Lab demo modu: http://localhost:8000  (Ctrl+C ile kapat)"
exec python -m uvicorn backend.app.main:app --host 127.0.0.1 --port "${LAB_PORT:-8000}"
