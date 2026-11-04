"""ADR 0009 adım 2: konu dışı serbest cevabın GERÇEK Qwen ya da Haiku ile değerlendirmesi (Mac'te; Qwen için Ollama açık, Haiku için ANTHROPIC_API_KEY).

Ne ölçer: config/eval/free-reply-samples.json'daki her vakada (bekleyen soru + müşteri sözü + kategori) canlı akışla AYNI istem ve AYNI
çıktı denetimiyle Qwen'den kısa karşılık ister. Vaka başına: üretilen metin, denetimden geçti mi (geçmediyse hangi kurallar), süre, müşteriye
söylenecek tam cümle (karşılık + kodun eklediği soru; düşerse havuz cümlesi). Özet: geçme oranı, düşüş sebepleri, süre p50/p95/en çok.

Kullanım (proje kökünde):
  ./.venv/bin/python scripts/eval_free_reply.py                    # 3 tekrar, config'teki model ve zaman aşımı
  ./.venv/bin/python scripts/eval_free_reply.py --runs 5 --timeout 1.5 --model qwen3:30b-a3b-instruct-2507-q4_K_M
  ./.venv/bin/python scripts/eval_free_reply.py --fake             # betiğin kendisini modelsiz dener (kanıt DEĞİLDİR, evidence'a yazmaz)
  ./.venv/bin/python scripts/eval_free_reply.py --runs 3 --thinking   # aynı vakalar thinking modeliyle (think:true, thinking_timeout_s)
  ./.venv/bin/python scripts/eval_free_reply.py --runs 3 --thinking --compare evidence/free-reply-eval-<önceki>.json   # kapalı koşuyla kıyas

  ./.venv/bin/python scripts/eval_free_reply.py --runs 3 --backend haiku   # aynı vakalar Claude Haiku ile (A1S'in LLM'i; API ücreti)

--backend haiku (docs/serbest-cevap-haiku.md): model varsayılanı ekrandaki haiku_model, yoksa A1S profilinin LLM modeli (claude-haiku-5-5);
zaman aşımı haiku_timeout_s, token sınırı haiku_max_tokens. Anahtar ortamdan ya da proje kökündeki .env'den okunur; yoksa betik çalışmadan
hata verir. Isınma yapılmaz (soğuk model kavramı yok); ilk çağrının TLS el sıkışması ölçüme girer, bu yüzden özet ilk çağrıyı ayrıca yazar.
Satıra backend / input_tokens / output_tokens / cost_usd, özete token ortalaması ve toplam tahmini maliyet yazılır. --thinking ile birlikte kullanılamaz.

--thinking: model varsayılanı config'teki thinking_model, zaman aşımı thinking_timeout_s, token sınırı thinking_max_tokens. Düşünme metni
cevaptan ayıklanır (canlıyla aynı split_thinking); yalnız son cevap denetlenir. Satıra think_chars / eval_tokens / ollama_s yazılır.

Model soğuksa önce bir ısınma çağrısı yapılır (ölçüme girmez, yükleme süresi ayrıca yazılır; ADR 0001). Ölçüm sıcak modelle yapılır.
Çıktı: evidence/free-reply-eval-<tarih>.json (makine) + aynı adla .md (insan okuması, gözden geçirme sütunu boş).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from backend.app import persona as persona_mod
from backend.app import scenario as S
from backend.app.voice import free_reply as F
from backend.app.voice import smalltalk as T

SAMPLES = ROOT / "config" / "eval" / "free-reply-samples.json"


class FakeClient:
    """--fake: betiğin akışını modelsiz sınamak için (kategoriye göre sabit metin; biri bilerek denetime takılır).
    --thinking ile ayrı düşünme metni de döndürür (cevaba sızmadığını test doğrular)."""
    model = "fake"

    def __init__(self, think: bool = False, backend: str = "qwen"):
        self.think = think
        self.backend = backend

    def is_warm(self):
        return True

    def chat(self, messages, timeout_s, max_tokens, temperature):
        u = messages[1]["content"]
        out = "Ben olsam sekiz verirdim." if "ignore" in u else "Bu tamamen sizin kendi deneyiminize bağlı bir değerlendirme."
        if self.backend == "haiku":
            return F.ChatReply(out, "", {"input_tokens": 900, "output_tokens": 30, "api_s": 0.0})
        if not self.think:
            return out
        return F.ChatReply(out, "Müşteri bana soruyor, düşünüyorum: puan vermemeliyim.", {"eval_tokens": 120, "ollama_s": 0.0})


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, round(q * (len(xs) - 1)))], 3)


def read_system_file(path: Path) -> str:
    """off-004: --system-file içeriği (temizlenmiş). Sınırı aşan dosya KESİLMEZ: kesik istemle ölçüm sessizce yanlış sonuç verirdi
    (canlıda aynı istem Ayarlar'da reddedilir), bu yüzden açık Türkçe hata (ValueError; main çıkış kodu 2)."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Sistem istemi dosyası okunamadı: {path} ({exc})") from exc
    text = F.clean_prompt(raw)
    if not text:
        raise ValueError(f"Sistem istemi dosyası boş: {path}")
    if len(text) > F.SYSTEM_PROMPT_MAX:
        raise ValueError(f"Sistem istemi dosyası çok uzun: {len(text)} karakter (sınır {F.SYSTEM_PROMPT_MAX}). Dosya kesilmez; "
                         "istemi kısaltıp yeniden deneyin (serbest cevap için kısa istem önerilir: config/prompts/serbest-cevap-selin.txt).")
    return text


def warm_up_ollama(client, system: str, timeout_s: float, rounds: int = 4, cold_timeout_s: float = 180.0,
                   say=print, clock=time.perf_counter) -> float | None:
    """Yerel modeli ölçümden ÖNCE ısıtır. Ölçülecek gerçek sistem istemiyle (aynı önek) uzun zaman aşımlı çağrılar yapar;
    bir çağrı `timeout_s` içinde dönene kadar (en çok `rounds` kez) tekrarlar. Dönen değer: ilk çağrının süresi (soğuk yük),
    ilk çağrı zaten hızlıysa None. Ölçüme girmez."""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": "<musteri>merhaba</musteri>"}]
    first = None
    for i in range(rounds):
        t0 = clock()
        client.chat(msgs, cold_timeout_s, 8, 0.0)
        dt = round(clock() - t0, 2)
        first = dt if first is None else first
        say(f"ısınma {i + 1}/{rounds}: {dt} sn")
        if dt <= timeout_s:
            return first if first > timeout_s else None
    raise RuntimeError(f"model {rounds} ısınma çağrısında da {timeout_s} sn altına inmedi (son {dt} sn); başka bir süreç Ollama'yı meşgul ediyor olabilir")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=3, help="vaka başına tekrar (sıcaklık 0,6: çıktı değişir)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--timeout", type=float, default=None, help="zaman aşımı (sn); varsayılan config/free-reply.json")
    ap.add_argument("--samples", type=Path, default=SAMPLES)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--fake", action="store_true", help="modelsiz kuru çalıştırma; evidence'a yazmaz")
    ap.add_argument("--thinking", action="store_true", help="thinking modeli + think:true ile ölç (gecikme kıyası; canlı varsayılan kapalı)")
    ap.add_argument("--compare", type=Path, default=None, help="önceki bir çıktı JSON'u: özet farkları (süre, geçme oranı) yazdırılır")
    ap.add_argument("--backend", choices=("qwen", "haiku"), default="qwen", help="qwen (Ollama, varsayılan) ya da haiku (Anthropic API)")
    ap.add_argument("--system-file", type=Path, default=None,
                    help="off-004: bu dosyadaki sistem istemiyle ölç (verilmezse Ayarlar'da kaydedilmiş istem, o da yoksa varsayılan)")
    args = ap.parse_args()

    cfg = F.settings()
    system_override = None
    if args.system_file is not None:
        try:
            system_override = read_system_file(args.system_file)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    haiku = args.backend == "haiku"
    if haiku and args.thinking:
        print("--thinking yalnız Qwen içindir; Haiku'da düşünme her zaman kapalı.", file=sys.stderr)
        return 2
    if haiku:
        from backend.app.profiles import load_dotenv
        load_dotenv()           # backend ile aynı: .env'deki anahtar (ortamdakini ezmez)
        if not args.fake and not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY tanımlı değil (ortamda ya da proje kökündeki .env'de). Haiku ölçümü yapılmadı.", file=sys.stderr)
            return 2
        model = args.model or F.haiku_model(cfg, a1s_llm())
        timeout = args.timeout or float(cfg.get("haiku_timeout_s", F.HAIKU_TIMEOUT_DEFAULT))
    else:
        model = args.model or (cfg["thinking_model"] if args.thinking else cfg["model"])
        timeout = args.timeout or float(cfg["thinking_timeout_s"] if args.thinking else cfg["timeout_s"])
    data = json.loads(args.samples.read_text(encoding="utf-8"))
    sc = S.get("anket")
    steps = S.step_map(sc)
    persona = persona_mod.load()
    values = {**S.sample_values(sc), **persona_mod.scenario_values(persona)}
    assistant = values.get("ASISTAN", "Ayşe")
    texts = S.load_overrides(sc["key"])

    if args.fake:
        client = FakeClient(args.thinking, args.backend)
    elif haiku:
        client = F.AnthropicChatClient(model)
    else:
        client = F.OllamaChatClient(model, ttl_s=0, think=args.thinking)
    load_s = None
    if not args.fake and not haiku:      # Haiku: soğuk model yok, ısınma/yoklama atlanır
        if client.is_warm() is None:
            print(f"Ollama'ya ulaşılamıyor ({client.url}). `ollama serve` çalışıyor mu?", file=sys.stderr)
            return 2
        # 2026-11-04 ölçümü: /api/ps 'yüklü' dese de ilk 28 tur timeout aldı (model yeniden yükleniyordu); bu yüzden ısınma
        # /api/ps'ye güvenmez, ölçülecek GERÇEK istemle ısınana kadar döner.
        sys_cfg = {**cfg, "system_prompt": system_override} if system_override is not None else cfg
        try:
            load_s = warm_up_ollama(client, F.system_text(sys_cfg), timeout)
        except Exception as exc:  # noqa: BLE001
            print(f"Isınma başarısız: {exc}", file=sys.stderr)
            return 2
    if system_override is not None:
        cfg = {**cfg, "system_prompt": system_override}
    live_rep = F.FreeReplier(FakeClient(backend=args.backend), cfg)
    if live_rep.wide:   # off-004 geniş kapsam: canlıda NEVER_LLM dışındaki tüm kategoriler denenir
        live_cats = {c["category"] for c in data["cases"]} - set(F.NEVER_LLM)
    else:
        live_cats = set(F.categories_for(cfg, args.backend))   # canlıda bu arka ucun denediği kategoriler (Haiku listesi daha geniş)
    # Değerlendirmede tüm kategoriler denenir (canlıda yalnız live_cats); denetim ve istem canlıyla aynı
    run_cfg = {**cfg, "model": model, "timeout_s": timeout, "thinking": args.thinking, "thinking_model": model, "thinking_timeout_s": timeout, "haiku_timeout_s": timeout,
               "categories": sorted({c["category"] for c in data["cases"]} | live_cats),
               "haiku_categories": sorted({c["category"] for c in data["cases"]} | live_cats),
               "use_pool_fallback_only": False}   # ölçüm her vaka kategorisini dener (NEVER_LLM dahil); canlı kapsam live_eligible'da
    rep = F.FreeReplier(client, run_cfg, assistant, thinking_client=client if args.thinking else None)
    pool_rng = random.Random(0)
    rows = []
    for case in data["cases"]:
        step = steps[case["step"]]
        question = S.fill(texts.get(step["key"], step["defaultText"]), values)
        reask = S.fill(step["retryText"], values) if step.get("retryText") and step["key"] not in texts else question
        for run in range(args.runs):
            r = rep.generate(step, question, case["utterance"], case["category"])
            pool = T.config()["replies"].get(case["category"]) or T.config()["replies"]["other"]
            said = (r.text if r.text else S.fill(pool_rng.choice(pool), values) + " " + S.fill(pool_rng.choice(T.config()["bridges"]), values))
            rows.append({"id": case["id"], "run": run, "step": case["step"], "category": case["category"], "utterance": case["utterance"],
                         "live_eligible": case["category"] in live_cats, "source": r.source, "reason": r.reason, "passed": r.text is not None,
                         "fails": r.fails, "seconds": r.seconds, "text": r.text, "candidate": r.candidate, "spoken": said + " " + reask,
                         "thinking": r.thinking, "think_chars": r.think_chars, "eval_tokens": r.eval_tokens, "ollama_s": r.ollama_s,
                         "backend": r.backend, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "cost_usd": r.cost_usd,
                         "note": case.get("note", "")})
            mark = "OK " if r.text else f"-> havuz ({r.reason}: {', '.join(r.fails)[:60]})"
            print(f"{case['id']} #{run} {r.seconds:5.2f} sn {mark}  {(r.text or r.candidate or '')[:90]}", flush=True)

    secs = [x["seconds"] for x in rows if x["reason"] not in ("cold", "unreachable")]
    live = [x for x in rows if x["live_eligible"]]
    reasons: dict[str, int] = {}
    rule_fails: dict[str, int] = {}
    for x in rows:
        if not x["passed"]:
            reasons[x["reason"]] = reasons.get(x["reason"], 0) + 1
            for f in x["fails"]:
                rule_fails[f] = rule_fails.get(f, 0) + 1
    summary = {"cases": len(data["cases"]), "runs_per_case": args.runs, "turns": len(rows),
               "pass_rate": round(sum(x["passed"] for x in rows) / len(rows), 3),
               "pass_rate_live_categories": round(sum(x["passed"] for x in live) / len(live), 3) if live else None,
               "within_timeout_rate": round(sum(x["reason"] != "timeout" for x in rows) / len(rows), 3),
               "fallback_reasons": reasons, "rule_fails": rule_fails,
               "seconds": {"p50": pct(secs, 0.5), "p95": pct(secs, 0.95), "max": max(secs) if secs else None,
                           "mean": round(statistics.mean(secs), 3) if secs else None},
               "think_chars_mean": mean_of(rows, "think_chars"), "eval_tokens_mean": mean_of(rows, "eval_tokens"),
               "input_tokens_mean": mean_of(rows, "input_tokens"), "output_tokens_mean": mean_of(rows, "output_tokens"),
               "cost_usd_total": total_cost(rows),
               # ilk çağrı (Haiku: ilk TLS el sıkışması; Qwen: ısınmadan sonraki ilk istek) ayrıca: p95'i tek başına şişirebilir
               "first_call_s": rows[0]["seconds"] if rows else None}
    meta = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fake": args.fake, "model": model if not args.fake else "fake",
            "backend": args.backend,
            "timeout_s": timeout, "thinking": args.thinking, "max_tokens": rep._max_tokens(), "cold_load_s": load_s, "prompt": rep.describe()["prompt"], "wide_scope_live": live_rep.wide,
            "samples": str(args.samples.relative_to(ROOT)) if args.samples.is_relative_to(ROOT) else str(args.samples),
            "live_categories": sorted(live_cats)}
    doc = {"meta": meta, "summary": summary, "rows": rows}

    if args.compare:
        summary["compare"] = compare(summary, json.loads(args.compare.read_text(encoding="utf-8")), str(args.compare))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    tag = "haiku-" if haiku else ("thinking-" if args.thinking else "")
    if args.out:
        out = args.out
    elif args.fake:
        out = Path(tempfile.gettempdir()) / f"free-reply-eval-FAKE-{tag}{stamp}.json"
    else:
        out = ROOT / "evidence" / f"free-reply-eval-{tag}{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    out.with_suffix(".md").write_text(markdown(doc), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"kanıt: {out} ve {out.with_suffix('.md').name}")
    return 0


