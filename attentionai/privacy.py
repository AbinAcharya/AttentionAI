from __future__ import annotations

import hashlib
from typing import Any, Dict


def hash_contact_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def sanitize_event(event: Any) -> Dict[str, Any]:
    return {
        "app_name": event.app_name,
        "sender_id": hash_contact_id(event.sender_id),
        "content_length": len(event.content or ""),
        "timestamp": event.timestamp,
    }
