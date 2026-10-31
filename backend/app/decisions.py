"""Profil karar kaydı (kıyas sonrası eleme): hangi profil/model neden elendi ya da seçildi, demoda profil bazında anlatılır.

Kayıt data/profile-decisions.json: {profil: {status, reason, decided_at, snapshot}}.
- status: aday (karar yok) | secildi | elendi. elendi/secildi için gerekçe zorunludur (en az MIN_REASON karakter): gerekçesiz eleme olmaz.
- snapshot: karar anındaki kıyas sayıları (toplam, kapsam, kriter puanları). Sonradan yeni ölçüm gelse de kararın dayandığı sayı kaybolmaz.
Lisans nedeniyle otomatik elenen profiller (matrix.py) için ayrıca elle kayıt gerekmez; rapor lisans gerekçesini kendisi yazar.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .profiles import ROOT

STATUSES = ("aday", "secildi", "elendi")
MIN_REASON = 15
LABEL = {"aday": "Aday (karar yok)", "secildi": "Seçildi", "elendi": "Elendi"}


def path() -> Path:
    return Path(os.environ.get("SVA_DATA_DIR", ROOT / "data")) / "profile-decisions.json"


def load() -> dict[str, dict[str, Any]]:
    try:
        d = json.loads(path().read_text(encoding="utf-8"))
        return {k: v for k, v in d.items() if isinstance(v, dict) and v.get("status") in STATUSES}
    except (OSError, ValueError, AttributeError):
        return {}


def _save(d: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def snapshot_of(row: dict | None) -> dict | None:
    if not row:
        return None
    return {"total": row.get("total"), "coverage": row.get("coverage"), "missing": row.get("missing"),
            "scores": {k: (m or {}).get("score") for k, m in (row.get("metrics") or {}).items()},
            "values": {k: {"value": m["value"], "unit": m["unit"], "n": m.get("n")} for k, m in (row.get("metrics") or {}).items() if m}}


def set_decision(pid: str, status: str, reason: str, row: dict | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"bilinmeyen durum: {status}")
    reason = (reason or "").strip()
    if status != "aday" and len(reason) < MIN_REASON:
        raise ValueError(f"{LABEL[status]} için gerekçe yazılmalı (en az {MIN_REASON} karakter): neden bu karar verildi?")
    d = load()
    if status == "aday":
        d.pop(pid, None)
        _save(d)
        return {"status": "aday", "reason": "", "decided_at": None, "snapshot": None}
    rec = {"status": status, "reason": reason, "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "snapshot": snapshot_of(row)}
    d[pid] = rec
    _save(d)
    return rec


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.1f}".replace(".", ",")


def report(matrix: dict) -> str:
    """Demo için profil bazlı karar özeti (Markdown). Eleme gerekçesi yoksa açıkça 'gerekçe yazılmadı' der."""
    recs = load()
    lines = ["# Profil kararları (kıyas sonrası)", "",
             "| Profil | Bileşenler | Karar | Gerekçe | Karar anındaki sayılar |", "|---|---|---|---|---|"]
    for r in matrix["rows"]:
        rec = recs.get(r["profile"])
        comps = " · ".join(f"{c['kind']}: {(c['model'] or c['provider']).split('/')[-1]}" for c in r["components"])
        lic_out = [x for x in r["license"] if x["commercial_ok"] is False]
        if rec:
            status, reason = LABEL[rec["status"]], rec["reason"]
            s = rec.get("snapshot") or {}
            nums = f"toplam {_fmt(s.get('total'))} · kapsam %{round((s.get('coverage') or 0) * 100)}" if s else "—"
        elif lic_out:
            status = "Elendi (lisans)"
            reason = "; ".join(f"{x['kind']} {x['model']}: {x['license']} (ticari kullanım uygun değil)" for x in lic_out)
            nums = "—"
        else:
            status, reason, nums = LABEL["aday"], "—", f"toplam {_fmt(r.get('total'))} · kapsam %{round(r['coverage'] * 100)}"
        lines.append(f"| {r['profile']} · {r['name']} | {comps} | {status} | {reason.replace('|', '/')} | {nums} |")
    lines += ["", "Not: sayılar karar anındaki kıyas matrisidir; kapsam düşükse (eksik kriter) sıralama kesin kanıt değildir."]
    return "\n".join(lines) + "\n"
