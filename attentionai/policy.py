from __future__ import annotations

import re
from typing import Dict, List, Optional

from .models import Decision, InteractionProfile, NotificationEvent, UserContext


class NotificationPolicy:
    def __init__(self) -> None:
        self.urgency_keywords = {
            "urgent": 0.8,
            "emergency": 1.0,
            "help": 0.9,
            "call me": 0.9,
            "please": 0.2,
            "asap": 0.8,
            "now": 0.6,
        }

    def analyze(self, event: NotificationEvent, profile: Optional[InteractionProfile] = None) -> Decision:
        content = (event.content or "").lower()
        urgency_score = self._estimate_urgency(content)

        if profile is None:
            profile = InteractionProfile(sender_id=event.sender_id)

        relationship_score = profile.relationship_score
        tier_bonus = 0.1 * max(0, 5 - profile.tier)
        context_penalty = self._context_penalty(event.context)
        dormancy_bonus = 0.0

        if profile.last_interaction_days > 700:
            dormancy_bonus = 0.15

        score = urgency_score * 0.7 + relationship_score * 0.15 + tier_bonus * 0.08 + dormancy_bonus
        score -= context_penalty * 0.5
        if urgency_score >= 0.8:
            score += 0.15
        score = max(0.0, min(1.0, score))

        reasons: List[str] = []
        if urgency_score > 0.7:
            reasons.append("high urgency content")
        if relationship_score > 0.7:
            reasons.append("strong sender relationship")
        if profile.last_interaction_days > 700:
            reasons.append("dormancy break detected")
        if context_penalty > 0.2:
            reasons.append("context suggests deferral")

        if score >= 0.75:
            action = "interrupt"
        elif score >= 0.45:
            action = "show_silently"
        else:
            action = "defer"

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
        if context.time_of_day == "sleep" or context.time_of_day == "night":
            penalty += 0.25
        if context.location_category == "meeting":
            penalty += 0.2
        if not context.screen_on:
            penalty += 0.1
        return min(0.6, penalty)
