from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


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


@dataclass
class NotificationEvent:
    app_name: str
    sender_id: str
    sender_name: Optional[str] = None
    content: str = ""
    timestamp: Optional[str] = None
    context: Optional[UserContext] = None


@dataclass
class Decision:
    action: str
    priority_score: float
    reasons: List[str] = field(default_factory=list)
