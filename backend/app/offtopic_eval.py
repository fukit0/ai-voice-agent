"""off-001: konu dışı söz ve bağlama bağlı karşılık ölçümü (offline simülasyon).

Ne ölçer: FlowDriver'ın (kademeli hat akışı) konu dışı sözlere, kimlik sorularına, kural sınırındaki sözlere (DNC/ret/geri arama) ve
duygulu cevaplara verdiği KARŞILIK. Ayrıştırıcı LLM gerçek çağrılmaz: her vakada LLM'in döndürdüğü JSON veri setinde sabittir
(config/eval/offtopic-samples.json). Böylece ölçülen şey modelin değil, akış + konuşma katmanının davranışıdır.

SINIR (dürüst durum): gerçek modelin bu sözleri hangi intent'e koyduğu burada ÖLÇÜLMEZ (prompt_eval/core-012 işi). Bu yüzden konu dışı tek
tur vakaları iki etiketle koşulur: veri setindeki etiket ve 'unclear' (modelin sık karıştırdığı etiket). Ses, TTS, telefon yok.

Araç yalnızca FlowDriver'ın genel arayüzünü kullanır (start yok; current atanır, handle çağrılır), bu yüzden değişiklik öncesi ve
sonrası kod aynı araçla ölçülebilir.
"""
from __future__ import annotations

import itertools
import json
import random
import re
import statistics
import time
from pathlib import Path
from typing import Any

from . import persona as persona_mod
from . import scenario as S
from .providers.base import LLMResult
from .voice import flow as flow_mod

ROOT = Path(__file__).resolve().parents[2]
DATASET_PATH = ROOT / "config" / "eval" / "offtopic-samples.json"
FROZEN_SETS = (ROOT / "config" / "eval" / "prompt-samples.json", ROOT / "config" / "eval" / "prompt-holdout.json")
UNCLEAR = {"intent": "unclear", "value": None}


class StubLLM:
    """Sıradaki turun sabit JSON'unu döndürür; çağrı sayısını tutar (gecikme bütçesi: ek LLM çağrısı olmamalı)."""
    kind, model = "stub", "stub"

    def __init__(self):
        self.next: dict | None = None
        self.calls = 0

    def complete(self, messages, max_tokens=256, temperature=0.3):
        self.calls += 1
        out = self.next if self.next is not None else UNCLEAR
        return LLMResult(json.dumps(out, ensure_ascii=False), 0.0, "stub", "stub")


def load_dataset(path: Path | None = None) -> dict:
    return json.loads((path or DATASET_PATH).read_text(encoding="utf-8"))


