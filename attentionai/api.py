from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .models import Decision, InteractionProfile, NotificationEvent
from .policy import NotificationPolicy
from .privacy import hash_contact_id


class DictNotificationAdapter:
    def adapt(self, payload: Dict[str, Any]) -> NotificationEvent:
        return NotificationEvent.from_dict({
            "app_name": self._first_non_empty(payload, ["app_name", "application", "app"]),
            "sender_id": self._first_non_empty(payload, ["sender_id", "senderId", "sender"]),
            "sender_name": self._first_non_empty(payload, ["sender_name", "senderName", "name"]),
            "content": self._first_non_empty(payload, ["content", "message", "body"]),
            "timestamp": self._first_non_empty(payload, ["timestamp", "time", "sent_at"]),
            "context": self._extract_context(payload),
        })

    def _first_non_empty(self, payload: Dict[str, Any], keys: list[str]) -> Optional[str]:
        for key in keys:
            value = payload.get(key)
            if value is not None and value != "":
                return str(value)
        return None

    def _extract_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if payload.get("context") and isinstance(payload["context"], dict):
            return payload["context"]

        return {
            "time_of_day": payload.get("time_of_day"),
            "location_category": payload.get("location_category"),
            "calendar_busy": payload.get("calendar_busy"),
            "current_app": payload.get("current_app"),
            "screen_on": payload.get("screen_on"),
            "battery_level": payload.get("battery_level"),
            "driving": payload.get("driving"),
            "headphones_connected": payload.get("headphones_connected"),
            "activity": payload.get("activity"),
        }


class JsonProfileStore:
    def __init__(self, path: str | Path, hash_sender_id: bool = False) -> None:
        self.path = Path(path)
        self.hash_sender_id = hash_sender_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._load()
        else:
            self._data: Dict[str, Dict[str, Any]] = {}
            self._save()

    def _load(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                self._data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            self._data = {}
            self._save()

    def _save(self) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, indent=2)

    def _normalize_sender_id(self, sender_id: str) -> str:
        if self.hash_sender_id:
            return hash_contact_id(sender_id)
        return sender_id

    def get(self, sender_id: str) -> Optional[InteractionProfile]:
        key = self._normalize_sender_id(sender_id)
        raw = self._data.get(key)
        if not raw:
            return None
        return InteractionProfile.from_dict(raw)

    def save(self, profile: InteractionProfile) -> None:
        key = self._normalize_sender_id(profile.sender_id)
        saved_profile = profile.to_dict()
        if self.hash_sender_id:
            saved_profile["sender_id"] = key
        self._data[key] = saved_profile
        self._save()


class AttentionAIEngine:
    def __init__(self, policy: Optional[NotificationPolicy] = None, profile_store: Optional[JsonProfileStore] = None) -> None:
        self.policy = policy or NotificationPolicy()
        self.profile_store = profile_store

    def process(self, payload: Dict[str, Any], adapter: Optional[DictNotificationAdapter] = None) -> Decision:
        adapter = adapter or DictNotificationAdapter()
        event = adapter.adapt(payload)
        return self.process_event(event)

    def process_event(self, event: NotificationEvent) -> Decision:
        profile = self.profile_store.get(event.sender_id) if self.profile_store is not None else None
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
        profile.record_interaction(
            urgency=event.estimate_urgency(),
            responded=decision.is_interrupt(),
        )
        if self.profile_store is not None:
            self.profile_store.save(profile)

    def record_feedback(
        self,
        sender_id: str,
        responded: bool,
        response_time_seconds: Optional[float] = None,
        override: bool = False,
        days_since_last_interaction: int = 1,
    ) -> Optional[InteractionProfile]:
        if self.profile_store is None:
            return None

        profile = self.profile_store.get(sender_id) or InteractionProfile(sender_id=sender_id)
        profile.record_interaction(
            urgency=0.0,
            responded=responded,
            override=override,
            response_time_seconds=response_time_seconds,
            days_since_last_interaction=days_since_last_interaction,
        )
        self.profile_store.save(profile)
        return profile
