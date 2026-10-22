#!/usr/bin/env bash
# Oturum başlangıç betiği: ortamı hazırlar ve lokal modellerin çalıştığını doğrular.
#   ./init.sh                         # bağımlılık + tüm model kontrolleri
#   SKIP_CHATTERBOX=1 ./init.sh       # Chatterbox'ı atla (yüklemesi uzun sürer)
#   SKIP_MODEL_CHECKS=1 ./init.sh     # sadece ortam
# Ortam değişkenleri: OLLAMA_URL, OLLAMA_MODEL, STT_MODEL (bkz. scripts/healthcheck.py)

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
echo "==> Working directory: $PWD"

# --- Python ortamı ---------------------------------------------------------
if [ ! -d .venv ]; then
  echo "==> .venv yok, oluşturuluyor (Python 3.11)"
  uv venv --python 3.11 .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "==> Python: $(python --version)"

if [ -f requirements.txt ] && [ "${SKIP_INSTALL:-0}" != "1" ]; then
  echo "==> Bağımlılıklar senkronize ediliyor"
  uv pip install -q -r requirements.txt
fi

# --- Ollama ----------------------------------------------------------------
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
if ! curl -sf "$OLLAMA_URL/api/tags" >/dev/null; then
  echo "==> Ollama yanıt vermiyor ($OLLAMA_URL). Başlatmayı deniyorum: ollama serve"
  if command -v ollama >/dev/null; then
    (ollama serve >/tmp/ollama.log 2>&1 &)
    for _ in $(seq 1 15); do curl -sf "$OLLAMA_URL/api/tags" >/dev/null && break; sleep 1; done
  fi
fi

# --- Model sağlık kontrolleri ---------------------------------------------
if [ "${SKIP_MODEL_CHECKS:-0}" != "1" ]; then
  SKIP=()
  [ "${SKIP_CHATTERBOX:-0}" = "1" ] && SKIP+=(chatterbox)
  python scripts/healthcheck.py ${SKIP[@]+--skip "${SKIP[@]}"}
fi

echo "==> Hazır. Kanıtlar evidence/ altında."