def a1s_llm() -> dict | None:
    """A1S profilinin LLM'i (haiku_model ayarı boşsa model adı buradan gelir; canlıda da profilden gelir)."""
    try:
        from backend.app.profiles import load_profiles
        prof = load_profiles().get("A1S")
        return prof.component("llm") if prof else None
    except Exception:  # noqa: BLE001 — profil dosyası okunamazsa config'teki haiku_default_model
        return None


def total_cost(rows: list[dict]) -> float | None:
    """Fiyatı bilinen satırların tahmini maliyet toplamı (USD); hiç fiyatlı satır yoksa None (sıfır yazılmaz)."""
    xs = [x["cost_usd"] for x in rows if isinstance(x.get("cost_usd"), (int, float))]
    return round(sum(xs), 6) if xs else None


def mean_of(rows: list[dict], key: str) -> float | None:
    xs = [x[key] for x in rows if isinstance(x.get(key), (int, float))]
    return round(statistics.mean(xs), 1) if xs else None


def compare(cur: dict, prev_doc: dict, name: str) -> dict:
    """Bu koşunun özeti ile önceki bir koşunun (ör. thinking kapalı) farkı: süre p50/p95/ortalama ve geçme oranları (bu - önceki)."""
    prev = prev_doc.get("summary", {})
    def d(a, b):
        return round(a - b, 3) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
    out = {"against": name, "against_thinking": bool(prev_doc.get("meta", {}).get("thinking", False)),
           "against_model": prev_doc.get("meta", {}).get("model")}
    for k in ("p50", "p95", "mean", "max"):
        out[f"seconds_{k}_delta"] = d(cur["seconds"].get(k), (prev.get("seconds") or {}).get(k))
    for k in ("pass_rate", "pass_rate_live_categories", "within_timeout_rate"):
        out[f"{k}_delta"] = d(cur.get(k), prev.get(k))
    return out


