"""Privacy helpers.

Two rules the rest of the package relies on:

1. Hashing is *idempotent*. ``hash_contact_id(hash_contact_id(x)) == hash_contact_id(x)``.
   The previous version double-hashed on every save/load round trip, which silently
   split one contact into two profiles and threw away everything it had learned.
2. Hashing is *salted per install*. A phone number has ~10 digits of entropy, so a
   bare SHA-256 of one is reversible with a laptop and an afternoon. The salt is
   generated once on the device and never leaves it.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Dict, Optional

__all__ = ["HASH_PREFIX", "new_salt", "is_hashed", "hash_contact_id", "sanitize_event"]

HASH_PREFIX = "ak_"
HASH_LENGTH = 24
_HASHED_LENGTH = len(HASH_PREFIX) + HASH_LENGTH


def new_salt() -> str:
    """Generate a per-install salt. Store it once; reuse it forever."""
    return secrets.token_hex(16)


def is_hashed(value: Optional[str]) -> bool:
    """True when ``value`` already looks like output of :func:`hash_contact_id`."""
    return (
        isinstance(value, str)
        and value.startswith(HASH_PREFIX)
        and len(value) == _HASHED_LENGTH
    )


def hash_contact_id(value: str, salt: str = "") -> str:
    """Map a raw sender identifier to a stable, opaque key.

    Idempotent: re-hashing an already-hashed key returns it unchanged.
    """
    if is_hashed(value):
        return value
    digest = hashlib.sha256(f"{salt}|{value}".encode("utf-8")).hexdigest()
    return HASH_PREFIX + digest[:HASH_LENGTH]


def sanitize_event(event: Any, salt: str = "") -> Dict[str, Any]:
    """Reduce a notification to numeric features safe to log or persist.

    Message text never survives this call -- only its length. Conversation
    metadata (thread / notification ids) is also stripped: a thread id is not
    the message, but it can tie a log line to a real conversation.
    """
    if isinstance(event, dict):
        get = event.get
    else:
        def get(key: str, default: Any = None) -> Any:
            return getattr(event, key, default)

    content = get("content", "") or ""
    return {
        "app_name": get("app_name"),
        "sender_key": hash_contact_id(str(get("sender_id", "") or ""), salt),
        "content_length": len(str(content)),
        "has_thread": bool(get("thread_id")),
        "has_notification_key": bool(get("notification_key")),
        "timestamp": get("timestamp"),
    }
