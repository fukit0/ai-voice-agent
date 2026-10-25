"""Anket akışını konuşma oturumunda yürüten sürücü (lab-003 + core-004'ün çekirdeği).

İlke (plan): akışı bu motor yönetir, LLM yalnızca düğüm içinde müşterinin cevabını {"intent","value"} olarak
yapılandırır (eval-llm ile aynı JSON sözleşmesi). Statement adımları ardışık okunur; soru adımında durulur.
Anlaşılmayan cevap en fazla iki kez farklı biçimde tekrar sorulur; ardından Score/Duration/OpenText için "cevap yok"
dalı izlenir, Evet/Hayır ve Seçenekli için görüşme 'sistem_sonlandirdi' ile kibarca kapatılır.
Sessiz hat (kapanis_sessiz) ve ses katmanı olayları henüz bağlı değil (açık madde).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from .. import scenario as S
from ..llm_eval import parse_output
from ..trnorm import number_to_words

MAX_RETRIES = 2
INTENTS = {
    "answer": "Soruya cevap verdi (value dolu).",
    "repeat": "Soruyu duymadı / tekrar istiyor.",
    "refuse": "Cevap vermek / ankete devam etmek istemiyor.",
    "unclear": "Bilmiyor / belirsiz; cevap çıkarılamıyor.",
    "off_topic": "Soruyla ilgisiz soru ya da şikayet soruyor.",
    "callback": "Şu an müsait değil, başka zamanda aranmak istiyor.",
    "dnc": "Bir daha aranmak istemiyor ('beni aramayın').",
}
FALLBACK_CLOSE = "Sizi duymakta zorlanıyorum, rahatsız ettiğim için özür dilerim. İyi günler dilerim."
HINTS = {
    "YesNo": "Evet ya da hayır diyebilirsiniz.",
    "Duration": "Örneğin otuz saniye ya da iki dakika diyebilirsiniz.",
    "CallbackTime": "Örneğin yarın saat on beşte diyebilirsiniz.",
    "CheckIn": "Sorunuz varsa söyleyebilirsiniz, yoksa devam diyebilirsiniz.",
}
QUESTION_NOTED = "Sorunuzu not aldım, bilgilendirmeye devam edelim."


@dataclass
class Reply:
    utterances: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    finished: bool = False
    outcome: str | None = None
    llm_s: float | None = None


def _rule(step: dict) -> str:
    kind = step["kind"]
    if kind == "Score":
        return f"{step['min'] if step['code'] != 'Q12' else 0}-10 arası tam sayı"
    if kind == "YesNo":
        return "true (evet) veya false (hayır)"
    if kind == "Choice":
        return "seçenek anahtarlarından biri: " + ", ".join(c["value"] for c in step["choices"])
    if kind == "Duration":
        return "toplam saniye cinsinden tam sayı (örn. 'iki dakika' -> 120, 'otuz saniye' -> 30)"
    if kind == "CallbackTime":
        return "müşterinin söylediği gün/saat ifadesi, metin olarak (örn. 'yarın saat on beşte'); söylemediyse intent=unclear"
    if kind == "CheckIn":
        return ("true: müşterinin sormak/öğrenmek istediği bir şey var (soru sordu); "
                "false: sorusu yok, onayladı ya da devam etmek istiyor (tamam, anladım, yok, devam)")
    return "metin"


def build_messages(step: dict, question: str, utterance: str) -> list[dict]:
    intents = "\n".join(f"- {k}: {v}" for k, v in INTENTS.items())
    system = (
        "Sen bir sesli anket ajanının cevap ayrıştırıcısısın. Müşteri telefonda konuştu; cümlesi konuşma "
        "tanımadan geldiği için küçük harfli ve noktalamasızdır. Görevin müşterinin cevabını yapılandırmak.\n"
        "SADECE tek bir JSON nesnesi döndür, başka hiçbir şey yazma. Şema:\n"
        '{"intent": "answer|repeat|refuse|unclear|off_topic|callback|dnc", "value": <değer veya null>}\n'
        f"intent anlamları:\n{intents}\n"
        "value yalnızca intent=answer iken dolu olur; diğer durumlarda null.\n"
        f"Bu sorunun value kuralı: {_rule(step)}.\n"
        "Sayıları rakamla yaz (örn. 'dokuz' -> 9). Müşteri birden fazla şey söylerse sorulan soruya verdiği asıl cevabı al."
    )
    user = f"Soru: {question}"
    if step["kind"] == "Choice":
        user += "\nSeçenekler: " + ", ".join(f"{c['value']} = {c['label']}" for c in step["choices"])
    user += f"\nMüşteri: {utterance}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _is_int(v: Any) -> bool:
    return not isinstance(v, bool) and (isinstance(v, int) or (isinstance(v, float) and v.is_integer()))


def check_value(step: dict, obj: dict) -> tuple[bool, Any]:
    """(geçerli mi, normalize değer). Kesin tip: '9' metni sayı sayılmaz."""
    intent, value = obj.get("intent"), obj.get("value")
    if intent not in INTENTS:
        return False, None
    if intent != "answer":
        return True, None
    kind = step["kind"]
    if kind == "Score":
        lo = 0 if step["code"] == "Q12" else step["min"]
        ok = _is_int(value) and lo <= value <= step["max"]
        return ok, int(value) if ok else None
    if kind in ("YesNo", "CheckIn"):
        return isinstance(value, bool), value
    if kind == "Choice":
        ok = isinstance(value, str) and value in {c["value"] for c in step["choices"]}
        return ok, value if ok else None
    if kind == "Duration":
        ok = _is_int(value) and value >= 0
        return ok, int(value) if ok else None
    if kind in ("CallbackTime", "OpenText"):
        ok = isinstance(value, str) and bool(value.strip())
        return ok, value.strip() if ok else None
    return False, None


class FlowDriver:
    def __init__(self, scenario: dict, llm, values: dict[str, str] | None = None):
        self.sc = scenario
        self.steps = S.step_map(scenario)
        self.llm = llm
        self.values = {**S.sample_values(scenario), **(values or {})}
        self.texts = S.load_overrides(scenario["key"])
        self.current: str | None = None
        self.retries = 0
        self.finished = False
        self.outcome: str | None = None
        self.answers: list[dict] = []
        self.path: list[str] = []

    # ---- metin ----------------------------------------------------------------------------------
    def text_of(self, key: str) -> str:
        step = self.steps[key]
        return S.fill(self.texts.get(key, step["defaultText"]), self.values)

    def _node_event(self, step: dict, spoken: str) -> dict:
        return {"type": "node", "key": step["key"], "code": step["code"], "title": step["title"], "kind": step["kind"],
                "group": step["group"], "spoken": spoken, "terminal": step["kind"] == "Terminal"}

    def _advance(self, key: str, reply: Reply, prefix: str = "") -> None:
        """key adımından başlayarak Statement'ları okuyup ilk soruda ya da kapanışta durur."""
        first = True
        while True:
            step = self.steps[key]
            self.path.append(key)
            text = self.text_of(key)
            reply.utterances.append((prefix + text) if first else text)
            reply.events.append(self._node_event(step, reply.utterances[-1]))
            first = False
            if step["kind"] == "Terminal":
                self._finish(step["outcome"], reply)
                self.current = key
                return
            if step["kind"] == "Statement":
                key = S.next_step(step, None)
                continue
            self.current, self.retries = key, 0
            return

    def _finish(self, outcome: str | None, reply: Reply) -> None:
        self.finished, self.outcome, reply.finished, reply.outcome = True, outcome, True, outcome
        label = next((o["label"] for o in self.sc["outcomes"] if o["key"] == outcome), outcome)
        reply.events.append({"type": "outcome", "outcome": outcome, "label": label})

    # ---- akış -----------------------------------------------------------------------------------
    def start(self) -> Reply:
        reply = Reply()
        self._advance(self.sc["steps"][0]["key"], reply)
        return reply

    def _extract(self, step: dict, utterance: str) -> tuple[dict | None, float | None]:
        if step["kind"] == "OpenText":
            return {"intent": "answer", "value": utterance.strip()}, None
        t0 = time.perf_counter()
        res = self.llm.complete(build_messages(step, self.text_of(step["key"]), utterance), 120, 0.0)
        obj, _ = parse_output(res.text)
        return obj, round(time.perf_counter() - t0, 3)

    def handle(self, utterance: str) -> Reply:
        reply = Reply()
        if self.finished or self.current is None:
            return reply
        key = self.current
        step = self.steps[key]
        obj, reply.llm_s = self._extract(step, utterance)
        ok, value = check_value(step, obj) if obj is not None else (False, None)
        intent = obj.get("intent") if ok and obj else "unclear"
        reply.events.append({"type": "understood", "step": key, "intent": intent, "value": value, "llm_s": reply.llm_s,
                             "valid": ok})
        if intent == "answer":
            return self._accept(step, utterance, value, reply)
        if intent == "repeat":
            reply.utterances.append(self.text_of(key))
            return reply
        if intent == "refuse":
            return self._exit("kapanis_ret", reply)
        if intent == "dnc":
            return self._exit("kapanis_dnc", reply)
        if intent == "callback" and "randevu" in self.steps and key != "randevu":
            self._advance("randevu", reply)
            return reply
        if intent == "off_topic" and self.retries < MAX_RETRIES:
            self.retries += 1
            reply.utterances.append("Sorunuzu not aldım, şimdi anketimize devam edelim. " + self.text_of(key))
            return reply
        return self._retry(step, reply)

    def _retry(self, step: dict, reply: Reply) -> Reply:
        key = step["key"]
        if self.retries < MAX_RETRIES:
            self.retries += 1
            q = self.text_of(key)
            if self.retries == 1:
                reply.utterances.append("Özür dilerim, tam anlayamadım. " + q)
            else:
                hint = HINTS.get(step["kind"]) or (
                    "Lütfen " + (f"{'sıfır' if step['code'] == 'Q12' else 'bir'} ile on arasında bir puan söyleyin."
                                 if step["kind"] == "Score" else
                                 "şunlardan birini söyleyin: " + ", ".join(c["label"] for c in step["choices"]) + "."
                                 if step["kind"] == "Choice" else "kısaca cevaplayın."))
                reply.utterances.append(f"Kusura bakmayın, tekrar soruyorum. {q} {hint}")
            return reply
        if step["kind"] in ("Score", "Duration", "OpenText", "CheckIn"):
            return self._accept(step, "", None, reply, unanswered=True)
        reply.utterances.append(FALLBACK_CLOSE)
        reply.events.append({"type": "node", "key": "sistem_sonlandirdi", "code": None, "title": "Sistem sonlandırdı",
                             "kind": "Terminal", "group": "Erken Kapanış", "spoken": FALLBACK_CLOSE, "terminal": True})
        self._finish("sistem_sonlandirdi", reply)
        return reply

    def _exit(self, target: str, reply: Reply) -> Reply:
        self._advance(target, reply)
        return reply

    def _accept(self, step: dict, utterance: str, value: Any, reply: Reply, unanswered: bool = False) -> Reply:
        key = step["key"]
        self.answers.append({"step": key, "code": step["code"], "title": step["title"], "kind": step["kind"],
                             "value": value, "utterance": utterance, "unanswered": unanswered})
        reply.events.append({"type": "answer", **self.answers[-1]})
        if key == "q2" and value is not None:
            self.values["Q2"] = number_to_words(int(value))
        if step["kind"] == "CallbackTime" and value:
            self.values["RANDEVU"] = value
        if step["kind"] == "CheckIn" and value is True:
            # PoC'de serbest soruları yanıtlayan bilgi bankası yok (Faz 2): soru kaydedilir, bilgilendirme sürer.
            reply.utterances.append(QUESTION_NOTED)
        self._advance(S.next_step(step, value if not unanswered else None), reply)
        return reply
