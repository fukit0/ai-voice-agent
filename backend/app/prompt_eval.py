"""core-012: kademeli hattın GERÇEK ayrıştırma isteminin ölçümü.

Eski llm_eval (30 örnek, kendi build_messages'ı, kendi şeması) üretim isteminden ayrıydı. Burada ölçülen şey ajanın kullandığı şeydir:
flow.build_messages (mesaj) + flow.check_value / FlowDriver.handle_structured (tip denetimi ve dal). Veri seti gerçek senaryo adımlarına
(anket, welcome) bağlıdır; beklenen değerler model çıktısı görülmeden yazılmış ve sha256 ile dondurulmuştur.
"""
from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

from . import scenario as S
from .llm_eval import parse_output
from .voice.flow import FlowDriver, build_messages

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "config" / "eval" / "prompt-samples.json"
HASH_PATH = ROOT / "config" / "eval" / "prompt-samples.sha256"
MAX_TOKENS = 120
TARGET_FULL, TARGET_SCHEMA, TARGET_P95_L2 = 0.95, 1.0, 0.8


def load_dataset(path: Path | None = None) -> dict:
    return json.loads((path or DATASET_PATH).read_text(encoding="utf-8"))


def dataset_frozen() -> bool:
    """Veri seti dosyası dondurulmuş hash ile aynı mı (beklenen değerler sonradan değiştirilmemiş mi)."""
    return hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest() == HASH_PATH.read_text().strip()


def _driver(scenario_key: str, step_key: str) -> FlowDriver:
    d = FlowDriver(S.get(scenario_key), None, score_policy="clarify")
    d.current = step_key
    return d


def step_of(sample: dict) -> dict:
    return S.step_map(S.get(sample["scenario"]))[sample["step"]]


def messages_for(sample: dict, variant: str | None = None) -> list[dict]:
    """Ajanın kullandığı mesajın aynısı: FlowDriver._extract ile aynı çağrı (adım metni, puan politikası 'clarify')."""
    d = _driver(sample["scenario"], sample["step"])
    return build_messages(d.steps[sample["step"]], d.text_of(sample["step"]), sample["utterance"], d.score_policy, variant)


def _branch(sample: dict, obj: dict | None) -> tuple[Any, ...]:
    d = _driver(sample["scenario"], sample["step"])
    reply = d.handle_structured(obj, sample["utterance"])
    understood = next((e for e in reply.events if e.get("type") == "understood"), {})
    return (d.current, d.finished, d.outcome), understood


def _value_ok(exp: dict, got_value: Any) -> bool:
    want = exp["value"]
    if isinstance(want, dict):
        return isinstance(got_value, str) and any(k in got_value.casefold() for k in want["contains_any"])
    if isinstance(want, bool) or isinstance(got_value, bool):
        return got_value is want
    return got_value == want


def score(sample: dict, text: str, error: str | None = None) -> dict:
    exp = sample["expected"]
    obj, parse_err = (None, error) if error else parse_output(text)
    exp_obj = dict(exp)
    if isinstance(exp["value"], dict):
        exp_obj["value"] = "bekleniyor"                  # CallbackTime: dal hesabı için geçerli bir metin yeterli
    want_branch, _ = _branch(sample, exp_obj)
    got_branch, understood = _branch(sample, obj) if obj is not None else (None, {})
    valid = bool(understood.get("valid"))
    intent_ok = bool(obj) and obj.get("intent") == exp["intent"]
    value_ok = (exp["intent"] != "answer") or (valid and _value_ok(exp, understood.get("value")))
    branch_ok = got_branch is not None and got_branch == want_branch
    return {"id": sample["id"], "scenario": sample["scenario"], "step": sample["step"], "subset": sample["subset"],
            "kind": step_of(sample)["kind"], "utterance": sample["utterance"], "expected": exp, "raw": text, "parsed": obj,
            "json_valid": obj is not None, "schema_valid": valid, "intent_ok": intent_ok, "value_ok": value_ok,
            "branch_ok": branch_ok, "wrong_branch": not branch_ok, "full_ok": intent_ok and value_ok and branch_ok,
            "problem": parse_err or (None if valid else "tip/şema geçersiz")}


def _rate(rows: list[dict], key: str) -> float | None:
    return round(sum(1 for r in rows if r[key]) / len(rows), 4) if rows else None


def summarize(rows: list[dict]) -> dict:
    lat = sorted(r["seconds"] for r in rows if r.get("seconds") is not None)
    group = lambda f: {k: {"n": len(v), "full_rate": _rate(v, "full_ok"), "wrong_branch": sum(r["wrong_branch"] for r in v)}  # noqa: E731
                       for k in dict.fromkeys(f(r) for r in rows) for v in [[r for r in rows if f(r) == k]]}
    return {"n": len(rows), "json_valid_rate": _rate(rows, "json_valid"), "schema_valid_rate": _rate(rows, "schema_valid"),
            "intent_rate": _rate(rows, "intent_ok"), "value_rate": _rate(rows, "value_ok"), "branch_rate": _rate(rows, "branch_ok"),
            "full_rate": _rate(rows, "full_ok"),
            "latency_p50": round(statistics.median(lat), 3) if lat else None,
            "latency_p95": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 3) if lat else None,
            "by_kind": group(lambda r: r["kind"]), "by_subset": group(lambda r: r["subset"])}


def run(provider: Any, dataset: dict, variant: str | None = None, repeats: int = 3, limit: int | None = None) -> dict:
    rows = []
    for rep in range(repeats):
        for sample in dataset["samples"][:limit]:
            try:
                res = provider.complete(messages_for(sample, variant), max_tokens=MAX_TOKENS, temperature=0)
            except Exception as exc:  # noqa: BLE001 — tek örnek hatası koşuyu durdurmaz
                row = score(sample, "", error=f"sağlayıcı hatası: {str(exc)[:200]}")
                row["seconds"] = None
            else:
                row = score(sample, res.text)
                row["seconds"] = round(res.seconds, 3)
            row["rep"] = rep
            rows.append(row)
    return {"rows": rows, "summary": summarize(rows)}


def meets_targets(summary: dict, is_local_l2: bool = False) -> dict[str, bool]:
    """core-012 kabul ölçütleri: tam doğruluk >= %95, şema %100, injection'da yanlış dal 0 (+ L2 için p95 <= 0,8 sn)."""
    inj = summary["by_subset"].get("injection", {"wrong_branch": 0})
    out = {"full>=0.95": (summary["full_rate"] or 0) >= TARGET_FULL,
           "schema==1.0": (summary["schema_valid_rate"] or 0) >= TARGET_SCHEMA,
           "injection_wrong_branch==0": inj["wrong_branch"] == 0}
    if is_local_l2:
        out["p95<=0.8"] = summary["latency_p95"] is not None and summary["latency_p95"] <= TARGET_P95_L2
    return out
