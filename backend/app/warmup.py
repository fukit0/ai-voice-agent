"""Profil ön yükleme ("Hazırla") işleri — ADR 0001.

Her bileşen için: sağlayıcıyı oluştur, ısınma çıkarımı yap (yükleme + ilk çağrı maliyeti), ardından
ikinci bir çağrıyla sıcak süreyi ölç. Aynı anda tek ısınma çalışır (bellek ve doğru ölçüm için).
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .profiles import COMPONENTS, Profile
from . import sysinfo
from .providers import ProviderNotReady, evict_except, get_provider, provider_key, record_call

# Son kontrol: tüm bileşenler yüklüyken sıcak çağrı bu sınırı aşarsa model bellekte tutulamıyor demektir
# (ör. 36 GB Mac'te Qwen 18 GB + Chatterbox birlikte: swap / GPU bellek çekişmesi).
DEGRADE_FACTOR = 3.0
DEGRADE_MIN_EXTRA_S = 1.0


@dataclass
class WarmupJob:
    profile: str
    state: str = "running"  # running | ready | degraded | failed
    memory_before: dict[str, Any] | None = None
    memory_after: dict[str, Any] | None = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    finished_at: str | None = None
    seconds: float | None = None
    evicted: list[str] = field(default_factory=list)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_jobs: dict[str, WarmupJob] = {}
_jobs_lock = threading.Lock()
_running = threading.Lock()  # tek seferde tek ısınma


class WarmupBusy(Exception):
    pass


def get_job(profile_id: str) -> WarmupJob | None:
    with _jobs_lock:
        return _jobs.get(profile_id)


def components_of(profile: Profile, only: set[str] | None = None) -> list[tuple[str, dict]]:
    return [(c, profile.component(c)) for c in COMPONENTS if profile.component(c) and (only is None or c in only)]


def start(profile: Profile, keep_others: bool = False, background: bool = True,
          only: set[str] | None = None) -> WarmupJob:
    """`only` verilirse yalnızca o bileşenler hazırlanır (ör. STT test ekranı yalnızca STT modelini ister);
    bu durumda başka hiçbir model bellekten çıkarılmaz."""
    if not _running.acquire(blocking=False):
        raise WarmupBusy("Başka bir profil hazırlanıyor; bitince tekrar deneyin.")
    job = WarmupJob(profile=profile.id,
                    components={c: {"state": "pending"} for c, _ in components_of(profile, only)})
    with _jobs_lock:
        _jobs[profile.id] = job
    if background:
        threading.Thread(target=_run, args=(profile, job, keep_others or only is not None, only), daemon=True,
                         name=f"warmup-{profile.id}").start()
    else:
        _run(profile, job, keep_others or only is not None, only)
    return job


def _run(profile: Profile, job: WarmupJob, keep_others: bool, only: set[str] | None = None) -> None:
    t_all = time.perf_counter()
    final_state, final_error = "failed", None
    try:
        specs = components_of(profile, only)
        job.memory_before = sysinfo.memory()
        if not keep_others:
            job.evicted = evict_except({provider_key(spec) for _, spec in specs})
        for name, spec in specs:
            comp = job.components[name]
            comp.update(state="loading", provider=spec.get("provider"), model=spec.get("model") or "")
            try:
                provider = get_provider(spec, name, profile.id)
            except ProviderNotReady as exc:
                comp.update(state="failed", error=str(exc), missing_env=exc.missing_env)
                continue
            try:
                t0 = time.perf_counter()
                provider.warmup_call()  # yükleme + ilk çıkarım
                comp["load_seconds"] = round(time.perf_counter() - t0, 2)
                comp["state"] = "measuring"
                t1 = time.perf_counter()
                provider.warmup_call()  # sıcak çağrı: production'da beklenen süre
                comp["warm_seconds"] = round(time.perf_counter() - t1, 3)
                provider.mark_warm()
                comp["state"] = "ready"
                record_call(profile.id, name, provider, comp["warm_seconds"], ok=True, warm=True, warmup=True,
                            load_seconds=comp["load_seconds"])
            except Exception as exc:  # noqa: BLE001 — bileşen hatası diğerlerini durdurmasın
                comp.update(state="failed", error=f"{type(exc).__name__}: {exc}"[:400])
                record_call(profile.id, name, provider, time.perf_counter() - t0, ok=False, warmup=True,
                            error=str(exc)[:300])
        failed = [n for n, c in job.components.items() if c.get("state") != "ready"]
        if not failed:
            _final_pass(profile, job, specs)
        degraded = [n for n, c in job.components.items() if c.get("state") == "degraded"]
        if failed:
            causes = "; ".join(f"{n.upper()}: {job.components[n].get('error')}" for n in failed if job.components[n].get("error"))
            final_state, final_error = "failed", "Hazırlanamayan bileşen: " + ", ".join(failed) + (f" — {causes}" if causes else "")
        elif degraded:
            final_state = "degraded"
            final_error = ("Bu bilgisayarda profilin tüm modelleri aynı anda sıcak tutulamıyor; "
                         f"{', '.join(c.upper() for c in degraded)} hepsi yüklüyken yavaşlıyor (bellek çekişmesi).")
        else:
            final_state = "ready"
    except Exception as exc:  # noqa: BLE001
        final_state, final_error = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        try:
            job.memory_after = sysinfo.memory()
        except Exception:  # noqa: BLE001
            pass
        job.seconds = round(time.perf_counter() - t_all, 2)
        job.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        job.error = final_error
        _running.release()
        job.state = final_state  # en son: izleyen taraf 'bitti' gördüğünde yeni hazırlama başlatılabilir


def _final_pass(profile: Profile, job: WarmupJob, specs: list[tuple[str, dict]]) -> None:
    """Hepsi yüklüyken her bileşeni bir kez daha çağır: production'da bileşenler birlikte bellekte durur.

    Tek başına ölçülen sıcak süre, diğer modeller yüklenince bozuluyorsa (swap, GPU çekişmesi) bileşen
    'degraded' işaretlenir ve ölçümlere kapatılır.
    """
    for name, spec in specs:
        comp = job.components[name]
        provider = get_provider(spec, name, profile.id)
        t0 = time.perf_counter()
        provider.warmup_call()
        final = round(time.perf_counter() - t0, 3)
        comp["final_seconds"] = final
        limit = max(comp["warm_seconds"] * DEGRADE_FACTOR, comp["warm_seconds"] + DEGRADE_MIN_EXTRA_S)
        if final > limit:
            comp["state"] = "degraded"
            provider.mark_warm(False)
        record_call(profile.id, name, provider, final, ok=True, warm=comp["state"] == "ready", warmup=True,
                    final_pass=True)
