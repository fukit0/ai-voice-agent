"""Türkçe metin normalizasyonu (norm-007, plan F1.7): TTS'e giden metindeki sayı, fiyat, tarih, saat ve
telefon numaralarını okunur biçime çevirir.

Karar: bağımlılıksız, kurala dayalı kendi modülümüz. Gerekçe: (1) kapsam küçük ve anket metinlerine özgü
(ilan fiyatı, oda sayısı "3+1", m², telefon), (2) davranış birim testle sabitlenir, (3) production'da dış
kütüphane sürümü ya da lisansı riski yok. Bilerek kapsam dışı: ek uyumu üretmek (bkz. scn-008), yazıyla
verilmiş sayıları çevirmek, İngilizce metin.

Tek geçişte eşleştirilir; kural sırası (tarih → saat → telefon → para → yüzde → oda → alan → sayı) bir sayının
iki kez dönüştürülmesini önler.
"""
from __future__ import annotations

import re

_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]
_SCALES = [(10**15, "katrilyon"), (10**12, "trilyon"), (10**9, "milyar"), (10**6, "milyon")]
_MONTHS = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
           "Kasım", "Aralık"]
_DIGIT = ["sıfır"] + _ONES[1:]
MAX_NUMBER = 10**18 - 1

# para birimi: simge/kısaltma -> (ana birim, kuruş birimi)
_CURRENCY = {"TL": ("lira", "kuruş"), "₺": ("lira", "kuruş"), "TRY": ("lira", "kuruş"),
             "USD": ("dolar", "sent"), "$": ("dolar", "sent"), "EUR": ("avro", "sent"), "€": ("avro", "sent"),
             "GBP": ("sterlin", "peni"), "£": ("sterlin", "peni")}
_AREA_WORD = {"m²": "metrekare", "m2": "metrekare", "km²": "kilometrekare", "km2": "kilometrekare",
              "km": "kilometre", "kg": "kilogram", "cm": "santimetre", "mm": "milimetre"}
_ORD_LAST = {"bir": "birinci", "iki": "ikinci", "üç": "üçüncü", "dört": "dördüncü", "beş": "beşinci", "altı": "altıncı",
             "yedi": "yedinci", "sekiz": "sekizinci", "dokuz": "dokuzuncu", "on": "onuncu", "yirmi": "yirminci",
             "otuz": "otuzuncu", "kırk": "kırkıncı", "elli": "ellinci", "altmış": "altmışıncı", "yetmiş": "yetmişinci",
             "seksen": "sekseninci", "doksan": "doksanıncı", "yüz": "yüzüncü", "bin": "bininci", "sıfır": "sıfırıncı"}


