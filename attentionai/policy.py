from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import Decision, InteractionProfile, NotificationEvent, UserContext


@dataclass
class NotificationPolicyConfig:
    urgency_keywords: Dict[str, float] = field(default_factory=lambda: {
        "urgent": 0.8,
        "emergency": 1.0,
        "help": 0.9,
        "call me": 0.9,
        "please": 0.2,
        "asap": 0.8,
        "now": 0.6,
    })
    urgency_weight: float = 0.6
    relationship_weight: float = 0.15
    tier_bonus_multiplier: float = 0.08
    open_rate_weight: float = 0.05
    average_urgency_weight: float = 0.05
    context_penalty_multiplier: float = 0.5
    dormancy_bonus: float = 0.15
    dormancy_threshold_days: int = 700
    urgency_boost_threshold: float = 0.8
    urgency_boost_amount: float = 0.15
    interrupt_threshold: float = 0.75
    show_silently_threshold: float = 0.45


class NotificationPolicy:
    def __init__(self, config: Optional[NotificationPolicyConfig] = None) -> None:
        self.config = config or NotificationPolicyConfig()
        self.urgency_keywords = self.config.urgency_keywords

    def analyze(self, event: NotificationEvent, profile: Optional[InteractionProfile] = None) -> Decision:
        urgency_score = event.estimate_urgency(self.urgency_keywords)

        if profile is None:
            profile = InteractionProfile(sender_id=event.sender_id)

        relationship_score = profile.relationship_score
        tier_bonus = self.config.tier_bonus_multiplier * max(0, 5 - profile.tier)
        open_rate_bonus = profile.open_rate * self.config.open_rate_weight
        average_urgency_bonus = profile.average_urgency * self.config.average_urgency_weight
        context_penalty = self._context_penalty(event.context)
        dormancy_bonus = 0.0

        if profile.last_interaction_days > self.config.dormancy_threshold_days:
            dormancy_bonus = self.config.dormancy_bonus

        score = (
            urgency_score * self.config.urgency_weight
            + relationship_score * self.config.relationship_weight
            + tier_bonus
            + open_rate_bonus
            + average_urgency_bonus
            + dormancy_bonus
        )
        score -= context_penalty * self.config.context_penalty_multiplier

        if urgency_score >= self.config.urgency_boost_threshold:
            score += self.config.urgency_boost_amount

        score = self._clamp(score)

        reasons: List[str] = []
        if urgency_score >= self.config.urgency_boost_threshold:
            reasons.append("high urgency content")
        if relationship_score > 0.7:
            reasons.append("strong sender relationship")
        if profile.last_interaction_days > self.config.dormancy_threshold_days:
            reasons.append("dormancy break detected")
        if context_penalty > 0.2:
            reasons.append("context suggests deferral")

        action = self._action_from_score(score)
        return Decision(action=action, priority_score=score, reasons=reasons)

    def _estimate_urgency(self, content: str) -> float:
        lowered = content.lower()
        score = 0.0
        for keyword, weight in self.urgency_keywords.items():
            if keyword in lowered:
                score = max(score, weight)

        if re.search(r"\b(call|call me|urgent|emergency|help|asap|now)\b", lowered):
            score = max(score, 0.7)

        if score == 0.0:
            return 0.2
        return min(1.0, score)

    def _context_penalty(self, context: Optional[UserContext]) -> float:
        if context is None:
            return 0.0

        penalty = 0.0
        if context.calendar_busy:
            penalty += 0.2
        if context.driving:
            penalty += 0.3
        if context.time_of_day in {"sleep", "night"}:
            penalty += 0.25
        if context.location_category == "meeting":
            penalty += 0.2
        if not context.screen_on:
            penalty += 0.1
        if context.battery_level < 20:
            penalty += 0.1
        if context.activity in {"running", "walking", "biking"}:
            penalty += 0.1
        if context.headphones_connected:
            penalty += 0.05
        return min(0.8, penalty)

    def _action_from_score(self, score: float) -> str:
        if score >= self.config.interrupt_threshold:
            return "interrupt"
        if score >= self.config.show_silently_threshold:
            return "show_silently"
        return "defer"

    def _clamp(self, value: float) -> float:
        return max(0.0, min(1.0, value))
