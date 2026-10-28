"""core-023 / core-011: gerçek zamanlı profil (A2, A3) oturum raporu — fonksiyon çağrısı oranı, anket tamamlama, giriş transkripti dili.

Girdi data/voice-sessions/*.json. Ölçüm yapmaz, kayıtları özetler; canlı arama gerekir (en az 5).
Fonksiyon çağrısı oranı = müşteri cevap turları içinde modelin report_answer çağırdığı tur oranı (`no_tool_call` turları çağrı yok sayılır).
Dil denetimi: giriş transkriptinde Türkçe olmayan yazı (sttguard yabancı yazı/halüsinasyon) ve Türkçe harf içermeyen İngilizce/İspanyolca
belirteç kelimeleri sayılır (heuristik; dil ayarının sunucuda uygulandığını kanıtlamaz).
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

from . import sttguard

MIN_SESSIONS = 5
_NON_TR_WORDS = {"the", "and", "you", "yes", "hello", "thank", "thanks", "please", "okay", "hola", "gracias", "si", "sí", "por", "favor",
                 "buenos", "dias", "días", "que", "qué", "como", "cómo", "estoy", "bien", "muy", "gracias"}
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def language_flags(text: str) -> list[str]:
    flags = []
    if sttguard._FOREIGN.search(text or ""):
        flags.append("foreign_script")
    words = {w.casefold() for w in _WORD.findall(text or "")}
    if words & _NON_TR_WORDS and not re.search(r"[çğıöşüÇĞİÖŞÜ]", text or ""):
        flags.append("non_turkish_words")
    return flags


def session_row(doc: dict) -> dict:
    turns = [t for t in doc.get("turns", []) if not t.get("greeting")]
    answer_turns = [t for t in turns if t.get("realtime") and ("tool_args" in t or t.get("no_tool_call"))]
    no_call = sum(1 for t in answer_turns if t.get("no_tool_call"))
    user_texts = [x["text"] for x in doc.get("transcript", []) if x.get("role") == "user"]
    flags = Counter(f for t in user_texts for f in language_flags(t))
    flow = doc.get("flow") or {}
    stats = doc.get("stats") or {}
    return {"id": doc.get("id"), "answer_turns": len(answer_turns), "no_tool_call_turns": no_call,
            "tool_calls": stats.get("tool_calls", 0), "invalid_tool_calls": stats.get("invalid_tool_calls", 0),
            "outcome": flow.get("outcome"), "completed": flow.get("outcome") == "tamamlandi",
            "user_utterances": len(user_texts), "language_flags": dict(flags), "errors": len(doc.get("errors") or [])}


def summarize(sessions: list[dict], profile: str) -> dict:
    rows = [session_row(d) for d in sessions if d.get("profile") == profile]
    turns = sum(r["answer_turns"] for r in rows)
    no_call = sum(r["no_tool_call_turns"] for r in rows)
    utt = sum(r["user_utterances"] for r in rows)
    flagged = sum(sum(r["language_flags"].values()) for r in rows)
    return {"profile": profile, "sessions": len(rows), "enough_sessions": len(rows) >= MIN_SESSIONS,
            "answer_turns": turns, "tool_call_rate": round(1 - no_call / turns, 3) if turns else None,
            "invalid_tool_calls": sum(r["invalid_tool_calls"] for r in rows),
            "completion_rate": round(sum(1 for r in rows if r["completed"]) / len(rows), 3) if rows else None,
            "outcomes": dict(Counter(r["outcome"] or "bitmedi" for r in rows)),
            "foreign_or_non_turkish_transcript_rate": round(flagged / utt, 3) if utt else None,
            "sessions_with_errors": sum(1 for r in rows if r["errors"]),
            "median_answer_turns_per_session": statistics.median([r["answer_turns"] for r in rows]) if rows else None,
            "rows": rows}


def render(rep: dict) -> str:
    f = lambda v: "-" if v is None else v  # noqa: E731
    lines = [f"{rep['profile']}: {rep['sessions']} arama (hedef ≥ {MIN_SESSIONS}), {rep['answer_turns']} cevap turu",
             f"  fonksiyon çağrısı oranı: {f(rep['tool_call_rate'])}   geçersiz çağrı: {rep['invalid_tool_calls']}",
             f"  anket tamamlama (tamamlandi): {f(rep['completion_rate'])}   sonuçlar: {rep['outcomes']}",
             f"  yabancı/Türkçe olmayan transkript oranı: {f(rep['foreign_or_non_turkish_transcript_rate'])}",
             f"  hatalı oturum: {rep['sessions_with_errors']}"]
    if not rep["enough_sessions"]:
        lines.append(f"  ! örnek yetersiz ({rep['sessions']}/{MIN_SESSIONS}): karar için kullanılamaz; Playground'da senaryoyla arama yapın")
    return "\n".join(lines)
