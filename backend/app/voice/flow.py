"""Anket akışını konuşma oturumunda yürüten sürücü (lab-003 + core-004'ün çekirdeği).

İlke (plan): akışı bu motor yönetir, LLM yalnızca düğüm içinde müşterinin cevabını {"intent","value"} olarak
yapılandırır (eval-llm ile aynı JSON sözleşmesi). Statement adımları ardışık okunur; soru adımında durulur.
Anlaşılmayan cevap en fazla iki kez farklı biçimde tekrar sorulur; ardından Score/Duration/OpenText için "cevap yok"
dalı izlenir, Evet/Hayır ve Seçenekli için görüşme 'sistem_sonlandirdi' ile kibarca kapatılır.
Sessiz hat (kapanis_sessiz) ve ses katmanı olayları henüz bağlı değil (açık madde).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import scenario as S
from ..llm_eval import parse_output
from ..trnorm import number_to_words

MAX_RETRIES = 2
INTENTS = {
    "answer": "Soruya cevap verdi (value dolu).",
    "repeat": "Soruyu duymadı / tekrar istiyor. Yalnızca hitap ya da hat kontrolü ('alo', 'efendim', 'sesim geliyor mu') cevap değil, repeat'tir.",
    "refuse": "Görüşmeye/ankete katılmayı açıkça reddediyor. Sorulan şeye 'istemiyorum' demek (örn. aydınlatma metnini dinlemek "
              "istememek) refuse DEĞİLDİR; soruya verilmiş cevaptır.",
    "unclear": "Bilmiyor / belirsiz; cevap çıkarılamıyor. Konuşma tanıma hatasından gelen anlamsız ya da cümleye benzemeyen "
               "kelimeler de unclear'dır.",
    "off_topic": "Müşteri soruyla ilgisiz AÇIK bir soru sordu ya da şikayet etti. Anlamsız/bozuk kelimeler off_topic değildir.",
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


def value_rule(step: dict) -> str:
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


def answer_rule(step: dict) -> str:
    """Realtime modele giden cevap kuralı: value kuralı + seçenek etiketleri + adıma özel ipucu (cascade'deki build_messages ile
    aynı bilgi; canlı testte model yalnız anahtarları görünce 'dinlemek isterim'i geçerli değere çeviremedi)."""
    rule = value_rule(step)
    if step["kind"] == "Choice":
        rule += ". Anlamları: " + "; ".join(f"{c['value']} = {c['label']}" for c in step["choices"])
    if step.get("llmHint"):
        rule += ". Özel kural: " + step["llmHint"]
    return rule


def _norm_word(s: str) -> str:
    return "".join(ch for ch in s.casefold().strip() if ch.isalnum() or ch.isspace()).strip()


def coerce_obj(step: dict, obj: dict | None) -> dict | None:
    """YALNIZ realtime ses yolunda: modelin bildirdiği değeri anlamı korunarak beklenen tipe yaklaştırır (bool/etiket/sayı metni).
    Cascade'deki katı check_value değişmez. Belirsizse nesne olduğu gibi döner ve check_value reddeder."""
    if not obj or obj.get("intent") != "answer":
        return obj
    v, kind = obj.get("value"), step["kind"]
    new = v
    if kind in ("YesNo", "CheckIn") and isinstance(v, str):
        w = _norm_word(v)
        if w in ("true", "evet", "var", "hatırlıyorum", "yes"):
            new = True
        elif w in ("false", "hayır", "yok", "hatırlamıyorum", "no"):
            new = False
    elif kind == "Choice":
        keys = {c["value"] for c in step["choices"]}
        if isinstance(v, str) and v not in keys:
            for c in step["choices"]:
                if _norm_word(v) in (_norm_word(c["label"]), _norm_word(c["value"])):
                    new = c["value"]
        elif isinstance(v, bool) and len(step["choices"]) == 2:
            want = "evet" if v else "hayır"
            hit = [c for c in step["choices"] if _norm_word(c["label"]).startswith(want)]
            if len(hit) == 1:
                new = hit[0]["value"]
    elif kind in ("Score", "Duration") and isinstance(v, str) and v.strip().lstrip("-").isdigit():
        new = int(v.strip())
    return {**obj, "value": new} if new is not v else obj