def markdown(doc: dict) -> str:
    m, s = doc["meta"], doc["summary"]
    be = "Haiku" if m.get("backend") == "haiku" else "Qwen"
    lines = [f"# Serbest cevap ({be}) değerlendirmesi — {m['generated_at']}", "",
             ("**SAHTE (--fake) ÇALIŞTIRMA: kanıt değildir.**\n" if m["fake"] else ""),
             f"- Model: `{m['model']}` · thinking: {'açık' if m.get('thinking') else 'kapalı'} · zaman aşımı {m['timeout_s']} sn · istem {m['prompt']['version']}/{m['prompt']['hash']}"
             + (f" · ısınma (ölçüm dışı) {m['cold_load_s']} sn" if m["cold_load_s"] else ""),
             f"- {s['cases']} vaka × {s['runs_per_case']} tekrar = {s['turns']} tur",
             f"- Denetimden geçen: **{s['pass_rate']}** (canlıda LLM'e giden kategorilerde: **{s['pass_rate_live_categories']}**)",
             f"- Zaman aşımı içinde: {s['within_timeout_rate']} · süre p50 {s['seconds']['p50']} / p95 {s['seconds']['p95']} / en çok {s['seconds']['max']} sn",
             f"- Havuza düşüş sebepleri: {s['fallback_reasons'] or '-'} · kural: {s['rule_fails'] or '-'}",
             (f"- Düşünme: ortalama {s.get('think_chars_mean')} karakter · üretilen token (düşünme + cevap) ortalama {s.get('eval_tokens_mean')}"
              if m.get("thinking") else ""),
             (f"- Token ortalaması giriş {s.get('input_tokens_mean')} / çıkış {s.get('output_tokens_mean')} · tahmini toplam maliyet "
              f"{s.get('cost_usd_total')} USD (config/pricing.json) · ilk çağrı {s.get('first_call_s')} sn" if m.get("backend") == "haiku" else ""),
             (f"- Kıyas ({s['compare']['against']}, thinking {'açık' if s['compare']['against_thinking'] else 'kapalı'}): "
              f"p50 farkı {s['compare']['seconds_p50_delta']} sn · p95 farkı {s['compare']['seconds_p95_delta']} sn · "
              f"geçme farkı {s['compare']['pass_rate_delta']}" if s.get("compare") else ""), "",
             "Gözden geçirme: her satır için 'Doğal mı / doğru mu / güvenli mi' sütununu insan doldurur (otomatik denetim yalnızca yasakları yakalar).", "",
             f"| Vaka | Kat. | Canlı | Müşteri | {be} çıktısı | Denetim | Sn | Söylenecek (soru dahil) | İnsan notu |",
             "|---|---|---|---|---|---|---|---|---|"]
    esc = lambda t: (t or "").replace("|", "\\|").replace("\n", " ")
    for x in doc["rows"]:
        out = x["text"] or x["candidate"] or ""
        verdict = "geçti" if x["passed"] else f"{x['reason']}: {', '.join(x['fails'])[:50]}"
        lines.append(f"| {x['id']}#{x['run']} | {x['category']} | {'evet' if x['live_eligible'] else 'hayır'} | {esc(x['utterance'])} | {esc(out)} | "
                     f"{esc(verdict)} | {x['seconds']} | {esc(x['spoken'])} | |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