def _low(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").casefold()


def _has(text_low: str, key: str) -> bool:
    """Anahtar kelime BAŞINDAN eşleşir ('lan' -> 'bağlanana' içinde sayılmaz; 'üzül' -> 'üzüldüm' sayılır)."""
    return re.search(r"(?<![a-zçğıöşü0-9])" + re.escape(_low(key)), text_low) is not None


def _driver(step: str, seed: int, fast_path: bool = True) -> tuple[flow_mod.FlowDriver, StubLLM]:
    llm = StubLLM()
    sc = S.get("anket")
    p = persona_mod.defaults()
    d = flow_mod.FlowDriver(sc, llm, persona_mod.scenario_values(p), persona=p, rng=random.Random(seed))
    d.fast_path = fast_path
    d.current = step
    if hasattr(d, "path"):
        d.path.append(step)
    return d, llm


def run_case(case: dict, seed: int = 0, llm_override: dict | None = None) -> dict:
    d, llm = _driver(case["step"], seed)
    turns_out: list[dict] = []
    ok_all = True
    for i, t in enumerate(case["turns"]):
        step_before = d.current
        reask_texts = [d.retry_of(step_before), d.text_of(step_before)] if step_before else []
        llm.next = llm_override if (llm_override is not None and t.get("llm") is not None) else t.get("llm")
        calls0, n_ans0 = llm.calls, len(d.answers)
        t0 = time.perf_counter()
        r = d.handle(t["say"])
        dt_ms = (time.perf_counter() - t0) * 1000
        said = " ".join(r.utterances)
        low = _low(said)
        # 'ilgili cevap' denetimi yalnız AJANIN KARŞILIĞINA bakar: yeniden sorulan/sıradaki soru metni çıkarılır (soru metnindeki
        # 'sahibinden', 'hizmet' gibi kelimeler denetimi yanlışlıkla geçirmesin). Bağlam grubunda onay cümlesi senaryo düğümünün
        # kendisi olabildiği için (kapanis_randevu) tam metne bakılır.
        own = said
        if case["group"] != "context":
            qs = reask_texts + [d.text_of(e["key"]) for e in r.events if e.get("type") == "node" and not e.get("terminal")]
            for q in sorted({q for q in qs if q}, key=len, reverse=True):
                own = own.replace(q, " ")
        own_low = _low(own)
        new_answers = [a for a in d.answers[n_ans0:] if not a.get("unanswered")]
        exp = t.get("expect", {})
        checks: dict[str, bool] = {}
        if "reply_any" in exp:
            checks["reply_any"] = any(_has(own_low, k) for k in exp["reply_any"])
        if "reply_none" in exp:
            checks["reply_none"] = not any(_has(low, k) for k in exp["reply_none"])
        if exp.get("reask"):
            checks["reask"] = any(q and q in said for q in reask_texts)
        if "recorded" in exp:
            checks["recorded"] = bool(new_answers) == exp["recorded"]
        if "outcome" in exp:
            checks["outcome"] = (d.outcome if d.finished else None) == exp["outcome"]
        if "current" in exp:
            checks["current"] = d.current == exp["current"]
        ok = all(checks.values())
        ok_all = ok_all and ok
        turns_out.append({"say": t["say"], "llm": llm.next if t.get("llm") is not None else None, "reply": r.utterances,
                          "checks": checks, "ok": ok, "llm_calls": llm.calls - calls0, "layer_ms": round(dt_ms, 3),
                          "finished": d.finished, "outcome": d.outcome, "current": d.current,
                          "recorded": [{"step": a["step"], "value": a["value"]} for a in new_answers],
                          "robot_template": None})
        if d.finished:
            break
    replies = [" ".join(t["reply"]) for t in turns_out]
    consecutive_repeat = sum(1 for a, b in itertools.pairwise(replies) if a == b)
    firsts = [t["reply"][0] for t in turns_out if t["reply"]]
    lead_repeat = len(firsts) - len(set(firsts))
    if case.get("no_consecutive_repeat"):
        ok_all = ok_all and consecutive_repeat == 0 and lead_repeat == 0
    return {"id": case["id"], "group": case["group"], "category": case["category"], "subset": case.get("subset"), "seed": seed,
            "label": "override:" + llm_override["intent"] if llm_override else "dataset", "ok": ok_all, "turns": turns_out,
            "consecutive_repeat": consecutive_repeat, "lead_repeat": lead_repeat}


def _mark_robot(rows: list[dict], markers: list[str]) -> None:
    for r in rows:
        for t in r["turns"]:
            t["robot_template"] = any(_has(_low(" ".join(t["reply"])), m) for m in markers)


def frozen_branches() -> dict[str, Any]:
    """Dondurulmuş ana set + holdout: BEKLENEN nesne akışa verildiğinde dal (adım, bitti mi, sonuç). Değişiklik öncesi/sonrası aynı
    olmalı (konu dışı katmanı, etiketli setlerin akış davranışını bozmamalı). Model çağrılmaz."""
    out: dict[str, Any] = {}
    for path in FROZEN_SETS:
        for s in json.loads(path.read_text(encoding="utf-8"))["samples"]:
            exp = dict(s["expected"])
            if isinstance(exp["value"], dict):
                exp["value"] = "bekleniyor"
            sc = S.get(s["scenario"])
            d = flow_mod.FlowDriver(sc, None, score_policy="clarify")
            d.current = s["step"]
            d.handle_structured(exp, s["utterance"])
            out[s["id"]] = [d.current, d.finished, d.outcome, [a["value"] for a in d.answers]]
    return out


def _rate(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def summarize(rows: list[dict]) -> dict:
    by_group: dict[str, dict] = {}
    for g in dict.fromkeys(r["group"] for r in rows):
        rs = [r for r in rows if r["group"] == g]
        by_group[g] = {"runs": len(rs), "cases": len({r["id"] for r in rs}), "ok_rate": _rate([r["ok"] for r in rs]),
                       "failed_cases": sorted({r["id"] for r in rs if not r["ok"]})}
    off = [r for r in rows if r["group"] == "offtopic"]
    off_turns = [t for r in off for t in r["turns"]]
    def chk(turns: list[dict], k: str) -> float | None:
        return _rate([t["checks"][k] for t in turns if k in t["checks"]])
    by_cat: dict[str, Any] = {}
    for c in dict.fromkeys(r["category"] for r in off):
        rs = [r for r in off if r["category"] == c]
        by_cat[c] = {"runs": len(rs), "ok_rate": _rate([r["ok"] for r in rs])}
    by_label = {lab: _rate([r["ok"] for r in off if r["label"] == lab]) for lab in dict.fromkeys(r["label"] for r in off)}
    all_turns = [t for r in rows for t in r["turns"]]
    ms = sorted(t["layer_ms"] for t in all_turns)
    dialogs = [r for r in rows if r["group"] == "dialog"]
    ctx = [r for r in rows if r["group"] == "context"]
    return {
        "runs": len(rows), "cases": len({r["id"] for r in rows}), "ok_rate": _rate([r["ok"] for r in rows]),
        "by_group": by_group,
        "offtopic": {"relevant_reply_rate": chk(off_turns, "reply_any"), "reask_rate": chk(off_turns, "reask"),
                     "no_fabricated_answer_rate": chk(off_turns, "recorded"), "forbidden_text_free_rate": chk(off_turns, "reply_none"),
                     "robot_template_rate": _rate([t["robot_template"] for t in off_turns]), "by_category": by_cat,
                     "by_llm_label": by_label},
        "context": {"reaction_fit_rate": chk([t for r in ctx for t in r["turns"]], "reply_any"),
                    "no_wrong_tone_rate": chk([t for r in ctx for t in r["turns"]], "reply_none")},
        "dialog": {"consecutive_identical_replies": sum(r["consecutive_repeat"] for r in dialogs),
                   "repeated_lead_sentences": sum(r["lead_repeat"] for r in dialogs)},
        "latency": {"llm_calls_total": sum(t["llm_calls"] for t in all_turns), "turns": len(all_turns),
                    "layer_ms_p50": round(statistics.median(ms), 3) if ms else None,
                    "layer_ms_max": round(ms[-1], 3) if ms else None},
    }


def run(dataset: dict | None = None, seeds: tuple[int, ...] = (0, 1, 2, 3, 4)) -> dict:
    dataset = dataset or load_dataset()
    rows: list[dict] = []
    for case in dataset["cases"]:
        for seed in seeds:
            rows.append(run_case(case, seed))
            single_off = case["group"] == "offtopic" and len(case["turns"]) == 1 and case["turns"][0].get("llm", {}) is not None \
                and case["turns"][0]["llm"].get("intent") == "off_topic"
            if single_off:
                rows.append(run_case(case, seed, UNCLEAR))     # dayanıklılık: model konu dışı yerine 'anlaşılmadı' derse
    _mark_robot(rows, dataset.get("robot_markers", []))
    return {"dataset": {"path": str(DATASET_PATH.relative_to(ROOT)), "version": dataset.get("version"), "cases": len(dataset["cases"])},
            "seeds": list(seeds), "summary": summarize(rows), "frozen_branches": frozen_branches(), "rows": rows}