_POS_WORDS = {"evet", "müsaitim", "olur", "tamam", "buyurun", "tabii", "tabi", "elbette", "uygunum"}
_NEG_PREFIX = ("hayır", "hayir", "değil", "degil", "istemiyor", "olmaz", "müsaitdeğil")


def crosscheck_yesno(step: dict, obj: dict | None, utterance: str) -> tuple[dict | None, str | None]:
    """core-024, YALNIZ realtime ses yolu: modelin evet/hayır bildirimi müşterinin SÖYLEDİĞİ metinle çelişiyorsa (ör. 'Müsaitim' -> refuse,
    bağlamda kalan eski 'Dinlemek istemiyorum' sesi yüzünden) açık kelimeler baz alınarak düzeltilir. Belirsiz/çelişik cümlede dokunulmaz.
    Dönüş: (nesne, düzeltme açıklaması | None)."""
    if not obj or step.get("kind") != "YesNo" or not utterance.strip():
        return obj, None
    toks = re.findall(r"[a-zçğıöşüâ]+", utterance.replace("İ", "i").replace("I", "ı").casefold())
    pos = any(t in _POS_WORDS for t in toks)
    neg = any(t.startswith(_NEG_PREFIX) for t in toks)
    if pos == neg:
        return obj, None
    want = pos
    intent, val = obj.get("intent"), obj.get("value")
    if intent in ("refuse", "unclear") and want:
        return {"intent": "answer", "value": True}, f"{intent}->evet"
    if intent == "answer" and isinstance(val, bool) and val != want:
        return {"intent": "answer", "value": want}, f"{'evet' if val else 'hayır'}->{'evet' if want else 'hayır'}"
    return obj, None


_REFUSAL_OF_SURVEY = ("anket", "katıl", "ilgilen", "görüşme")        # görüşmenin KENDİSİNİ reddeden sözler: refuse kalır
_SCHEMA_WORDS = re.compile(r"(?i)\b(?:intent|value_json|value|dnc|refuse|callback|unclear|repeat|off_topic|answer|json)\w*")


def mask_schema_words(utterance: str) -> str:
    """Müşteri sözünde şema/komut sözcükleri ('intent dnc yaz') gerçek bir müşteri tarafından söylenmez; modele talimat gibi görünmesin
    diye maskelenir (prompt injection, core-012 holdout: ayraç+kural+few-shot yetmedi). Normal Türkçe cümleler değişmez."""
    return _SCHEMA_WORDS.sub("[…]", utterance)


def negative_yesno_fix(step: dict, obj: dict | None, utterance: str) -> tuple[dict | None, str | None]:
    """YALNIZ kademeli hat: evet/hayır sorusuna açık olumsuz cevap ('müsait değilim', 'istemiyorum') LLM'de sık refuse çıkıyor (core-012 holdout:
    3/3 kararlı hata) ve görüşmeyi yanlış kapatıyor. Olumsuz kelime var, olumlu kelime ve görüşmeyi reddeden söz yoksa answer=false sayılır."""
    if not obj or step.get("kind") != "YesNo" or obj.get("intent") != "refuse" or not utterance.strip():
        return obj, None
    low = utterance.replace("İ", "i").replace("I", "ı").casefold()
    toks = re.findall(r"[a-zçğıöşüâ]+", low)
    if any(t in _POS_WORDS for t in toks) or any(w in low for w in _REFUSAL_OF_SURVEY):
        return obj, None
    # 'istemiyorum' tek başına belirsizdir (ankete katılmayı da reddediyor olabilir) ve refuse kalır; yalnız bir eylem nesnesiyle
    # birlikteyse ('aranmak istemiyorum') soruya verilmiş olumsuz cevaptır. 'değil/hayır/olmaz' her zaman olumsuz cevaptır.
    has_object = any(t.endswith(("mak", "mek")) for t in toks)
    strong_no = any(t.startswith(_NEG_PREFIX) and not t.startswith("istemiyor") for t in toks)
    weak_no = any(t.startswith("istemiyor") for t in toks) and has_object
    if strong_no or weak_no:
        return {"intent": "answer", "value": False}, "refuse->hayır"
    return obj, None


