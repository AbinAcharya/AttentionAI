from __future__ import annotations

import hashlib
from typing import Any, Dict


def hash_contact_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def sanitize_event(event: Any) -> Dict[str, Any]:
    if isinstance(event, dict):
        return {
            "app_name": event.get("app_name"),
            "sender_id": hash_contact_id(str(event.get("sender_id", ""))),
            "content_length": len(str(event.get("content", ""))),
            "timestamp": event.get("timestamp"),
        }

    return {
        "app_name": getattr(event, "app_name", None),
        "sender_id": hash_contact_id(str(getattr(event, "sender_id", ""))),
        "content_length": len(str(getattr(event, "content", ""))),
        "timestamp": getattr(event, "timestamp", None),
    }
