#!/usr/bin/env bash
# Oturum başlangıç betiği: ortamı hazırlar ve lokal modellerin çalıştığını doğrular.
#   ./init.sh                      # her oturum: ortam + hızlı model kontrolü (Ollama, EMA -> STT)
#   FULL_CHECK=1 ./init.sh         # + Chatterbox; model değişince veya setup-001 kanıtı için
#   SKIP_MODEL_CHECKS=1 ./init.sh  # sadece ortam
#   MODELS_ONLINE=1 ./init.sh      # yeni modeli Hugging Face'ten indirmeye izin ver
# Modeller ~/.cache/huggingface altında önbelleklenir; ilk indirmeden sonra tekrar inmez.
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
# Varsayılan: önbellekten çevrimdışı çalış (ağ kontrolü ve indirme yok, daha hızlı).
if [ "${MODELS_ONLINE:-0}" != "1" ]; then export HF_HUB_OFFLINE=1; fi
export HF_HUB_DISABLE_PROGRESS_BARS=1
if [ "${SKIP_MODEL_CHECKS:-0}" != "1" ]; then
  ARGS=()
  [ "${FULL_CHECK:-0}" = "1" ] && ARGS+=(--full)
  python scripts/healthcheck.py ${ARGS[@]+"${ARGS[@]}"} || {
    echo "==> İpucu: model önbellekte yoksa MODELS_ONLINE=1 ./init.sh ile indir."; exit 1; }
fi

echo "==> Hazır. Kanıtlar evidence/ altında."
