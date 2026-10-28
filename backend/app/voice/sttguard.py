"""STT geçidi (canlı test bulguları, 2026-10-28): konuşma tanımanın ürettiği ama cevap olamayacak metinleri süzer.

Gözlenen: Whisper'ın yabancı yazı (Çince/Kiril/İbranice/İspanyolca işaretli) ve altyazı halüsinasyonları, kod karışımında
bozuk çıktı ("vermenção"), Deepgram'ın boğaz temizlemeyi düşük güvenle "merhaba, teşekkür" diye yazması. Geçemeyen metin
"anlaşılmadı" sayılır ve akış soruyu tekrar sorar; metin cevap olarak kaydedilmez. Heuristiktir: eşikler gerçek ses setiyle
ölçülerek ayarlanmalı (core-020).
"""
from __future__ import annotations

import re

# Türkçe alfabe + rakam + temel noktalama dışındaki her harf (Çince, Kiril, İbranice, ã, ç dışı aksanlar...) şüphelidir.
_FOREIGN = re.compile(r"[^\sA-Za-zÇĞİÖŞÜçğıöşüÂÎÛâîû0-9.,;:!?'\"()\-–%/]")
HALLUCINATIONS = ("altyazı", "izlediğiniz için", "abone ol")
MIN_CONFIDENCE = 0.5          # Deepgram alt.confidence; düşükse (öksürük, nefes) metin güvenilmez
MIN_AVG_LOGPROB = -1.0        # Whisper segment ortalama log olasılığı
MAX_COMPRESSION = 2.4         # Whisper sıkıştırma oranı; yüksekse tekrar/halüsinasyon


def check(text: str, extra: dict | None = None) -> tuple[bool, str | None]:
    """(geçti mi, red nedeni)."""
    t = (text or "").strip()
    if not t:
        return False, "empty"
    if _FOREIGN.search(t):
        return False, "foreign_script"
    low = t.replace("İ", "i").replace("I", "ı").casefold()      # Türkçe büyük İ/I'nın casefold farkı
    if any(h in low for h in HALLUCINATIONS):
        return False, "hallucination_phrase"
    extra = extra or {}
    conf = extra.get("confidence")
    if isinstance(conf, (int, float)) and conf < MIN_CONFIDENCE:
        return False, "low_confidence"
    lp, cr = extra.get("avg_logprob"), extra.get("compression_ratio")
    if isinstance(lp, (int, float)) and lp < MIN_AVG_LOGPROB:
        return False, "low_logprob"
    if isinstance(cr, (int, float)) and cr > MAX_COMPRESSION:
        return False, "high_compression"
    return True, None
