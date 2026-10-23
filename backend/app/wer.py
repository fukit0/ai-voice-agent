"""Türkçe metinler için WER (word error rate) hesabı.

Karşılaştırmadan önce iki metin de aynı biçime getirilir: Türkçe küçük harf kuralı (İ->i, I->ı),
noktalama ve fazla boşluk atılır. Sayılar ve yazım biçimleri (ör. "3 bin" / "üç bin") çevrilmez;
bu fark WER'e hata olarak yansır ve normalizasyon (norm-007) ile ayrıca ele alınır.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_PUNCT = re.compile(r"[^\w\s]|_", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize_tr(text: str) -> str:
    text = text.replace("İ", "i").replace("I", "ı").lower()
    text = _PUNCT.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def words(text: str) -> list[str]:
    norm = normalize_tr(text)
    return norm.split(" ") if norm else []


@dataclass
class WerResult:
    wer: float | None  # referans boşsa None
    ref_words: int
    substitutions: int
    deletions: int
    insertions: int

    def to_dict(self) -> dict:
        d = asdict(self)
        d["wer"] = None if self.wer is None else round(self.wer, 4)
        return d


def wer(reference: str, hypothesis: str) -> WerResult:
    ref, hyp = words(reference), words(hypothesis)
    n, m = len(ref), len(hyp)
    # dp[i][j] = (maliyet, sub, del, ins) ref[:i] -> hyp[:j]
    prev = [(j, 0, 0, j) for j in range(m + 1)]
    for i in range(1, n + 1):
        cur = [(i, 0, i, 0)]
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                cur.append(prev[j - 1])
                continue
            s, d, ins = prev[j - 1], prev[j], cur[j - 1]
            options = [(s[0] + 1, s[1] + 1, s[2], s[3]), (d[0] + 1, d[1], d[2] + 1, d[3]),
                       (ins[0] + 1, ins[1], ins[2], ins[3] + 1)]
            cur.append(min(options, key=lambda o: o[0]))
        prev = cur
    cost, sub, dele, ins = prev[m]
    return WerResult(wer=(cost / n) if n else None, ref_words=n, substitutions=sub, deletions=dele,
                     insertions=ins)
