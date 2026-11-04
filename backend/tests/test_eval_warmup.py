"""Eval betiğinin Qwen ısıtması (2026-11-04: /api/ps 'yüklü' dese de ilk 28 tur timeout aldı)."""
import runpy

import pytest

from backend.app import scenario as S

mod = runpy.run_path(str(S.ROOT / "scripts" / "eval_free_reply.py"), run_name="eval_free_reply_mod")
warm_up = mod["warm_up_ollama"]


class Clock:
    def __init__(self, steps):
        self.steps, self.t = list(steps), 0.0

    def __call__(self):
        return self.t

    def advance(self):
        self.t += self.steps.pop(0) if self.steps else 0.5


class Fake:
    def __init__(self, durations):
        self.durations, self.clock, self.calls = list(durations), Clock([]), []

    def chat(self, messages, timeout_s, max_tokens, temperature):
        self.calls.append((messages, timeout_s, max_tokens))
        self.clock.t += self.durations.pop(0)


def run(durations, timeout_s=2.0, rounds=4):
    f = Fake(durations)
    out = warm_up(f, "SYS", timeout_s, rounds=rounds, say=lambda *_: None, clock=f.clock)
    return f, out


def test_cold_model_reports_first_call_duration_and_stops_when_fast():
    f, out = run([55.0, 0.9])
    assert out == 55.0 and len(f.calls) == 2


def test_already_warm_model_returns_none_after_one_call():
    f, out = run([0.8])
    assert out is None and len(f.calls) == 1


def test_uses_real_system_prompt_and_long_timeout():
    f, _ = run([0.5])
    msgs, timeout, max_tokens = f.calls[0]
    assert msgs[0] == {"role": "system", "content": "SYS"} and timeout >= 120 and max_tokens == 8


def test_never_getting_fast_raises():
    with pytest.raises(RuntimeError):
        run([40.0, 35.0, 30.0, 20.0])
