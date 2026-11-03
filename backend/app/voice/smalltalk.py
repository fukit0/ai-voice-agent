"""off-001 konuşma katmanı (docs/offtopic-baglam-iyilestirme.md, ADR 0009'un 2. adımının LLM'siz ilk dilimi).

Akışı kod yönetir (FlowDriver); bu modül yalnızca NE SÖYLENECEĞİNİ seçer:
- konu dışı sözün kategorisi (kimlik, kim arıyor, numara kaynağı, kayıt, süre, amaç, destek talebi, hava, hal hatır, şaka, hakaret,
  bekletme, diğer) -> kısa, dürüst karşılık + soruya köprü;
- akış kuralını koruyan sinyaller: açık DNC sözü ('bir daha aramayın'), görüşmeyi reddeden söz (kimlik kısa yolu bunları yutmasın);
- bağlam: müşteri cevabındaki olumsuz duygu (empati tepkisi), geri arama isteğindeki zaman ifadesi ('yarın akşam').

Neden kural + havuz, LLM değil: (1) gecikme: konu dışı ve tepki cümlesi ek LLM çağrısı gerektirmez (ölçüm: katman < 1 ms); (2) güvenlik:
cümleler sabit, gözden geçirilmiş havuzdan gelir, müşteri sözü hiçbir zaman tekrarlanmaz, yani enjeksiyon yüzeyi yoktur; (3) test
edilebilirlik. Sınır: kapsam sözlükle sınırlıdır; tanınmayan konu dışı söz 'other' kovasına düşer (yine kısa ve kibar).
Kategoriler YALNIZ ayrıştırıcının off_topic/unclear dediği (ya da açık uçlu adımda soru biçimli kısa) sözlere uygulanır; geçerli bir
cevabı (answer), DNC, ret ve geri arama kararlarını değiştirmez (DNC yönünde güçlendirme hariç).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[3] / "config" / "smalltalk.json"
OFFTOPIC_CLOSE_AT = 3          # art arda bu kadar konu dışı (kimlik hariç) -> nazik kapanış; 2. seferde geri arama önerilir
META = ("identity", "who", "number_source", "recording", "duration", "purpose")    # cevapla birlikte gelse de kısaca yanıtlanır
ASKS_BACK = ("counter", "clarify")    # ADR 0009 adım 2: karşı soru / açıklama isteği; açık uçlu adımda cevap olarak kaydedilmez
CHAT_ASKS = ("weather", "chitchat", "topic_change")   # off-003 (docs/serbest-cevap-haiku.md): açık uçlu adımda kısa soru biçimli sohbet cevap değildir
TOPIC_SWITCH_MAX_TOKENS = 16          # açık 'başka bir şey konuşalım' sözü bu uzunluğa kadar açık uçlu adımda da cevap sayılmaz


@lru_cache(maxsize=1)
def config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def low(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").casefold().replace("â", "a").replace("î", "i").replace("û", "u")


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts))


B = r"(?<![a-zçğıöşü])"        # kelime başı (Türkçe harfler dahil)
# Açık konu değiştirme sözü: 'başka bir şey konuşalım', 'konuyu değiştirelim', 'biraz sohbet edelim'
TOPIC_SWITCH_SRC = "|".join((
    B + r"başka\s+(?:bir\s+)?(?:şey|şeyler|konu\w*)\s+(?:\w+\s+)?(?:konuş|sohbet|anlat|lafla)\w*",
    B + r"konu(?:yu)?\s+değiştir\w*",
    B + r"(?:biraz\s+)?(?:sohbet|muhabbet)\s+(?:ed(?:elim|er\s+mi\w*|ebilir\s+mi\w*)|yapalım)",
    B + r"laflayalım"))
# Sıra önemli: ilk eşleşen kategori kazanır (kimlik > numara > kayıt > kim > süre > amaç > bekletme > destek > hakaret > şaka > hava > hal hatır)
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("identity", _rx(B + r"(?:bot|robot|makine|bilgisayar|yapay\s+zek\w*|insan|gerçek\s+(?:bir\s+)?(?:insan|kişi))\s*(?:y?la|y?le|ile)\s+m[ıi]\s+konuş",
                     B + r"(?:bot|robot|yapay\s+zek\w*)\s+m[ıiuü](?:sun|sın|sin|sün)?(?:uz|ız|iz|üz)?(?![a-zçğıöşü])",
                     B + r"(?:bot|robot|yapay\s+zek\w*|insan|gerçek\s+(?:bir\s+)?(?:insan|kişi))\s+m[ıiuü]s[ıiuü]n",
                     B + r"kayıtlı\s+ses\s+m[ıi]", B + r"bant\s+kayd")),
    ("number_source", _rx(B + r"(?:numara|telefon|cep)\w*\s+(?:\w+\s+){0,3}?(?:nere|kim|nasıl|nerden)\w*",
                          B + r"(?:nere|kim|nerden)\w*\s+(?:\w+\s+){0,3}?(?:numara|telefon)\w*")),
    ("recording", _rx(B + r"kay(?:ıt|d)\w*\s+(?:m[ıi]|altında|al[ıi]n[ıi]yor|ediliyor|yap[ıi]l[ıi]yor|yap[ıi]yor|alıyor)",
                      B + r"kaydedil\w*", B + r"kaydediyor\w*", B + r"ses\s+kayd\w*", B + r"kaydı\s+m[ıi]")),
    ("who", _rx(B + r"kimsin\w*", B + r"kimsiniz", B + r"siz\s+kim", B + r"sen\s+kim", B + r"kim\s+ar[ıi]yor",
                B + r"nereden\s+ar[ıi]yor", B + r"nerden\s+ar[ıi]yor", B + r"hangi\s+(?:firma|şirket|kurum|yer)\w*", B + r"kimin\s+adına")),
    ("duration", _rx(B + r"ne\s+kadar\s+sür", B + r"kaç\s+dakika\s+sür", B + r"kaç\s+soru", B + r"(?:çok|daha)\s+(?:çok\s+)?soru\s+var",
                     B + r"uzun\s+mu\s+sür", B + r"bitmedi\s+mi", B + r"ne\s+zaman\s+bit", B + r"az\s+m[ıi]\s+kald")),
    ("purpose", _rx(B + r"ne\s+anketi", B + r"anket\w*\s+ne\s+(?:için|hakkında|ile)", B + r"ne\s+için\s+ar[ıi]yor", B + r"neden\s+ar[ıi]yor",
                    B + r"niye\s+ar[ıi]yor", B + r"ne\s+hakkında", B + r"konu\s+ne", B + r"amac\w*\s+ne")),
    ("hold", _rx(B + r"bir\s+saniye", B + r"bir\s+sn\b", B + r"bekle(?:r\s+mis|yin|r\s+mısın|yiver)", B + r"hemen\s+geliyorum", B + r"az\s+bekle")),
    ("support", _rx(B + r"ilan\w*", B + r"iade\w*", B + r"param\b", B + r"param[ıi]\w*", B + r"ücret\w*", B + r"fatura\w*", B + r"hesab[ıi]m\w*",
                    B + r"şifre\w*", B + r"üyeli\w*", B + r"dolandır\w*", B + r"ödeme\w*", B + r"yayından\s+kald")),
    ("profanity", _rx(B + r"(?:salak|aptal|gerizekal|geri\s+zekal|ahmak|şerefsiz|siktir|amk\b|aq\b|lan\b|mal\s+m[ıi]s|saçma|defol|kahrol|bıktım|"
                      r"embesil|dangalak|yeter\s+ya)")),
    ("joke", _rx(B + r"evlen\w*", B + r"fıkra\w*", B + r"şaka\w*", B + r"sevgili\w*", B + r"kaç\s+yaşında", B + r"espri\w*", B + r"yakışıklı",
                 B + r"güzel\s+misin")),
    ("weather", _rx(B + r"hava\b", B + r"havalar", B + r"hava\s+nas", B + r"yağmur\w*", B + r"kar\s+yağ", B + r"sıcak\s+m[ıi]", B + r"soğuk\s+m[ıi]",
                    B + r"bugün\s+hava", B + r"sıcak\s+değil\s+mi")),
    ("chitchat", _rx(B + r"nasılsın\w*", B + r"nasılsınız", B + r"naber", B + r"ne\s+haber", B + r"iyi\s+misin\w*", B + r"napıyorsun\w*",
                     B + r"ne\s+yapıyorsun\w*")),
    # ADR 0009 adım 2 (docs/serbest-cevap-qwen.md): müşteri soruyu ajana geri soruyor / ajanın fikrini ya da puanını soruyor
    ("counter", _rx(B + r"(?:sen|siz)(?:ce|de|\s+de)?\s+(?:kaç|ne)\s+(?:puan\s+)?(?:ver|der|düşün|söyle)",
                    B + r"(?:sence|sizce)(?![a-zçğıöşü])", B + r"(?:sen|siz)\s+olsa(?:n|nız|ydın|ydınız)(?![a-zçğıöşü])",
                    B + r"ne\s+düşünüyorsun\w*", B + r"kaç\s+puan\s+(?:vereyim|versem|vermeliyim|vermem\s+lazım)",
                    B + r"ne\s+(?:diyeyim|desem|söyleyeyim)", B + r"(?:siz|sen)\s+bilirsin\w*")),
    # sorunun ne anlama geldiğini ya da neden sorulduğunu soruyor
    # çıplak 'ne demek' bilinçli olarak YOK: anlaşılmama tekrarı (unclear) olarak kalır (test_survey_e2e dal B)
    ("clarify", _rx(B + r"(?:bu|o|şu|bunun|onun)\s+ne\s+demek", B + r"ne\s+demek\s+(?:ist|yani|oluyor)", B + r"ne\s+kastet\w*", B + r"kastınız", B + r"nasıl\s+yani",
                    B + r"yani\s+ne(?![a-zçğıöşü])", B + r"(?:bunu|bunları|neden|niye|niçin)\s+(?:\w+\s+)?sor(?:uyorsunuz|uyorsun|uluyor)",
                    B + r"anlamadım\s+(?:ne|neyi|soruyu|bunu)", B + r"(?:açar|açıklar)\s+m[ıi]s[ıi]n\w*", B + r"daha\s+açık\s+(?:söyle|anlat)")),
    # off-003 (docs/serbest-cevap-haiku.md): konuyu değiştirme isteği ya da ankette olmayan güncel bilgi sorusu (havaalanı, trafik, uçuş, maç,
    # kur, saat). Listenin SONUNDA: hava/şaka/hal hatır gibi daha özel kategoriler önce kazanır. 'başka zaman konuşalım' geri aramadır, burada yok.
    ("topic_change", _rx(TOPIC_SWITCH_SRC,
                         B + r"(?:havaalan|havaliman|trafik|yollar|uçuş|uçak|maç|borsa|dolar|euro|altın)\w*\s+(?:\w+\s+){0,2}?"
                             r"(?:nasıl|ne\s+durumda|kaç|var\s+m|açık\s+m|kalabalık\s+m|oldu\s+mu|bitti\s+mi|ne\s+kadar)",
                         B + r"saat\s+kaç(?![a-zçğıöşü])", B + r"haberler\w*\s+(?:\w+\s+)?(?:ne|nasıl|var\s+m)")),
]
_TOPIC_SWITCH = re.compile(TOPIC_SWITCH_SRC)

_DNC = _rx(B + r"bir\s+daha\s+(?:beni\s+)?ara(?:may|mayın|mayınız|maz)", B + r"beni\s+(?:bir\s+daha\s+)?aramay", B + r"aramayın\s+artık",
           B + r"artık\s+(?:beni\s+)?aramay", B + r"hiç\s+(?:beni\s+)?aramay", B + r"liste\w*\s+(?:den\s+)?çıkar", B + r"numaramı\s+sil",
           B + r"numaram[ıi]\s+(?:listeden\s+)?silin")
_REFUSAL = ("ilgilenm", "katılm", "katilm", "istemiyorum", "aramay", "aranmak istem", "kapat", "rahatsız etme", "listeniz")
_QUESTIONISH = re.compile(B + r"(?:m[ıiuü]|m[ıiuü]s[ıiuü]n\w*|m[ıiuü]y[ıiuü]m|nere\w*|nerden|kim\w*|ne\s+kadar|kaç|hangi|neden|niye|nasıl)(?![a-zçğıöşü])")

# --- duygu (yalnız tepki seçimi için; cevap değerini ASLA etkilemez) ---
_NEG_STEMS = ("kötü", "berbat", "rezalet", "rezil", "felaket", "kaba", "terslen", "tersledi", "sinir", "bıktı", "beklet", "bekledim", "bekliyorum",
              "saatlerce", "çözülmedi", "çözemedi", "çözmedi", "çözülmed", "ilgilenmedi", "ilgisiz", "şikayet", "şikâyet", "donuyor", "çöküyor",
              "yetersiz", "yavaş", "maalesef", "mağdur", "sorunum", "sorun yaşadım", "problem")
_NEG_PHRASES = ("memnun değil", "memnun kalmadım", "hiç memnun", "memnun olmadım", "hiç beğenmedim", "beğenmedim", "yardımcı olmadı",
                "yardımcı olmadılar", "işe yaramadı", "hiç iyi değil")
_NEGATORS = ("değil", "değildi", "değildir", "olmadı", "yoktu", "yok")

# --- geri arama zamanı ---
_DAY = {"yarın", "bugün", "akşam", "akşama", "akşamüstü", "sabah", "sabaha", "öğle", "öğlen", "öğleden", "öğlene", "haftaya", "hafta",
        "pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar", "gece", "mesai", "saat", "saatte"}
_TIME_CONT = {"sonra", "gibi", "civarı", "civarında", "buçuk", "buçukta", "içinde", "başı", "sularında", "geç", "erken", "üzeri", "üstü",
              "doğru", "bu", "dakika", "dakikaya", "saat", "saate", "saatte", "saatlerinde", "ortası", "ortasında", "sonu", "sonunda", "başında",
              "içi", "ilk", "yarım", "çeyrek", "kala", "geçe"}
_NUM_ROOTS = ("bir", "iki", "üç", "dört", "dörd", "beş", "altı", "yedi", "sekiz", "dokuz", "on", "yirmi", "otuz", "kırk", "elli")
_NUM_SUFFIX = ("", "de", "da", "te", "ta", "den", "dan", "ten", "tan", "e", "a", "ye", "ya", "i", "ı", "yi", "yı")


def categorize(utterance: str) -> str | None:
    """Konu dışı sözün kategorisi; hiçbiri eşleşmezse None (çağıran 'other' kullanır)."""
    t = low(utterance)
    for cat, rx in PATTERNS:
        if rx.search(t):
            return cat
    return None


def dnc_phrase(utterance: str) -> bool:
    """Açık 'beni bir daha aramayın / listenizden çıkarın' sözü. YALNIZ ayrıştırıcının off_topic/unclear dediği sözleri DNC'ye yükseltmek
    ve kimlik kısa yolunu atlamak için kullanılır: yasal yön (aranmama isteğine uymak) güvenli yöndür. 'sonra arayın' DNC değildir."""
    return bool(_DNC.search(low(utterance)))


def exit_signal(utterance: str) -> bool:
    """Sözde DNC, görüşmeyi reddetme ya da geri arama isteği var mı: varsa LLM'siz kısa yollar (kimlik) devreye GİRMEZ, karar akışa kalır."""
    t = low(utterance)
    return dnc_phrase(t) or any(w in t for w in _REFUSAL)


