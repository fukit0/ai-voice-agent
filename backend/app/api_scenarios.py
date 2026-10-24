"""Senaryo API'si (lab-003): senaryoları listeler, metin düzenlemeyi ve örnek değerlerle okunuşu önizlemeyi sağlar."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import scenario as S
from .trnorm import normalize

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _sc(key: str) -> dict:
    try:
        return S.get(key)
    except KeyError:
        raise HTTPException(404, {"error": "unknown_scenario", "message": f"Senaryo bulunamadı: {key}"}) from None


def _step(sc: dict, key: str) -> dict:
    st = S.step_map(sc).get(key)
    if st is None:
        raise HTTPException(404, {"error": "unknown_step", "message": f"Adım bulunamadı: {key}"})
    return st


def _view(sc: dict, st: dict, ov: dict[str, str], values: dict[str, str]) -> dict:
    text = ov.get(st["key"], st["defaultText"])
    steps = S.step_map(sc)
    return {
        **{k: st[k] for k in ("key", "title", "code", "group", "kind", "condition", "dtmf", "min", "max", "longAnswer",
                              "outcome", "applicable", "choices", "defaultText")},
        "text": text, "edited": st["key"] in ov, "placeholders": S.placeholders_in(text),
        "branches": [{**b, "to_title": steps[b["to"]]["title"]} for b in st["branches"]],
        "spoken": normalize(S.fill(text, values)),
        "chars": len(text),
    }


@router.get("")
def list_scenarios() -> list[dict]:
    return [{"key": k, "label": s["label"], "shortLabel": s["shortLabel"], "description": s["description"],
             "steps": len(s["steps"]), "outcomes": s["outcomes"], "problems": S.validate(s)}
            for k, s in S.load_all().items()]


@router.get("/{key}")
def get_scenario(key: str) -> dict:
    sc = _sc(key)
    ov, values = S.load_overrides(key), S.sample_values(sc)
    return {"key": key, "label": sc["label"], "description": sc["description"], "outcomes": sc["outcomes"],
            "placeholders": sc["_placeholders"], "sample_values": values, "problems": S.validate(sc),
            "steps": [_view(sc, st, ov, values) for st in sc["steps"]]}


class TextBody(BaseModel):
    text: str


@router.put("/{key}/steps/{step}/text")
def put_text(key: str, step: str, body: TextBody) -> dict:
    sc = _sc(key)
    st = _step(sc, step)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, {"error": "empty_text", "message": "Metin boş olamaz."})
    bad = S.unknown_placeholders(sc, text)
    if bad:
        raise HTTPException(400, {"error": "unknown_placeholder",
                                  "message": "Bilinmeyen yer tutucu: " + ", ".join("{" + b + "}" for b in bad)})
    S.save_override(key, step, None if text == st["defaultText"] else text)
    return _view(sc, st, S.load_overrides(key), S.sample_values(sc))


@router.delete("/{key}/steps/{step}/text")
def reset_text(key: str, step: str) -> dict:
    sc = _sc(key)
    st = _step(sc, step)
    S.save_override(key, step, None)
    return _view(sc, st, S.load_overrides(key), S.sample_values(sc))


@router.post("/{key}/preview")
def preview(key: str, body: TextBody) -> dict:
    sc = _sc(key)
    return {"spoken": normalize(S.fill(body.text, S.sample_values(sc))), "chars": len(body.text),
            "unknown_placeholders": S.unknown_placeholders(sc, body.text)}