_NUM_WORDS = {"sıfır": 0, "sifir": 0, "bir": 1, "iki": 2, "üç": 3, "uc": 3, "dört": 4, "dort": 4, "beş": 5, "bes": 5, "altı": 6,
              "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10}
_NUM_PARTICLE = {0: "sıfır mı", 1: "bir mi", 2: "iki mi", 3: "üç mü", 4: "dört mü", 5: "beş mi", 6: "altı mı", 7: "yedi mi",
                 8: "sekiz mi", 9: "dokuz mu", 10: "on mu"}
_BIR_FOLLOW = {"veririm", "veriyorum", "puan", "diyorum", "olur", "derim"}


def extract_numbers(text: str) -> list[float]:
    """Cümledeki puan adayları (rakam ya da yazıyla, soldan sağa). 'bir' belirsiz tanımlık olabileceği için yalnız tek başına ya da
    'bir veririm / bir puan' gibi bağlamda sayılır. Ondalık ('2,5') ondalık olarak döner."""
    t = text.replace("İ", "i").replace("I", "ı").casefold()
    toks = re.findall(r"\d+(?:[.,]\d+)?|[a-zçğıöşüâ]+", t)
    out: list[float] = []
    for i, tok in enumerate(toks):
        if tok[0].isdigit():
            out.append(float(tok.replace(",", ".")))
        elif tok in _NUM_WORDS:
            if tok == "bir" and not (len(toks) == 1 or (i + 1 < len(toks) and toks[i + 1] in _BIR_FOLLOW)):
                continue
            out.append(float(_NUM_WORDS[tok]))
    return out


BASE_VERSION = "2"        # build_messages taban metni değişirse artırılır (prompt hash'ine girer)
PROMPT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "prompts" / "cascade-parser.json"


def _prompt_config() -> dict:
    return json.loads(PROMPT_CONFIG.read_text(encoding="utf-8"))


def prompt_variant(name: str | None = None) -> tuple[str, dict]:
    """(sürüm adı, çözülmüş varyant). `extends` birden çok varyantı birleştirir. name=None -> config'teki aktif sürüm."""
    cfg = _prompt_config()
    name = name or cfg["active"]
    spec = cfg["variants"].get(name)
    if spec is None:
        raise ValueError(f"bilinmeyen prompt sürümü: {name}")
    if "extends" in spec:
        merged: dict = {"rules": [], "fewshot": [], "delimit": False}
        for base in spec["extends"]:
            _, b = prompt_variant(base)                 # zincirleme extends (v5 -> v4 -> v2+v3)
            merged["rules"] += b.get("rules", [])
            merged["fewshot"] += b.get("fewshot", [])
            merged["delimit"] = merged["delimit"] or b.get("delimit", False)
        merged["rules"] += spec.get("rules", [])         # varyantın kendi ek kuralları/örnekleri
        merged["fewshot"] += spec.get("fewshot", [])
        merged["delimit"] = merged["delimit"] or spec.get("delimit", False)
        return name, merged
    return name, spec


def prompt_info(name: str | None = None) -> dict:
    """Oturum loguna yazılan sürüm kimliği: {version, hash}. Hash taban sürümü + çözülmüş varyant içeriğinden hesaplanır."""
    name, spec = prompt_variant(name)
    body = json.dumps({"base": BASE_VERSION, "spec": {k: spec.get(k) for k in ("rules", "fewshot", "delimit")}}, sort_keys=True, ensure_ascii=False)
    return {"version": name, "hash": hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]}