def pure_meta(utterance: str) -> str | None:
    """Açık uçlu adımda (LLM çağrılmayan) soru biçimli, kısa, META kategorisinde söz: cevap olarak kaydedilmemeli. Kategori ya da None."""
    t = low(utterance)
    toks = re.findall(r"[a-zçğıöşü0-9]+", t)
    if not toks:
        return None
    if len(toks) <= TOPIC_SWITCH_MAX_TOKENS and _TOPIC_SWITCH.search(t):
        # off-003: 'başka bir şey konuşalım ya, mesela havaalanı nasıl bugün' (9 kelime) eskiden açık uçlu adımın CEVABI sayılıp
        # bir sonraki soruya geçiliyordu (müşterinin sözü yok sayılıyordu). Açık konu değiştirme sözü uzun da olsa cevap değildir.
        cat = categorize(t)
        return cat if cat in ASKS_BACK + CHAT_ASKS or cat in META else "topic_change"
    if len(toks) > 7:
        return None
    cat = categorize(t)
    if cat in ASKS_BACK or cat == "chitchat":   # kalıpların kendisi soru biçimli ('sen ne düşünüyorsun', 'nasılsınız'): soru eki şartı yok
        return cat
    if not _QUESTIONISH.search(t):
        return None
    # off-003: kısa soru biçimli sohbet ('nasılsınız', 'hava nasıl', 'saat kaç') da cevap değildir. Şaka bilinçli olarak YOK: kalıpları
    # ('şaka', 'evlen') gerçek bir açık uçlu cevabın içinde geçebilir.
    return cat if cat in META or cat in CHAT_ASKS else None


