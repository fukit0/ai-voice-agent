"""Sessiz hat bekçisi (core-022): ajan sorduktan sonra müşteriden ses gelmezse soru tekrar edilir, ikincide kibarca kapatılır.

Zaman yerine 20 ms'lik çerçeve sayılır (gerçek zamanlı akışta eşdeğer, testte deterministik). Müşteri konuşurken ya da ajan
konuşurken/düşünürken sayaç sıfırlanır. Kısa bir ses denemesi olduysa (VAD'in attığı kısa parça) bekleme kısalır:
müşteri cevap vermeye çalışmış ama duyulmamıştır, 17 sn ölü hat bırakmak yerine 'duyamadım' denir.
"""
from __future__ import annotations

SILENCE_S = 6.0
SILENCE_AFTER_SHORT_DROP_S = 3.0
FRAME_S = 0.02


class SilenceGuard:
    def __init__(self, silence_s: float = SILENCE_S, after_drop_s: float = SILENCE_AFTER_SHORT_DROP_S):
        self.limit = int(silence_s / FRAME_S)
        self.limit_after_drop = int(after_drop_s / FRAME_S)
        self.quiet = 0
        self.short_drop = False

    def note_drop(self) -> None:
        self.short_drop = True

    def reset(self) -> None:
        self.quiet = 0
        self.short_drop = False

    def tick(self, listening: bool, collecting: bool) -> bool:
        """Her çerçevede çağrılır. True: bekleme doldu, sessizlik cevabı verilmeli."""
        if not listening or collecting:
            self.quiet = 0
            return False
        self.quiet += 1
        if self.quiet >= (self.limit_after_drop if self.short_drop else self.limit):
            self.reset()
            return True
        return False
