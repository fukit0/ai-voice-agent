"""LLM fonksiyon çağrısı testi API'si (eval-llm, plan Faz 0 adım 4).

Seçilen profillerin LLM'leri 30 örnek cevapla sırayla çalıştırılır; her model için doğru normalize oranı,
doğru dal oranı, JSON geçerliliği ve gecikme döner. Soğuk model ölçülmez (ADR 0001): önce Hazırla.
Koşular `data/llm-evals/<id>.json` altında saklanır, sonradan listelenip açılabilir.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import llm_eval
from .api_profiles import _provider
from .profiles import load_profiles
from .providers import PROVIDERS, cached, missing_env, provider_key, record_call

router = APIRouter(prefix="/api/eval/llm", tags=["eval"])
_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


def _runs_dir() -> Path:
    return Path(os.environ.get("SVA_DATA_DIR", Path(__file__).resolve().parents[2] / "data")) / "llm-evals"


class RunRequest(BaseModel):
    profiles: list[str]
    limit: int | None = None  # yalnızca ilk N örnek (hızlı deneme); varsayılan hepsi


def _llm_models() -> dict[tuple, dict]:
    models: dict[tuple, dict] = {}
    for p in load_profiles().values():
        spec = p.component("llm")
        if not spec:
            continue
        key = provider_key(spec)
        if key not in models:
            cls = PROVIDERS.get(spec.get("provider"))
            prov = cached(spec)
            models[key] = {"profile": p.id, "profiles": [], "provider": spec.get("provider"),
                           "model": spec.get("model") or "", "missing_env": missing_env(cls) if cls else [],
                           "warm": bool(prov and prov.is_warm()), "known": cls is not None}
        models[key]["profiles"].append(p.id)
    return models


@router.get("/models")
def list_models() -> list[dict]:
    return [{**m, "ready": m["known"] and not m["missing_env"]} for m in _llm_models().values()]


@router.get("/samples")
def samples() -> dict:
    d = llm_eval.load_dataset()
    return {"nodes": d["nodes"], "intents": d["intents"], "samples": d["samples"]}


@router.post("/run")
def run(req: RunRequest) -> dict:
    ids = [i for i in dict.fromkeys(x.strip() for x in req.profiles) if i]
    if not ids:
        raise HTTPException(400, {"error": "no_models", "message": "En az bir LLM seçin."})
    if req.limit is not None and req.limit < 1:
        raise HTTPException(400, {"error": "bad_limit", "message": "limit 1 veya daha büyük olmalı."})
    dataset = llm_eval.load_dataset()
    all_profiles = load_profiles()
    results, seen = [], set()
    for pid in ids:
        profile = all_profiles.get(pid)
        spec = profile.component("llm") if profile else None
        if not spec:
            raise HTTPException(400, {"error": "unknown_llm", "message": f"{pid} profilinde LLM yok."})
        if provider_key(spec) in seen:
            continue
        seen.add(provider_key(spec))
        base = {"profile": pid, "provider": spec.get("provider"), "model": spec.get("model") or ""}
        try:
            provider = _provider(profile, "llm")
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            state = "cold" if detail.get("error") == "profile_not_warm" else "not_ready"
            results.append({**base, "status": state, "error": detail.get("message", "")})
            continue
        out = llm_eval.run_eval(provider, dataset, req.limit)
        rows = out["rows"]
        if rows and all(r["seconds"] is None for r in rows):  # hiçbir çağrı yanıt vermedi: model ölçülemedi
            results.append({**base, "status": "failed", "error": rows[0]["problem"] or "LLM yanıt vermedi",
                            "summary": out["summary"], "rows": rows})
            continue
        total = sum(r["seconds"] or 0 for r in rows)
        record_call(pid, "llm", provider, total, ok=True, warm=True, chars=len(rows), source="eval-llm")
        results.append({**base, "status": "ok", "summary": out["summary"], "rows": rows})
    saved = {"id": datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
             "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "n_samples": len(dataset["samples"][:req.limit]), "results": results}
    folder = _runs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{saved['id']}.json").write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return saved


@router.get("/runs")
def runs() -> list[dict]:
    root = _runs_dir()
    if not root.is_dir():
        return []
    out = []
    for path in sorted((p for p in root.glob("*.json") if _ID.match(p.stem)), reverse=True)[:50]:
        r = json.loads(path.read_text(encoding="utf-8"))
        out.append({"id": r["id"], "created_at": r["created_at"], "n_samples": r["n_samples"],
                    "models": [f"{x['provider']}:{x['model']}" for x in r["results"]],
                    "best_full_rate": max((x["summary"]["full_rate"] for x in r["results"] if x["status"] == "ok"),
                                          default=None)})
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    path = _runs_dir() / f"{run_id}.json"
    if not _ID.match(run_id) or not path.is_file():
        raise HTTPException(404, {"error": "unknown_run", "message": f"Koşu bulunamadı: {run_id}"})
    return json.loads(path.read_text(encoding="utf-8"))