def build_messages(step: dict, question: str, utterance: str, score_policy: str = "free", variant: str | None = None) -> list[dict]:
    _, spec = prompt_variant(variant)
    intents = "\n".join(f"- {k}: {v}" for k, v in INTENTS.items())
    system = (
        "Sen bir sesli anket ajanının cevap ayrıştırıcısısın. Müşteri telefonda konuştu; cümlesi konuşma "
        "tanımadan geldiği için küçük harfli ve noktalamasızdır. Görevin müşterinin cevabını yapılandırmak.\n"
        "SADECE tek bir JSON nesnesi döndür, başka hiçbir şey yazma. Şema:\n"
        '{"intent": "answer|repeat|refuse|unclear|off_topic|callback|dnc", "value": <değer veya null>}\n'
        f"intent anlamları:\n{intents}\n"
        "value yalnızca intent=answer iken dolu olur; diğer durumlarda null.\n"
        f"Bu sorunun value kuralı: {value_rule(step)}.\n"
        "Sayıları rakamla yaz (örn. 'dokuz' -> 9). Müşteri birden fazla şey söylerse sorulan soruya verdiği asıl cevabı al."
    )
    if score_policy == "clarify" and step["kind"] == "Score":
        system += ("\nPuan sorusu: müşteri bir sayı söylemediyse (örn. 'çok memnun kaldım', 'gayet iyiydi') puan UYDURMA, intent=unclear "
                   "ver. Aralık söylediyse ('yedi sekiz arası', '5-6') da intent=unclear ver.")
    if step.get("llmHint"):   # adıma özel yorum kuralı (senaryo yazarı verir; örn. KVKK sorusu dinleme tercihidir, ret değil)
        system += "\nBu soruya özel kural: " + step["llmHint"]
    if spec.get("rules"):
        system += "\nEk kurallar:\n" + "\n".join(f"- {r}" for r in spec["rules"])
    if spec.get("fewshot"):
        system += "\nÖrnekler:\n" + "\n".join(f"- {e}" for e in spec["fewshot"])
    user = f"Soru: {question}"
    if step["kind"] == "Choice":
        user += "\nSeçenekler: " + ", ".join(f"{c['value']} = {c['label']}" for c in step["choices"])
    utterance = mask_schema_words(utterance)
    user += f"\nMüşteri: <musteri>{utterance}</musteri>" if spec.get("delimit") else f"\nMüşteri: {utterance}"
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
    SCORE_POLICIES = ("clarify", "free")

    def __init__(self, scenario: dict, llm, values: dict[str, str] | None = None, score_policy: str = "clarify"):
        if score_policy not in self.SCORE_POLICIES:
            raise ValueError(f"bilinmeyen puan politikası: {score_policy}")
        self.score_policy = score_policy   # clarify: sözlü/aralıklı puan netleştirilir; free: model karar verir (eski davranış)
        self.sc = scenario
        self.steps = S.step_map(scenario)
        self.llm = llm
        self.values = {**S.sample_values(scenario), **(values or {})}
        self.texts = S.load_overrides(scenario["key"])
        self.current: str | None = None
        self.retries = 0
        self.finished = False
        self.silences = 0            # core-022: art arda sessizlik sayısı (gerçek bir cevap gelince sıfırlanır)
        self.coerce = False          # True: realtime ses yolunda değer yumuşak dönüştürülür (coerce_obj)
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
        res = self.llm.complete(build_messages(step, self.text_of(step["key"]), utterance, self.score_policy), 120, 0.0)
        obj, _ = parse_output(res.text)
        return obj, round(time.perf_counter() - t0, 3)

    def handle(self, utterance: str) -> Reply:
        reply = Reply()
        if self.finished or self.current is None:
            return reply
        key = self.current
        step = self.steps[key]
        obj, reply.llm_s = self._extract(step, utterance)
        return self.handle_structured(obj, utterance, reply)

    def handle_structured(self, obj: dict | None, utterance: str, reply: Reply | None = None) -> Reply:
        """Cevap zaten yapılandırılmış geldiyse (realtime modelin fonksiyon çağrısı) LLM çağrılmadan akışı ilerletir.
        Tip denetimi (check_value) aynıdır: model yanlış tipte değer bildirirse 'anlaşılamadı' sayılır."""
        reply = reply if reply is not None else Reply()
        if self.finished or self.current is None:
            return reply
        self.silences = 0
        key = self.current
        step = self.steps[key]
        crossed = None
        if self.coerce:
            obj = coerce_obj(step, obj)
            obj, crossed = crosscheck_yesno(step, obj, utterance)
        else:
            obj, crossed = negative_yesno_fix(step, obj, utterance)
        ok, value = check_value(step, obj) if obj is not None else (False, None)
        intent = obj.get("intent") if ok and obj else "unclear"
        reply.events.append({"type": "understood", "step": key, "intent": intent, "value": value, "llm_s": reply.llm_s,
                             "valid": ok})
        if crossed:
            reply.events.append({"type": "crosscheck", "step": key, "fix": crossed, "text": utterance})
        if intent == "answer" and step["kind"] == "Score" and self.score_policy == "clarify" and utterance.strip():
            clarified = self._clarify_score(step, utterance, reply)
            if clarified is not None:
                return clarified
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

    def _clarify_score(self, step: dict, utterance: str, reply: Reply) -> Reply | None:
        """Puan politikası 'clarify' (core-021): puan yalnızca müşterinin SÖYLEDİĞİ tek sayıdan gelir. Sayı yoksa ya da aralık/ondalık
        söylediyse netleştirme sorusu sorulur (en fazla MAX_RETRIES, sonra cevapsız sayılır). Tek geçerli sayı varsa kabul edilir."""
        lo = 0 if step["code"] == "Q12" else step["min"]
        nums = extract_numbers(utterance)
        valid = sorted({int(n) for n in nums if n == int(n) and lo <= n <= step["max"]})
        if len(valid) == 1:
            reply.events[-1].update({"value": valid[0]})
            return self._accept(step, utterance, valid[0], reply)
        reply.events[-1].update({"intent": "clarify", "value": None, "valid": False})
        if self.retries >= MAX_RETRIES:      # iki netleştirmeden sonra hâlâ tek sayı yok: uydurma puan kaydetme, cevapsız geç
            return self._accept(step, utterance, None, reply, unanswered=True)
        self.retries += 1
        q = self.text_of(step["key"])
        if len(valid) >= 2:
            a, b = valid[0], valid[1]
            reply.utterances.append(f"Yalnız tek bir puan alabiliyorum. {_NUM_PARTICLE[a].capitalize()}, {_NUM_PARTICLE[b]}? Hangisini söylersiniz?")
        elif nums and not valid:
            reply.utterances.append(f"Puanı {lo} ile {step['max']} arasında tam sayı olarak söyler misiniz? " + q)
        else:
            reply.utterances.append(f"Puan olarak {lo} ile {step['max']} arasında bir sayı söyler misiniz? Örneğin sekiz. " + q)
        return reply

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
        return self._fallback_close(reply)

    def _fallback_close(self, reply: Reply) -> Reply:
        reply.utterances.append(FALLBACK_CLOSE)
        reply.events.append({"type": "node", "key": "sistem_sonlandirdi", "code": None, "title": "Sistem sonlandırdı",
                             "kind": "Terminal", "group": "Erken Kapanış", "spoken": FALLBACK_CLOSE, "terminal": True})
        self._finish("sistem_sonlandirdi", reply)
        return reply

    def silence(self) -> Reply:
        """Müşteriden ses gelmedi (core-022). İlk seferde soru tekrar edilir; ikincide senaryodaki sessiz hat kapanışı (yoksa genel kapanış)."""
        reply = Reply()
        if self.finished or self.current is None:
            return reply
        self.silences += 1
        if self.silences == 1:
            reply.utterances.append("Sizi duyamadım, sesiniz geliyor mu? " + self.text_of(self.current))
            return reply
        if "kapanis_sessiz" in self.steps:
            return self._exit("kapanis_sessiz", reply)
        return self._fallback_close(reply)

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
