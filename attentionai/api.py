from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .models import Decision, InteractionProfile, NotificationEvent, UserContext
from .policy import NotificationPolicy
from .privacy import hash_contact_id


class DictNotificationAdapter:
    def adapt(self, payload: Dict[str, Any]) -> NotificationEvent:
        context_payload = payload.get("context") or {}
        context = UserContext(
            time_of_day=context_payload.get("time_of_day", "day"),
            location_category=context_payload.get("location_category", "office"),
            calendar_busy=bool(context_payload.get("calendar_busy", False)),
            current_app=context_payload.get("current_app", "unknown"),
            screen_on=bool(context_payload.get("screen_on", True)),
            battery_level=int(context_payload.get("battery_level", 100)),
            driving=bool(context_payload.get("driving", False)),
            headphones_connected=bool(context_payload.get("headphones_connected", False)),
            activity=context_payload.get("activity", "stationary"),
        )
        return NotificationEvent(
            app_name=str(payload.get("app_name", "unknown")),
            sender_id=str(payload.get("sender_id", "unknown")),
            sender_name=payload.get("sender_name"),
            content=str(payload.get("content", "")),
            timestamp=payload.get("timestamp"),
            context=context,
        )


class JsonProfileStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._load()
        else:
            self._data: Dict[str, Dict[str, Any]] = {}
            self._save()

    def _load(self) -> None:
        with self.path.open("r", encoding="utf-8") as handle:
            self._data = json.load(handle)

    def _save(self) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2)

    def get(self, sender_id: str) -> Optional[InteractionProfile]:
        raw = self._data.get(sender_id)
        if not raw:
            return None
        return InteractionProfile(
            sender_id=raw.get("sender_id", sender_id),
            tier=int(raw.get("tier", 3)),
            relationship_score=float(raw.get("relationship_score", 0.5)),
            avg_response_time_seconds=float(raw.get("avg_response_time_seconds", 120.0)),
            open_rate=float(raw.get("open_rate", 0.5)),
            urgency_history=list(raw.get("urgency_history", [])),
            last_interaction_days=int(raw.get("last_interaction_days", 365)),
            manual_overrides=int(raw.get("manual_overrides", 0)),
        )

    def save(self, profile: InteractionProfile) -> None:
        self._data[profile.sender_id] = {
            "sender_id": profile.sender_id,
            "tier": profile.tier,
            "relationship_score": profile.relationship_score,
            "avg_response_time_seconds": profile.avg_response_time_seconds,
            "open_rate": profile.open_rate,
            "urgency_history": profile.urgency_history,
            "last_interaction_days": profile.last_interaction_days,
            "manual_overrides": profile.manual_overrides,
        }
        self._save()


class AttentionAIEngine:
    def __init__(self, policy: Optional[NotificationPolicy] = None, profile_store: Optional[JsonProfileStore] = None) -> None:
        self.policy = policy or NotificationPolicy()
        self.profile_store = profile_store

    def process(self, payload: Dict[str, Any], adapter: Optional[DictNotificationAdapter] = None) -> Decision:
        adapter = adapter or DictNotificationAdapter()
        event = adapter.adapt(payload)
        profile = None
        if self.profile_store is not None:
            profile = self.profile_store.get(event.sender_id)
        if profile is None:
            profile = InteractionProfile(sender_id=event.sender_id)
        decision = self.policy.analyze(event, profile)
        self._update_profile(profile, event, decision)
        return decision

    def get_profile(self, sender_id: str) -> Optional[InteractionProfile]:
        if self.profile_store is None:
            return None
        return self.profile_store.get(sender_id)

    def _update_profile(self, profile: InteractionProfile, event: NotificationEvent, decision: Decision) -> None:
        profile.urgency_history.append(self._estimate_content_weight(event.content))
        if decision.action == "interrupt":
            profile.relationship_score = min(1.0, profile.relationship_score + 0.05)
        elif decision.action == "defer":
            profile.relationship_score = max(0.0, profile.relationship_score - 0.02)
        if self.profile_store is not None:
            self.profile_store.save(profile)

    def _estimate_content_weight(self, content: str) -> float:
        lowered = (content or "").lower()
        if any(word in lowered for word in ["emergency", "urgent", "call me", "help", "asap"]):
            return 0.9
        if any(word in lowered for word in ["hey", "how are you", "what's up"]):
            return 0.2
        return 0.5
