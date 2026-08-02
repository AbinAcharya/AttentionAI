from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar, Dict, List, Optional
import re


@dataclass
class UserContext:
    time_of_day: str = "day"
    location_category: str = "office"
    calendar_busy: bool = False
    current_app: str = "unknown"
    screen_on: bool = True
    battery_level: int = 100
    driving: bool = False
    headphones_connected: bool = False
    activity: str = "stationary"

    def is_quiet_time(self) -> bool:
        return (
            self.time_of_day in {"sleep", "night"}
            or self.location_category == "meeting"
            or self.driving
            or not self.screen_on
        )

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]] = None) -> UserContext:
        payload = payload or {}
        return cls(
            time_of_day=str(payload.get("time_of_day", "day")),
            location_category=str(payload.get("location_category", "office")),
            calendar_busy=bool(payload.get("calendar_busy", False)),
            current_app=str(payload.get("current_app", "unknown")),
            screen_on=bool(payload.get("screen_on", True)),
            battery_level=int(payload.get("battery_level", 100)),
            driving=bool(payload.get("driving", False)),
            headphones_connected=bool(payload.get("headphones_connected", False)),
            activity=str(payload.get("activity", "stationary")),
        )


@dataclass
class InteractionProfile:
    sender_id: str
    tier: int = 3
    relationship_score: float = 0.5
    avg_response_time_seconds: float = 120.0
    open_rate: float = 0.5
    urgency_history: List[float] = field(default_factory=list)
    last_interaction_days: int = 365
    manual_overrides: int = 0

    @property
    def average_urgency(self) -> float:
        if not self.urgency_history:
            return 0.0
        return sum(self.urgency_history) / len(self.urgency_history)

    def record_interaction(
        self,
        urgency: float,
        responded: bool,
        override: bool = False,
        response_time_seconds: Optional[float] = None,
        days_since_last_interaction: int = 1,
    ) -> None:
        normalized_urgency = max(0.0, min(1.0, urgency))
        self.urgency_history.append(normalized_urgency)

        if responded:
            self.relationship_score = min(1.0, self.relationship_score + normalized_urgency * 0.05)
            self.open_rate = min(1.0, self.open_rate + 0.02)
            self.last_interaction_days = 0
            if response_time_seconds is not None and response_time_seconds >= 0:
                self.avg_response_time_seconds = (
                    (self.avg_response_time_seconds + response_time_seconds) / 2
                )
        else:
            self.relationship_score = max(0.0, self.relationship_score - 0.02)
            self.open_rate = max(0.0, self.open_rate - 0.01)
            self.last_interaction_days += max(1, days_since_last_interaction)

        if override:
            self.manual_overrides += 1

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> InteractionProfile:
        return cls(
            sender_id=str(raw.get("sender_id", "")),
            tier=int(raw.get("tier", 3)),
            relationship_score=float(raw.get("relationship_score", 0.5)),
            avg_response_time_seconds=float(raw.get("avg_response_time_seconds", 120.0)),
            open_rate=float(raw.get("open_rate", 0.5)),
            urgency_history=list(raw.get("urgency_history", [])),
            last_interaction_days=int(raw.get("last_interaction_days", 365)),
            manual_overrides=int(raw.get("manual_overrides", 0)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NotificationEvent:
    app_name: str
    sender_id: str
    sender_name: Optional[str] = None
    content: str = ""
    timestamp: Optional[str] = None
    context: Optional[UserContext] = None

    urgency_keywords: ClassVar[Dict[str, float]] = {
        "urgent": 0.8,
        "emergency": 1.0,
        "help": 0.9,
        "call me": 0.9,
        "please": 0.2,
        "asap": 0.8,
        "now": 0.6,
    }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> NotificationEvent:
        app_name = payload.get("app_name")
        sender_id = payload.get("sender_id")

        if not app_name or not isinstance(app_name, str):
            raise ValueError("NotificationEvent payload must include a non-empty app_name")
        if not sender_id or not isinstance(sender_id, str):
            raise ValueError("NotificationEvent payload must include a non-empty sender_id")

        return cls(
            app_name=app_name,
            sender_id=sender_id,
            sender_name=payload.get("sender_name"),
            content=str(payload.get("content", "")),
            timestamp=payload.get("timestamp"),
            context=UserContext.from_dict(payload.get("context")),
        )

    def estimate_urgency(self, keywords: Optional[Dict[str, float]] = None) -> float:
        lowered = (self.content or "").lower()
        urgency_keywords = keywords if keywords is not None else self.urgency_keywords
        score = 0.0
        for keyword, weight in urgency_keywords.items():
            if keyword in lowered:
                score = max(score, weight)

        if re.search(r"\b(call|call me|urgent|emergency|help|asap|now)\b", lowered):
            score = max(score, 0.7)

        return max(0.2, min(1.0, score))

    @property
    def is_urgent(self) -> bool:
        return self.estimate_urgency() >= 0.7

    def summary(self) -> str:
        sender = self.sender_name or self.sender_id
        snippet = (self.content or "")[:120]
        return f"{self.app_name} notification from {sender}: {snippet}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "app_name": self.app_name,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "content": self.content,
            "timestamp": self.timestamp,
            "context": asdict(self.context) if self.context is not None else None,
        }


@dataclass
class Decision:
    action: str
    priority_score: float
    reasons: List[str] = field(default_factory=list)

    def is_interrupt(self) -> bool:
        return self.action == "interrupt"

    def is_show_silently(self) -> bool:
        return self.action == "show_silently"

    def is_defer(self) -> bool:
        return self.action == "defer"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
