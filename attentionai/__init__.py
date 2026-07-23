"""AttentionAI package entry point."""

from .api import AttentionAIEngine, DictNotificationAdapter, JsonProfileStore
from .models import Decision, NotificationEvent, UserContext, InteractionProfile
from .policy import NotificationPolicy
from .privacy import hash_contact_id, sanitize_event

__all__ = [
    "Decision",
    "NotificationEvent",
    "UserContext",
    "InteractionProfile",
    "NotificationPolicy",
    "AttentionAIEngine",
    "DictNotificationAdapter",
    "JsonProfileStore",
    "hash_contact_id",
    "sanitize_event",
]
