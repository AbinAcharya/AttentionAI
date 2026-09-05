"""Interrupt budget and de-duplication.

Scoring alone will happily let twenty notifications cross the threshold in one hour,
which defeats the point of Do Not Disturb. This module is the back-pressure: a rolling
cap on breakthroughs, a per-sender cooldown, and suppression of repeats of a
notification the user has already been shown.

A high enough score bypasses both the cooldown and the cap -- a real emergency should
not be rate-limited because two other things got through first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "ALLOWED",
    "REASON_BUDGET",
    "REASON_COOLDOWN",
    "REASON_DUPLICATE",
    "BudgetConfig",
    "BudgetVerdict",
    "InterruptBudget",
]

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS

ALLOWED = "allowed"
REASON_BUDGET = "hourly_budget_exhausted"
REASON_COOLDOWN = "sender_cooldown"
REASON_DUPLICATE = "duplicate_notification"


@dataclass
class BudgetConfig:
    window_ms: int = HOUR_MS
    max_interrupts_per_window: int = 3
    per_sender_cooldown_ms: int = 10 * MINUTE_MS
    duplicate_ttl_ms: int = 5 * MINUTE_MS
    # Scores at or above this ignore the cooldown and the hourly cap.
    bypass_score: float = 0.90
    max_tracked_keys: int = 1024


@dataclass
class BudgetVerdict:
    allowed: bool
    reason: str = ALLOWED
    remaining: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {"allowed": self.allowed, "reason": self.reason, "remaining": self.remaining}


class InterruptBudget:
    """Rolling-window breakthrough limiter."""

    def __init__(self, config: Optional[BudgetConfig] = None) -> None:
        self.config = config or BudgetConfig()
        self._interrupts: List[int] = []
        self._last_by_sender: Dict[str, int] = {}
        self._seen_dedup: Dict[str, int] = {}

    def check(
        self,
        sender_key: str,
        score: float,
        at_ms: int,
        dedup_key: Optional[str] = None,
    ) -> BudgetVerdict:
        """Decide whether an interrupt-scored notification may actually break through."""
        self._prune(at_ms)
        config = self.config

        if dedup_key is not None:
            last_seen = self._seen_dedup.get(dedup_key)
            if last_seen is not None and at_ms - last_seen < config.duplicate_ttl_ms:
                return BudgetVerdict(False, REASON_DUPLICATE, self._remaining())

        if score >= config.bypass_score:
            return BudgetVerdict(True, ALLOWED, self._remaining())

        last_interrupt = self._last_by_sender.get(sender_key)
        if last_interrupt is not None and at_ms - last_interrupt < config.per_sender_cooldown_ms:
            return BudgetVerdict(False, REASON_COOLDOWN, self._remaining())

        if len(self._interrupts) >= config.max_interrupts_per_window:
            return BudgetVerdict(False, REASON_BUDGET, 0)

        return BudgetVerdict(True, ALLOWED, self._remaining())

    def commit(self, sender_key: str, at_ms: int, dedup_key: Optional[str] = None) -> None:
        """Record that a breakthrough actually happened."""
        self._interrupts.append(at_ms)
        self._last_by_sender[sender_key] = at_ms
        if dedup_key is not None:
            self._seen_dedup[dedup_key] = at_ms
        self._prune(at_ms)

    def note_shown(self, dedup_key: Optional[str], at_ms: int) -> None:
        """Record a silent/deferred delivery so repeats of it are still de-duplicated."""
        if dedup_key is not None:
            self._seen_dedup[dedup_key] = at_ms
            self._prune(at_ms)

    def remaining(self, at_ms: int) -> int:
        self._prune(at_ms)
        return self._remaining()

    def reset(self) -> None:
        self._interrupts.clear()
        self._last_by_sender.clear()
        self._seen_dedup.clear()

    # ---- internals -----------------------------------------------------------

    def _remaining(self) -> int:
        return max(0, self.config.max_interrupts_per_window - len(self._interrupts))

    def _prune(self, at_ms: int) -> None:
        config = self.config
        window_cutoff = at_ms - config.window_ms
        self._interrupts = [stamp for stamp in self._interrupts if stamp > window_cutoff]

        cooldown_cutoff = at_ms - config.per_sender_cooldown_ms
        for key in [k for k, v in self._last_by_sender.items() if v <= cooldown_cutoff]:
            self._last_by_sender.pop(key, None)

        dedup_cutoff = at_ms - config.duplicate_ttl_ms
        for key in [k for k, v in self._seen_dedup.items() if v <= dedup_cutoff]:
            self._seen_dedup.pop(key, None)

        if len(self._seen_dedup) > config.max_tracked_keys:
            for key in sorted(self._seen_dedup, key=lambda k: self._seen_dedup.get(k, 0))[
                : len(self._seen_dedup) // 2
            ]:
                self._seen_dedup.pop(key, None)
