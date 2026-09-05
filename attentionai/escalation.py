"""Burst / repetition detection.

The strongest real-world urgency signal is not vocabulary, it is *retrying*. People
in genuine trouble send three messages in ninety seconds, or call twice and then
text. That pattern needs no language model and survives any phrasing -- including
"are you awake", which no keyword list would ever rank highly on its own.

State is in-memory and bounded. Nothing here is persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "EscalationConfig",
    "EscalationSignal",
    "EscalationTracker",
]

MINUTE_MS = 60_000


@dataclass
class EscalationConfig:
    window_ms: int = 10 * MINUTE_MS
    message_weight: float = 1.0
    call_weight: float = 3.0
    mention_weight: float = 1.5
    # Weighted units above the first that correspond to escalation == 1.0.
    saturation: float = 4.0
    # Repeated calls from anyone -- known or not -- open the emergency override.
    override_call_count: int = 3
    max_events_per_sender: int = 32
    max_senders: int = 512


@dataclass
class EscalationSignal:
    score: float = 0.0
    burst_count: int = 0
    call_count: int = 0
    override_factor: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "score": self.score,
            "burst_count": float(self.burst_count),
            "call_count": float(self.call_count),
            "override_factor": self.override_factor,
        }


@dataclass
class _Event:
    at_ms: int
    weight: float
    is_call: bool


class EscalationTracker:
    """Sliding-window counter of recent traffic per sender."""

    def __init__(self, config: Optional[EscalationConfig] = None) -> None:
        self.config = config or EscalationConfig()
        self._events: Dict[str, List[_Event]] = {}

    def record(
        self,
        sender_key: str,
        at_ms: int,
        is_call: bool = False,
        mentions_user: bool = False,
    ) -> EscalationSignal:
        """Record one inbound event and return the resulting escalation signal."""
        config = self.config
        weight = config.call_weight if is_call else config.message_weight
        if mentions_user and not is_call:
            weight = max(weight, config.mention_weight)

        events = self._events.setdefault(sender_key, [])
        events.append(_Event(at_ms=at_ms, weight=weight, is_call=is_call))
        self._prune(sender_key, at_ms)
        self._evict_stale_senders(at_ms)

        events = self._events.get(sender_key, [])
        total_weight = sum(event.weight for event in events)
        call_count = sum(1 for event in events if event.is_call)

        # The first message is never escalation; only what follows it is.
        excess = max(0.0, total_weight - config.message_weight)
        score = min(1.0, excess / config.saturation) if config.saturation > 0 else 0.0

        override_factor = 0.0
        if config.override_call_count > 0 and call_count >= config.override_call_count:
            extra = call_count - config.override_call_count
            override_factor = min(1.0, 0.6 + 0.2 * extra)

        return EscalationSignal(
            score=score,
            burst_count=len(events),
            call_count=call_count,
            override_factor=override_factor,
        )

    def peek(self, sender_key: str, at_ms: int) -> EscalationSignal:
        """Read the current signal without recording a new event."""
        self._prune(sender_key, at_ms)
        events = self._events.get(sender_key, [])
        if not events:
            return EscalationSignal()
        total_weight = sum(event.weight for event in events)
        call_count = sum(1 for event in events if event.is_call)
        excess = max(0.0, total_weight - self.config.message_weight)
        saturation = self.config.saturation
        return EscalationSignal(
            score=min(1.0, excess / saturation) if saturation > 0 else 0.0,
            burst_count=len(events),
            call_count=call_count,
        )

    def reset(self, sender_key: Optional[str] = None) -> None:
        if sender_key is None:
            self._events.clear()
        else:
            self._events.pop(sender_key, None)

    # ---- internals -----------------------------------------------------------

    def _prune(self, sender_key: str, at_ms: int) -> None:
        events = self._events.get(sender_key)
        if not events:
            return
        cutoff = at_ms - self.config.window_ms
        kept = [event for event in events if event.at_ms > cutoff]
        if len(kept) > self.config.max_events_per_sender:
            kept = kept[-self.config.max_events_per_sender:]
        if kept:
            self._events[sender_key] = kept
        else:
            self._events.pop(sender_key, None)

    def _evict_stale_senders(self, at_ms: int) -> None:
        if len(self._events) <= self.config.max_senders:
            return
        cutoff = at_ms - self.config.window_ms
        for key in list(self._events.keys()):
            events = self._events[key]
            if not events or events[-1].at_ms <= cutoff:
                self._events.pop(key, None)
