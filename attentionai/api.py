"""Engine wiring: adapter -> profile -> policy -> budget -> decision.

The engine no longer trains on its own output. ``process()`` only records that a
notification was *delivered*; the relationship score moves solely through
``record_feedback()``, which the Android layer drives from real user behaviour
(``onNotificationRemoved`` with ``REASON_CLICK`` vs ``REASON_CANCEL``).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "FEEDBACK_OPENED",
    "FEEDBACK_DISMISSED",
    "FEEDBACK_REPLIED",
    "FEEDBACK_OUTBOUND",
    "FEEDBACK_PROMOTED",
    "FEEDBACK_DEMOTED",
    "DictNotificationAdapter",
    "JsonProfileStore",
    "AttentionEngine",
    "AttentionAIEngine",
]

from .budget import BudgetConfig, BudgetVerdict, InterruptBudget
from .escalation import EscalationConfig, EscalationSignal, EscalationTracker
from .models import (
    DEFER,
    INTERRUPT,
    SHOW_SILENTLY,
    Decision,
    InteractionProfile,
    NotificationEvent,
    UserContext,
    now_ms,
)
from .policy import NotificationPolicy, PolicyConfig
from .privacy import hash_contact_id, is_hashed, new_salt

# Feedback kinds, mirroring what a NotificationListenerService can actually observe.
FEEDBACK_OPENED = "opened"
FEEDBACK_DISMISSED = "dismissed"
FEEDBACK_REPLIED = "replied"
FEEDBACK_OUTBOUND = "outbound"
FEEDBACK_PROMOTED = "promoted"
FEEDBACK_DEMOTED = "demoted"


class DictNotificationAdapter:
    """Normalise a loosely-shaped dict into a :class:`NotificationEvent`."""

    _ALIASES = {
        "app_name": ["app_name", "application", "app", "package"],
        "sender_id": ["sender_id", "senderId", "sender", "person_key"],
        "sender_name": ["sender_name", "senderName", "name", "title"],
        "content": ["content", "message", "body", "text"],
        "thread_id": ["thread_id", "threadId", "conversation_id"],
        "notification_key": ["notification_key", "key", "sbn_key"],
    }

    _CONTEXT_KEYS = [
        "time_of_day", "location_category", "calendar_busy", "current_app",
        "screen_on", "battery_level", "driving", "headphones_connected",
        "activity", "dnd_active",
    ]

    def adapt(self, payload: Dict[str, Any]) -> NotificationEvent:
        normalised: Dict[str, Any] = {
            field: self._first_present(payload, keys)
            for field, keys in self._ALIASES.items()
        }
        normalised.update({
            "timestamp_ms": payload.get("timestamp_ms") or payload.get("timestamp") or 0,
            "is_group": payload.get("is_group", False),
            "mentions_user": payload.get("mentions_user", False),
            "is_missed_call": payload.get("is_missed_call", False),
            "is_ongoing": payload.get("is_ongoing", False),
            "is_group_summary": payload.get("is_group_summary", False),
            "context": self._extract_context(payload),
        })
        return NotificationEvent.from_dict(normalised)

    def _first_present(self, payload: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            value = payload.get(key)
            if value is not None and value != "":
                return str(value)
        return None

    def _extract_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # `isinstance`, not truthiness: an empty dict is a legitimate context and
        # must not fall through to the flat-key path (that produced a dict full of
        # None and then crashed on int(None)).
        raw = payload.get("context")
        if isinstance(raw, dict):
            source = raw
        else:
            source = payload
        return {key: source[key] for key in self._CONTEXT_KEYS if source.get(key) is not None}


class JsonProfileStore:
    """File-backed profile store.

    Hashing happens exactly once, at the storage boundary, and
    :func:`hash_contact_id` is idempotent -- so a load/save round trip can no longer
    fork one contact into two profiles.

    All public read/write methods hold a :class:`threading.Lock`, so the store is
    safe to share across threads (e.g. a per-app worker pool). The atomic
    :func:`os.replace` write protects the file, and the lock protects the in-memory
    ``_data`` dict; both are needed.
    """

    def __init__(
        self,
        path: str | Path,
        hash_sender_id: bool = True,
        salt: Optional[str] = None,
    ) -> None:
        self.path = Path(path)
        self.hash_sender_id = hash_sender_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Dict[str, Any]] = {}
        self._salt = salt or ""
        self._lock = threading.RLock()
        self._load()
        if hash_sender_id and not self._salt:
            self._salt = new_salt()
            self._save()

    @property
    def salt(self) -> str:
        return self._salt

    def key_for(self, sender_id: str) -> str:
        if not self.hash_sender_id:
            return sender_id
        return hash_contact_id(sender_id, self._salt)

    def get(self, sender_id: str) -> Optional[InteractionProfile]:
        with self._lock:
            raw = self._data.get(self.key_for(sender_id))
            if not raw:
                return None
            return InteractionProfile.from_dict(raw)

    def get_or_create(self, sender_id: str) -> InteractionProfile:
        return self.get(sender_id) or InteractionProfile(sender_key=self.key_for(sender_id))

    def save(self, profile: InteractionProfile) -> None:
        key = self.key_for(profile.sender_key)
        stored = profile.to_dict()
        stored["sender_key"] = key
        with self._lock:
            self._data[key] = stored
            self._save()

    def all_profiles(self) -> List[InteractionProfile]:
        with self._lock:
            return [InteractionProfile.from_dict(raw) for raw in self._data.values()]

    def delete(self, sender_id: str) -> None:
        with self._lock:
            self._data.pop(self.key_for(sender_id), None)
            self._save()

    def clear(self) -> None:
        """Local profile reset, as promised in the privacy notes."""
        with self._lock:
            self._data.clear()
            self._salt = new_salt() if self.hash_sender_id else ""
            self._save()

    # ---- internals -----------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            self._save()
            return
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError):
            self._data = {}
            self._save()
            return

        if isinstance(payload, dict) and "profiles" in payload:
            self._salt = str(payload.get("salt") or "")
            self._data = dict(payload.get("profiles") or {})
        elif isinstance(payload, dict):
            # Legacy flat layout: {sender_key: profile}
            self._data = {
                key: value for key, value in payload.items() if isinstance(value, dict)
            }
        else:
            self._data = {}

    def _save(self) -> None:
        payload = {"version": 2, "salt": self._salt, "profiles": self._data}
        # Atomic write: a half-written profile file on a phone that lost power
        # should not cost the user everything the app has learned.
        directory = self.path.parent
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
        )
        try:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, self.path)


class AttentionEngine:
    """Top-level entry point. One instance per process."""

    def __init__(
        self,
        policy: Optional[NotificationPolicy] = None,
        profile_store: Optional[JsonProfileStore] = None,
        escalation: Optional[EscalationTracker] = None,
        budget: Optional[InterruptBudget] = None,
    ) -> None:
        self.policy = policy or NotificationPolicy()
        self.profile_store = profile_store
        self.escalation = escalation or EscalationTracker()
        self.budget = budget or InterruptBudget()

    # ---- decisioning ---------------------------------------------------------

    def process(
        self,
        payload: Dict[str, Any],
        adapter: Optional[DictNotificationAdapter] = None,
        at_ms: Optional[int] = None,
    ) -> Decision:
        adapter = adapter or DictNotificationAdapter()
        return self.process_event(adapter.adapt(payload), at_ms=at_ms)

    def process_event(
        self,
        event: NotificationEvent,
        at_ms: Optional[int] = None,
    ) -> Decision:
        at_ms = at_ms if at_ms is not None else (event.timestamp_ms or now_ms())
        key = self._key_for(event.sender_id)

        if event.is_ongoing or event.is_group_summary:
            return self.policy.analyze(event, None, None, at_ms)

        profile = (
            self.profile_store.get_or_create(event.sender_id)
            if self.profile_store is not None
            else InteractionProfile(sender_key=key)
        )

        escalation = self.escalation.record(
            key,
            at_ms,
            is_call=event.is_missed_call,
            mentions_user=event.mentions_user,
        )

        decision = self.policy.analyze(event, profile, escalation, at_ms)

        # Delivery is recorded, engagement is not. The engine never labels its own
        # output as a success.
        profile.record_delivery(at_ms)
        if self.profile_store is not None:
            self.profile_store.save(profile)

        decision = self._apply_budget(decision, key, event, at_ms)
        return decision

    def _apply_budget(
        self,
        decision: Decision,
        key: str,
        event: NotificationEvent,
        at_ms: int,
    ) -> Decision:
        dedup_key = event.dedup_key()
        if not decision.is_interrupt():
            self.budget.note_shown(dedup_key, at_ms)
            return decision

        verdict = self.budget.check(key, decision.priority_score, at_ms, dedup_key)
        if verdict.allowed:
            self.budget.commit(key, at_ms, dedup_key)
            return decision

        return Decision(
            action=SHOW_SILENTLY,
            priority_score=decision.priority_score,
            reasons=decision.reasons + [f"held back: {verdict.reason}"],
            components=decision.components,
            suppressed_by=verdict.reason,
        )

    # ---- learning ------------------------------------------------------------

    def record_feedback(
        self,
        sender_id: str,
        kind: str,
        at_ms: Optional[int] = None,
        response_seconds: Optional[float] = None,
        tier: Optional[int] = None,
    ) -> Optional[InteractionProfile]:
        """Apply an observed user action to a sender's profile.

        ``kind`` is one of the ``FEEDBACK_*`` constants. This is the only path that
        moves ``relationship_score``.
        """
        if self.profile_store is None:
            return None

        at_ms = at_ms if at_ms is not None else now_ms()
        profile = self.profile_store.get_or_create(sender_id)

        if kind in (FEEDBACK_OPENED, FEEDBACK_REPLIED):
            profile.record_response(at_ms, response_seconds)
        elif kind == FEEDBACK_DISMISSED:
            profile.record_dismissal(at_ms)
        elif kind == FEEDBACK_OUTBOUND:
            profile.record_outbound(at_ms)
        elif kind == FEEDBACK_PROMOTED:
            profile.set_manual_tier(tier if tier is not None else 1)
        elif kind == FEEDBACK_DEMOTED:
            profile.set_manual_tier(tier if tier is not None else 5)
        else:
            raise ValueError(f"unknown feedback kind: {kind!r}")

        self.profile_store.save(profile)
        return profile

    def bootstrap_contact(
        self,
        sender_id: str,
        tier: int = 3,
        is_contact: bool = True,
        is_starred: bool = False,
        lifetime_interactions: int = 0,
    ) -> Optional[InteractionProfile]:
        """Seed a profile from the address book / call log at onboarding.

        Without this every sender starts at tier 3 with no history, which is the
        worst possible cold start for a feature whose whole job is to know who
        matters.
        """
        if self.profile_store is None:
            return None
        profile = self.profile_store.get_or_create(sender_id)
        profile.tier = max(1, min(5, tier))
        profile.is_contact = is_contact
        profile.is_starred = is_starred
        if lifetime_interactions:
            profile.lifetime_interactions = max(profile.lifetime_interactions, lifetime_interactions)
        if is_starred:
            profile.peak_relationship = max(profile.peak_relationship, 0.75)
            profile.relationship_score = max(profile.relationship_score, 0.6)
        self.profile_store.save(profile)
        return profile

    def get_profile(self, sender_id: str) -> Optional[InteractionProfile]:
        if self.profile_store is None:
            return None
        return self.profile_store.get(sender_id)

    def _key_for(self, sender_id: str) -> str:
        if self.profile_store is not None:
            return self.profile_store.key_for(sender_id)
        return sender_id


# Backwards-compatible alias for the old class name.
AttentionAIEngine = AttentionEngine
