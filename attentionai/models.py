"""Core data model.

Key changes from the first version:

* ``last_seen_ms`` is real wall-clock time. The old ``last_interaction_days`` counter
  only advanced when a message went unanswered, so genuine dormancy -- the exact
  thing this project cares about -- was literally unmeasurable.
* ``peak_relationship`` and ``lifetime_interactions`` never decay. They are what lets
  the policy tell "an old friend resurfacing" apart from "a stranger", long after the
  decaying ``relationship_score`` has forgotten the difference.
* ``from_dict`` ignores ``None`` values instead of feeding them to ``int()``.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "MS_PER_DAY",
    "UserContext",
    "InteractionProfile",
    "NotificationEvent",
    "INTERRUPT",
    "SHOW_SILENTLY",
    "DEFER",
    "Decision",
    "now_ms",
    "clamp01",
]

MS_PER_DAY = 86_400_000


def now_ms() -> int:
    """Current wall-clock time in milliseconds."""
    return int(time.time() * 1000)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _coerce(payload: Dict[str, Any], key: str, caster, default):
    """Read ``key`` from ``payload``, falling back to ``default`` on missing/None/bad."""
    value = payload.get(key)
    if value is None:
        return default
    try:
        return caster(value)
    except (TypeError, ValueError):
        return default


@dataclass
class UserContext:
    """Everything about the user's situation, independent of who is messaging."""

    time_of_day: str = "day"           # day | evening | night | sleep
    location_category: str = "unknown"  # home | office | meeting | transit | unknown
    calendar_busy: bool = False
    current_app: str = "unknown"
    screen_on: bool = True
    battery_level: int = 100
    driving: bool = False
    headphones_connected: bool = False
    activity: str = "stationary"
    dnd_active: bool = False

    def is_quiet_time(self) -> bool:
        return (
            self.dnd_active
            or self.time_of_day in {"sleep", "night"}
            or self.location_category == "meeting"
            or self.driving
        )

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]] = None) -> "UserContext":
        payload = payload or {}
        return cls(
            time_of_day=_coerce(payload, "time_of_day", str, "day"),
            location_category=_coerce(payload, "location_category", str, "unknown"),
            calendar_busy=_coerce(payload, "calendar_busy", bool, False),
            current_app=_coerce(payload, "current_app", str, "unknown"),
            screen_on=_coerce(payload, "screen_on", bool, True),
            battery_level=_coerce(payload, "battery_level", int, 100),
            driving=_coerce(payload, "driving", bool, False),
            headphones_connected=_coerce(payload, "headphones_connected", bool, False),
            activity=_coerce(payload, "activity", str, "stationary"),
            dnd_active=_coerce(payload, "dnd_active", bool, False),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InteractionProfile:
    """What we have learned about one sender.

    ``relationship_score`` decays with silence; ``peak_relationship`` does not. That
    asymmetry is the whole mechanism behind the reunion case.
    """

    sender_key: str
    tier: int = 3                          # 1 = closest, 5 = furthest
    manual_tier: Optional[int] = None      # explicit user override, wins over `tier`
    relationship_score: float = 0.35
    peak_relationship: float = 0.35
    lifetime_interactions: int = 0
    response_count: int = 0
    received_count: int = 0
    avg_response_seconds: float = 300.0
    last_seen_ms: int = 0                  # last inbound message; 0 = never
    last_outbound_ms: int = 0              # last time *we* messaged them
    last_response_ms: int = 0              # last time we actually engaged
    muted: bool = False
    is_contact: bool = False
    is_starred: bool = False
    manual_overrides: int = 0

    def __post_init__(self) -> None:
        self.tier = max(1, min(5, int(self.tier)))
        if self.manual_tier is not None:
            self.manual_tier = max(1, min(5, int(self.manual_tier)))
        self.relationship_score = clamp01(self.relationship_score)
        self.peak_relationship = clamp01(self.peak_relationship)
        self.lifetime_interactions = max(0, int(self.lifetime_interactions))
        self.response_count = max(0, int(self.response_count))
        self.received_count = max(0, int(self.received_count))
        self.avg_response_seconds = max(0.0, float(self.avg_response_seconds))

    def __repr__(self) -> str:
        return (
            f"InteractionProfile(key={self.sender_key!r}, tier={self.effective_tier}, "
            f"rel={self.relationship_score:.2f}, peak={self.peak_relationship:.2f}, "
            f"interactions={self.lifetime_interactions})"
        )

    # ---- derived -------------------------------------------------------------

    @property
    def effective_tier(self) -> int:
        return self.manual_tier if self.manual_tier is not None else self.tier

    @property
    def open_rate(self) -> float:
        """Laplace-smoothed, so a brand-new sender sits at 0.5 rather than 0 or 1."""
        return (self.response_count + 1.0) / (self.received_count + 2.0)

    def days_since_last_seen(self, at_ms: Optional[int] = None) -> float:
        if self.last_seen_ms <= 0:
            return 0.0
        at_ms = at_ms if at_ms is not None else now_ms()
        return max(0.0, (at_ms - self.last_seen_ms) / MS_PER_DAY)

    def decayed_relationship(
        self,
        at_ms: Optional[int] = None,
        half_life_days: float = 90.0,
        floor: float = 0.15,
    ) -> float:
        """Relationship strength as of ``at_ms``, decayed toward ``floor``."""
        if self.last_seen_ms <= 0:
            return self.relationship_score
        days = self.days_since_last_seen(at_ms)
        if days <= 0 or half_life_days <= 0:
            return self.relationship_score
        decay: float = 0.5 ** (days / half_life_days)
        return floor + (self.relationship_score - floor) * decay

    def is_established(self, peak_threshold: float, min_interactions: int) -> bool:
        """Did this person ever actually matter to the user?"""
        return (
            self.peak_relationship >= peak_threshold
            or self.lifetime_interactions >= min_interactions
            or self.is_starred
            or (self.manual_tier is not None and self.manual_tier <= 2)
        )

    # ---- learning ------------------------------------------------------------
    #
    # These are driven by observed user behaviour only. Nothing here is ever called
    # with the engine's own decision as the label -- doing that in the first version
    # created a loop where "I chose to interrupt" was recorded as "the user cared".

    def record_delivery(self, at_ms: int) -> None:
        """A notification from this sender arrived. Not a signal of interest yet."""
        self.received_count += 1
        self.last_seen_ms = at_ms

    def record_response(self, at_ms: int, response_seconds: Optional[float] = None) -> None:
        """The user opened or replied. This is the real positive label."""
        self.response_count += 1
        self.lifetime_interactions += 1
        self.last_response_ms = at_ms
        self.relationship_score = clamp01(self.relationship_score + 0.06)
        self.peak_relationship = max(self.peak_relationship, self.relationship_score)
        if response_seconds is not None and response_seconds >= 0:
            # Exponential moving average, weighted toward history.
            self.avg_response_seconds = (
                0.7 * self.avg_response_seconds + 0.3 * float(response_seconds)
            )

    def record_dismissal(self, at_ms: int) -> None:
        """The user swiped it away without engaging. The real negative label."""
        self.relationship_score = max(0.0, self.relationship_score - 0.02)

    def record_outbound(self, at_ms: int) -> None:
        """The user messaged this person first -- strong reciprocity signal."""
        self.last_outbound_ms = at_ms
        self.lifetime_interactions += 1
        self.relationship_score = clamp01(self.relationship_score + 0.04)
        self.peak_relationship = max(self.peak_relationship, self.relationship_score)

    def set_manual_tier(self, tier: int) -> None:
        self.manual_tier = max(1, min(5, int(tier)))
        self.manual_overrides += 1
        if self.manual_tier <= 2:
            self.peak_relationship = max(self.peak_relationship, 0.8)

    # ---- serialisation -------------------------------------------------------

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "InteractionProfile":
        raw = raw or {}
        return cls(
            sender_key=str(raw.get("sender_key") or raw.get("sender_id") or ""),
            tier=_coerce(raw, "tier", int, 3),
            manual_tier=_coerce(raw, "manual_tier", int, None),
            relationship_score=_coerce(raw, "relationship_score", float, 0.35),
            peak_relationship=_coerce(raw, "peak_relationship", float, 0.35),
            lifetime_interactions=_coerce(raw, "lifetime_interactions", int, 0),
            response_count=_coerce(raw, "response_count", int, 0),
            received_count=_coerce(raw, "received_count", int, 0),
            avg_response_seconds=_coerce(raw, "avg_response_seconds", float, 300.0),
            last_seen_ms=_coerce(raw, "last_seen_ms", int, 0),
            last_outbound_ms=_coerce(raw, "last_outbound_ms", int, 0),
            last_response_ms=_coerce(raw, "last_response_ms", int, 0),
            muted=_coerce(raw, "muted", bool, False),
            is_contact=_coerce(raw, "is_contact", bool, False),
            is_starred=_coerce(raw, "is_starred", bool, False),
            manual_overrides=_coerce(raw, "manual_overrides", int, 0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NotificationEvent:
    """One inbound notification, normalised away from any particular platform."""

    app_name: str
    sender_id: str
    sender_name: Optional[str] = None
    content: str = ""
    timestamp_ms: int = 0
    thread_id: Optional[str] = None
    notification_key: Optional[str] = None
    is_group: bool = False
    mentions_user: bool = False
    is_missed_call: bool = False
    is_ongoing: bool = False           # media / foreground-service noise
    is_group_summary: bool = False
    context: Optional[UserContext] = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "NotificationEvent":
        app_name = payload.get("app_name")
        sender_id = payload.get("sender_id")

        if not app_name or not isinstance(app_name, str):
            raise ValueError("NotificationEvent payload must include a non-empty app_name")
        if not sender_id or not isinstance(sender_id, str):
            raise ValueError("NotificationEvent payload must include a non-empty sender_id")

        raw_context = payload.get("context")
        context = UserContext.from_dict(raw_context if isinstance(raw_context, dict) else None)

        return cls(
            app_name=app_name,
            sender_id=sender_id,
            sender_name=payload.get("sender_name"),
            content=str(payload.get("content") or ""),
            timestamp_ms=_coerce(payload, "timestamp_ms", int, 0),
            thread_id=payload.get("thread_id"),
            notification_key=payload.get("notification_key"),
            is_group=_coerce(payload, "is_group", bool, False),
            mentions_user=_coerce(payload, "mentions_user", bool, False),
            is_missed_call=_coerce(payload, "is_missed_call", bool, False),
            is_ongoing=_coerce(payload, "is_ongoing", bool, False),
            is_group_summary=_coerce(payload, "is_group_summary", bool, False),
            context=context,
        )

    def dedup_key(self) -> str:
        return self.notification_key or self.thread_id or f"{self.app_name}:{self.sender_id}"

    def summary(self) -> str:
        sender = self.sender_name or self.sender_id
        return f"{self.app_name} notification from {sender}"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["context"] = self.context.to_dict() if self.context is not None else None
        return payload


# Decision actions.
INTERRUPT = "interrupt"
SHOW_SILENTLY = "show_silently"
DEFER = "defer"


@dataclass
class Decision:
    """What to do, how strongly, and -- for the UI -- why."""

    action: str
    priority_score: float
    reasons: List[str] = field(default_factory=list)
    components: Dict[str, float] = field(default_factory=dict)
    suppressed_by: Optional[str] = None

    def is_interrupt(self) -> bool:
        return self.action == INTERRUPT

    def is_show_silently(self) -> bool:
        return self.action == SHOW_SILENTLY

    def is_defer(self) -> bool:
        return self.action == DEFER

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __repr__(self) -> str:
        return (
            f"Decision(action={self.action!r}, score={self.priority_score:.3f}, "
            f"reasons={self.reasons})"
        )