def _below_thousand(n: int) -> str:
    words = []
    if n >= 100:
        h = n // 100
        words.append(("" if h == 1 else _ONES[h] + " ") + "yüz")  # 100 = "yüz", "bir yüz" değil
        n %= 100
    if n >= 10:
        words.append(_TENS[n // 10])
        n %= 10
    if n:
        words.append(_ONES[n])
    return " ".join(words)


def number_to_words(n: int) -> str:
    """Tam sayıyı Türkçe okunuşa çevirir: 1250000 -> 'bir milyon iki yüz elli bin'."""
    if n < 0:
        return "eksi " + number_to_words(-n)
    if n == 0:
        return "sıfır"
    if n > MAX_NUMBER:
        raise ValueError("sayı çok büyük")
    parts = []
    for size, name in _SCALES:
        if n >= size:
            parts.append(_below_thousand(n // size) + " " + name)
            n %= size
    if n >= 1000:
        t = n // 1000
        parts.append(("" if t == 1 else _below_thousand(t) + " ") + "bin")  # 1000 = "bin", "bir bin" değil
        n %= 1000
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


def _digits(s: str) -> str:
    return " ".join(_DIGIT[int(c)] for c in s if c.isdigit())


def _int_words(s: str) -> str:
    """'1.250.000' / '007' / '42' -> okunuş. Baştaki sıfırlı ya da noktasız 7+ haneli diziler (ilan no gibi)
    rakam rakam okunur."""
    raw = s.replace(".", "")
    if (len(raw) > 1 and raw.startswith("0")) or (len(raw) >= 7 and "." not in s):
        return _digits(raw)
    value = int(raw)
    return number_to_words(value) if value <= MAX_NUMBER else _digits(raw)


def _phone_group(group: str) -> str:
    """Telefon grubu: '532' -> 'beş yüz otuz iki', '45' -> 'kırk beş', '05' -> 'sıfır beş' (baştaki sıfır korunur)."""
    zeros = len(group) - len(group.lstrip("0"))
    rest = group.lstrip("0")
    lead = " ".join(["sıfır"] * zeros)
    return " ".join(x for x in (lead, number_to_words(int(rest)) if rest else "") if x)


def _frac_words(frac: str) -> str:
    # ,5 -> "beş"; ,25 -> "yirmi beş"; ,05 -> "sıfır beş"; 4+ hane rakam rakam
    return _digits(frac) if frac.startswith("0") or len(frac) > 3 else number_to_words(int(frac))


def _decimal_words(whole: str, frac: str | None) -> str:
    return f"{_int_words(whole)} virgül {_frac_words(frac)}" if frac else _int_words(whole)


# ---- kalıplar ---------------------------------------------------------------------------------------------

_NUM = r"\d{1,3}(?:\.\d{3})+|\d+"
_TR = "A-Za-zÇĞİÖŞÜçğıöşü"
_SUF = rf"(?:['’](?P<{{n}}_suf>[{_TR}]+))?"  # 2026'da, 5'te: ek yazıldığı gibi okunur, kesme düşer


def _suf(name: str) -> str:
    return _SUF.replace("{n}", name)


_RULES: list[tuple[str, str]] = [
    ("date", r"(?<![\d.,/])(?P<date_d>\d{1,2})[./](?P<date_m>\d{1,2})[./](?P<date_y>\d{4})(?!\d)" + _suf("date")),
    ("isodate", r"(?<![\d.,/-])(?P<isodate_y>\d{4})-(?P<isodate_m>\d{2})-(?P<isodate_d>\d{2})(?!\d)" + _suf("isodate")),
    ("timedot", r"(?<=[Ss]aat\s)(?P<timedot_h>[01]?\d|2[0-3])\.(?P<timedot_m>[0-5]\d)(?!\d)" + _suf("timedot")),
    ("time", r"(?<![\d:])(?P<time_h>[01]?\d|2[0-3]):(?P<time_m>[0-5]\d)(?![\d:])" + _suf("time")),
    ("phone", r"(?<![\d+])\(?(?P<phone_pre>\+90[\s.-]?|0)?\(?(?P<phone_a>[2-5]\d{2})\)?[\s.-]?(?P<phone_b>\d{3})"
              r"[\s.-]?(?P<phone_c>\d{2})[\s.-]?(?P<phone_d>\d{2})(?!\d)" + _suf("phone")),
    ("money", rf"(?<![\d.,])(?P<money_n>{_NUM})(?:,(?P<money_f>\d{{1,2}}))?(?:\s(?P<money_s>milyon|milyar|bin))?\s?"
              rf"(?P<money_c>TL|₺|TRY|USD|\$|EUR|€|GBP|£)(?![{_TR}])" + _suf("money")),
    ("moneyp", rf"(?<!\w)(?P<moneyp_c>₺|\$|€|£)\s?(?P<moneyp_n>{_NUM})(?:,(?P<moneyp_f>\d{{1,2}}))?(?!\d)"
               + _suf("moneyp")),
    ("pct", rf"(?<![\d.,])%\s?(?P<pct_n>{_NUM})(?:,(?P<pct_f>\d+))?(?!\d)" + _suf("pct")),
    ("pctp", rf"(?<![\d.,])(?P<pctp_n>{_NUM})(?:,(?P<pctp_f>\d+))?\s?%(?!\d)" + _suf("pctp")),
    ("rooms", r"(?<![\d.,])(?P<rooms_a>\d{1,2})\+(?P<rooms_b>\d{1,2})(?!\d)"),
    ("area", rf"(?<![\d.,])(?P<area_n>{_NUM})(?:,(?P<area_f>\d+))?\s?(?P<area_u>m²|m2|km²|km2|km|kg|cm|mm)(?![\w])"
             + _suf("area")),
    ("ord", rf"(?<![\w.,/-])(?P<ord_n>\d{{1,3}})\.(?=\s+[a-zçğıöşü])"),
    ("num", rf"(?<![\w.,/-])(?P<num_neg>-)?(?P<num_n>{_NUM})(?:,(?P<num_f>\d+))?(?![\d]){_SUF.replace('{n}', 'num')}(?![{_TR}\d])"),
]
_RE = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in _RULES), re.UNICODE)


def _join(text: str, suffix: str | None) -> str:
    return text + suffix if suffix else text


def _harmonize(suffix: str | None, word: str) -> str | None:
    """Kısaltmaya yazılmış eki ("TL'ye") okunan sözcüğe ("lira") uydurur: ünlü uyumu ve d/t.
    Yalnızca para ve alan birimleri için; genel ek üretimi scn-008'dedir."""
    if not suffix:
        return suffix
    vowels = "aeıioöuü"
    last = next((c for c in reversed(word) if c in vowels), "a")
    back, rounded = last in "aıou", last in "ouöü"
    out = []
    for i, c in enumerate(suffix):
        if c in "ea":
            out.append("a" if back else "e")
        elif c in "iıuü":
            out.append(("u" if rounded else "ı") if back else ("ü" if rounded else "i"))
        elif i == 0 and c in "dt":
            out.append("t" if word[-1] in "çfhkpsşt" else "d")  # sert ünsüzden sonra t (kuruşta, sentte)
        else:
            out.append(c)
    return "".join(out)


def _convert(m: re.Match) -> str:
    text, g = m.group(0), m.groupdict()
    kind = next(name for name, _ in _RULES if g.get(name) is not None)  # eşleşen üst düzey kural
    try:
        if kind == "date":
            d, mo, y = int(g["date_d"]), int(g["date_m"]), int(g["date_y"])
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                return text
            return _join(f"{number_to_words(d)} {_MONTHS[mo]} {number_to_words(y)}", g["date_suf"])
        if kind == "isodate":
            y, mo, d = int(g["isodate_y"]), int(g["isodate_m"]), int(g["isodate_d"])
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                return text
            return _join(f"{number_to_words(d)} {_MONTHS[mo]} {number_to_words(y)}", g["isodate_suf"])
        if kind in ("time", "timedot"):
            h, mi = int(g[f"{kind}_h"]), int(g[f"{kind}_m"])
            mins = "" if mi == 0 else (" sıfır " if mi < 10 else " ") + number_to_words(mi)
            return _join(number_to_words(h) + mins, g[f"{kind}_suf"])
        if kind == "ord":
            words = number_to_words(int(g["ord_n"])).split(" ")
            words[-1] = _ORD_LAST.get(words[-1], words[-1])
            return " ".join(words)
        if kind == "phone":
            # Türkçede numara gruplar halinde okunur (rakam rakam okuma EMA'da yapay duyuldu; geri bildirim 2026-10-24)
            pre = g["phone_pre"] or ""
            head = "artı doksan, " if pre.startswith("+") else ("sıfır " if pre else "")
            body = ", ".join(_phone_group(g[k]) for k in ("phone_a", "phone_b", "phone_c", "phone_d"))
            return _join(head + body, g["phone_suf"])
        if kind in ("money", "moneyp"):
            cur, whole, frac = g[f"{kind}_c"], g[f"{kind}_n"], g[f"{kind}_f"]
            main, minor = _CURRENCY[cur]
            scale = g.get("money_s") if kind == "money" else None
            if scale:  # "1,5 milyon TL" -> "bir virgül beş milyon lira": kesir ölçeğe bağlı, kuruş değil
                return _join(f"{_decimal_words(whole, frac)} {scale} {main}", _harmonize(g["money_suf"], main))
            out = f"{_int_words(whole)} {main}"
            if frac and int(frac.ljust(2, "0")):
                out += f" {number_to_words(int(frac.ljust(2, '0')))} {minor}"
            minor_used = " " + minor in out
            return _join(out, _harmonize(g[f"{kind}_suf"], minor if minor_used else main))
        if kind in ("pct", "pctp"):
            return _join("yüzde " + _decimal_words(g[f"{kind}_n"], g[f"{kind}_f"]), g[f"{kind}_suf"])
        if kind == "rooms":
            return f"{number_to_words(int(g['rooms_a']))} artı {number_to_words(int(g['rooms_b']))}"
        if kind == "area":
            body = _decimal_words(g["area_n"], g["area_f"])
            unit = _AREA_WORD[g["area_u"]]
            return _join(f"{body} {unit}", _harmonize(g["area_suf"], unit))
        if kind == "num":
            body = _decimal_words(g["num_n"], g["num_f"])
            return _join(("eksi " if g["num_neg"] else "") + body, g["num_suf"])
    except (ValueError, KeyError):
        return text
    return text


# Telaffuz sözlüğü: alan adı biçimindeki markalar TTS'e ham gidince (EMA) harf harf okunuyordu
# ("sahibinden.com adına arıyorum", geri bildirim 2026-10-26). "com" -> "kom", nokta sözcükle yazılır;
# metindeki ek ("com'un") apostrofsuz birleşir ("komun"; "com" son ünlüsü o: un/a/da/dan/u/la uyumu aynı kalır).
_BRAND_RE = re.compile(r"\bsahibinden\.com(?:['\u2019](\w+))?", re.IGNORECASE)


def _brand(m: re.Match) -> str:
    return "sahibinden nokta kom" + (m.group(1) or "")


def normalize(text: str) -> str:
    """Metindeki sayı, tarih, saat, telefon, para, yüzde ve oda/alan ifadelerini okunur Türkçeye çevirir."""
    text = _BRAND_RE.sub(_brand, text)
    return re.sub(r"[ \t]{2,}", " ", _RE.sub(_convert, text)).strip()


def changes(text: str) -> list[dict]:
    """Önizleme için: hangi parça neye çevrildi."""
    out = []
    for m in _RE.finditer(text):
        spoken = _convert(m)
        if spoken != m.group(0):
            out.append({"from": m.group(0), "to": spoken})
    return out