def meta_category(utterance: str) -> str | None:
    """Geçerli bir cevapla birlikte sorulan kısa meta soru ('evet müsaitim ama numaramı nereden buldunuz'): kategori ya da None."""
    t = low(utterance)
    if not _QUESTIONISH.search(t):
        return None
    cat = categorize(t)
    return cat if cat in META else None


def sentiment(utterance: str) -> str | None:
    """'neg' (müşteri olumsuz bir deneyim söyledi) ya da None. 'kötü değildi' gibi olumsuzlanmış olumsuzlar sayılmaz."""
    t = low(utterance)
    if any(p in t for p in _NEG_PHRASES):
        return "neg"
    toks = re.findall(r"[a-zçğıöşü]+", t)
    for i, tok in enumerate(toks):
        if any(tok.startswith(s) for s in _NEG_STEMS if " " not in s):
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            if nxt.startswith(_NEGATORS) or tok.endswith(("değil", "değildi")):
                continue
            return "neg"
    if any(s in t for s in _NEG_STEMS if " " in s):
        return "neg"
    return None


def _is_num(tok: str) -> bool:
    if tok[:1].isdigit():
        return True
    return any(tok == r + s for r in _NUM_ROOTS for s in _NUM_SUFFIX)


def callback_time(utterance: str) -> str | None:
    """Geri arama isteğindeki zaman ifadesi ('yarın', 'yarın akşam', 'saat beşten sonra', 'on dakika sonra'); yoksa None.
    En az bir gün/gün bölümü/saat çıpası ya da '<sayı> dakika/saat sonra' şartı aranır: çıplak 'sonra arayın' zaman değildir."""
    toks = re.findall(r"\d+(?::\d+)?|[a-zçğıöşü]+", low(utterance))
    best: list[str] = []
    cur: list[str] = []
    for tok in toks + ["\x00"]:
        if tok in _DAY or tok in _TIME_CONT or _is_num(tok):
            cur.append(tok)
            continue
        if cur:
            span = cur
            while span and span[0] in ("bu", "sonra", "gibi", "doğru", "geç", "erken"):
                if span[0] == "bu" and len(span) > 1 and span[1] in _DAY:
                    break
                span = span[1:]
            while span and span[-1] == "bu":
                span = span[:-1]
            anchored = any(w in _DAY or ":" in w for w in span) or (
                "sonra" in span and any(w.startswith(("dakika", "saat")) for w in span) and any(_is_num(w) for w in span))
            if anchored and len(span) > len(best):
                best = span
        cur = []
    return " ".join(best) if best else None


def pick(pool: list[str], used: list[str], rng) -> str:
    """Havuzdan aynı aramada kullanılmamış bir cümle; hepsi kullanıldıysa en azından son söylenenden farklısı (art arda tekrar yok)."""
    last = next((u for u in reversed(used) if u in pool), None)
    fresh = [x for x in pool if x not in used] or [x for x in pool if x != last] or pool
    text = rng.choice(fresh)
    used.append(text)
    return text
