"""LLM fonksiyon çağrısı testi (eval-llm, plan Faz 0 adım 4).

Flow motoru deterministiktir; LLM yalnızca müşterinin cevabını yapılandırır: {"intent", "value"}.
Bu modül 30 örnek cevabı bir LLM'den geçirir ve iki şeyi ölçer:
  - doğru normalize: `value` beklenen değerle aynı mı (ör. "iki buçuk milyon" -> 2500000)
  - doğru dal: LLM çıktısından flow motorunun türeteceği dal beklenenle aynı mı

Karar (belgelenmiş): native tool-calling yerine JSON çıktı sözleşmesi kullanılır. Sebep: sağlayıcı arayüzü
(`LLMProvider.complete`) metin döndürür ve tüm profillerde (Ollama, Anthropic) aynıdır; böylece modeller
aynı koşulda kıyaslanır. Native tool-calling ayrı bir ölçümdür ve bu testin kapsamı dışındadır.
Çıktı kesin (strict) doğrulanır: "9" (metin) sayı sayılmaz, çünkü production flow motoru da tip bekler.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any

DATASET_PATH = Path(__file__).resolve().parents[2] / "config" / "eval" / "llm-samples.json"
MAX_TOKENS = 120

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def load_dataset(path: Path | None = None) -> dict:
    return json.loads((path or DATASET_PATH).read_text(encoding="utf-8"))


def build_messages(dataset: dict, node_id: str, utterance: str) -> list[dict]:
    node = dataset["nodes"][node_id]
    intents = "\n".join(f"- {k}: {v}" for k, v in dataset["intents"].items())
    system = (
        "Sen bir sesli anket ajanının cevap ayrıştırıcısısın. Müşteri telefonda konuştu; cümlesi konuşma "
        "tanımadan geldiği için küçük harfli ve noktalamasızdır. Görevin müşterinin cevabını yapılandırmak.\n"
        "SADECE tek bir JSON nesnesi döndür, başka hiçbir şey yazma. Şema:\n"
        '{"intent": "answer|repeat|refuse|unclear|off_topic|callback", "value": <değer veya null>}\n'
        f"intent anlamları:\n{intents}\n"
        "value yalnızca intent=answer iken dolu olur; diğer durumlarda null.\n"
        f"Bu sorunun value kuralı: {node['value_rule']}.\n"
        "Sayıları rakamla yaz (örn. 'iki buçuk milyon' -> 2500000). Müşteri birden fazla şey söylerse "
        "sorulan soruya verdiği asıl cevabı al."
    )
    user = f"Soru: {node['question']}"
    if node.get("options"):
        user += "\nSeçenekler: " + ", ".join(f"{k} = {v}" for k, v in node["options"].items())
    user += f"\nMüşteri: {utterance}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_output(text: str) -> tuple[dict | None, str | None]:
    """Model çıktısından ilk JSON nesnesini çıkarır. (nesne, hata). Düşünce etiketi ve kod çiti tolere edilir."""
    cleaned = _THINK.sub("", text or "").strip()
    fence = _FENCE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    start = cleaned.find("{")
    if start < 0:
        return None, "JSON yok"
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        return None, f"JSON bozuk: {exc.msg}"
    if not isinstance(obj, dict):
        return None, "JSON nesne değil"
    return obj, None


def _is_int(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    return isinstance(v, int) or (isinstance(v, float) and v.is_integer())


def schema_error(dataset: dict, node_id: str, obj: dict) -> str | None:
    """Çıktı şemaya uyuyor mu? Uymuyorsa nedeni; uyuyorsa None."""
    node = dataset["nodes"][node_id]
    intent = obj.get("intent")
    if intent not in dataset["intents"]:
        return f"geçersiz intent: {intent!r}"
    value = obj.get("value")
    if intent != "answer":
        return None if value is None else "answer dışında value null olmalı"
    kind = node["type"]
    if kind == "rating":
        ok = _is_int(value) and 1 <= value <= 10
    elif kind == "yes_no":
        ok = isinstance(value, bool)
    elif kind == "choice":
        ok = isinstance(value, str) and value in node["options"]
    elif kind == "number":
        ok = _is_int(value) and value >= 0
    else:
        ok = False
    return None if ok else f"value {value!r} {kind} kuralına uymuyor"


def route(dataset: dict, node_id: str, obj: dict | None) -> str | None:
    """Flow motorunun LLM çıktısından seçeceği dal. Çıktı geçersizse None (motor yeniden sorar)."""
    if obj is None or schema_error(dataset, node_id, obj):
        return None
    intent = obj["intent"]
    if intent != "answer":
        return dataset["special_branches"][intent]
    node = dataset["nodes"][node_id]
    b, v = node["branches"], obj["value"]
    kind = node["type"]
    if kind == "rating":
        return b["low"] if v <= b["low_max"] else b["high"]
    if kind == "yes_no":
        return b["true"] if v else b["false"]
    if kind == "choice":
        return b[v]
    return b["high"] if v >= b["high_min"] else b["normal"]


def _values_equal(got: Any, want: Any) -> bool:
    if isinstance(got, bool) or isinstance(want, bool):
        return got is want
    if want is None:
        return got is None
    if isinstance(want, (int, float)):
        return isinstance(got, (int, float)) and float(got) == float(want)
    return got == want


def score_sample(dataset: dict, sample: dict, text: str, error: str | None = None) -> dict:
    exp = sample["expected"]
    obj, parse_err = (None, error) if error else parse_output(text)
    schema_err = schema_error(dataset, sample["node"], obj) if obj is not None else None
    valid = obj is not None and schema_err is None
    got_branch = route(dataset, sample["node"], obj)
    intent_ok = bool(obj) and obj.get("intent") == exp["intent"]
    value_ok = bool(obj) and valid and _values_equal(obj.get("value"), exp["value"])
    branch_ok = got_branch == exp["branch"]
    return {
        "id": sample["id"], "node": sample["node"], "utterance": sample["utterance"],
        "expected": exp, "raw": text, "parsed": obj, "got_branch": got_branch,
        "json_valid": obj is not None, "schema_valid": valid,
        "intent_ok": intent_ok, "value_ok": value_ok, "branch_ok": branch_ok,
        "full_ok": intent_ok and value_ok and branch_ok,
        "problem": parse_err or schema_err,
    }


def _rate(items: list[dict], key: str) -> float | None:
    return round(sum(1 for i in items if i[key]) / len(items), 4) if items else None


def summarize(dataset: dict, rows: list[dict]) -> dict:
    """Oranlar: json/şema/intent/dal/tam doğru tüm örneklerde; normalize yalnızca beklenen intent=answer olanlarda."""
    answers = [r for r in rows if r["expected"]["intent"] == "answer"]
    lat = sorted(r["seconds"] for r in rows if r.get("seconds") is not None)
    by_type: dict[str, dict] = {}
    for kind in dict.fromkeys(dataset["nodes"][r["node"]]["type"] for r in rows):
        subset = [r for r in rows if dataset["nodes"][r["node"]]["type"] == kind]
        by_type[kind] = {"n": len(subset), "full_rate": _rate(subset, "full_ok"), "branch_rate": _rate(subset, "branch_ok")}
    return {
        "n": len(rows), "n_answers": len(answers),
        "json_valid_rate": _rate(rows, "json_valid"), "schema_valid_rate": _rate(rows, "schema_valid"),
        "intent_rate": _rate(rows, "intent_ok"), "normalize_rate": _rate(answers, "value_ok"),
        "branch_rate": _rate(rows, "branch_ok"), "full_rate": _rate(rows, "full_ok"),
        "latency_p50": round(statistics.median(lat), 3) if lat else None,
        "latency_p95": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 3) if lat else None,
        "by_type": by_type,
    }


def run_eval(provider: Any, dataset: dict, limit: int | None = None) -> dict:
    """Örnekleri sırayla çalıştırır (ölçümler birbirini bozmasın). Sağlayıcı hatası o örneği başarısız sayar."""
    rows = []
    for sample in dataset["samples"][:limit]:
        messages = build_messages(dataset, sample["node"], sample["utterance"])
        try:
            res = provider.complete(messages, max_tokens=MAX_TOKENS, temperature=0)
        except Exception as exc:  # noqa: BLE001 — bir örneğin hatası koşuyu durdurmamalı
            row = score_sample(dataset, sample, "", error=f"sağlayıcı hatası: {str(exc)[:200]}")
            row["seconds"] = None
        else:
            row = score_sample(dataset, sample, res.text)
            row["seconds"] = round(res.seconds, 3)
            row["output_tokens"] = res.output_tokens
        rows.append(row)
    return {"rows": rows, "summary": summarize(dataset, rows)}
