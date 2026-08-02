from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .api import AttentionAIEngine, DictNotificationAdapter, JsonProfileStore
from .policy import NotificationPolicy, NotificationPolicyConfig


def sample_payload() -> dict[str, Any]:
    return {
        "app_name": "WhatsApp",
        "sender_id": "friend@example.com",
        "sender_name": "Raj",
        "content": "Please call me ASAP, it's urgent",
        "context": {
            "time_of_day": "day",
            "location_category": "office",
            "calendar_busy": True,
            "battery_level": 85,
        },
    }


def load_payload(source: str | None) -> dict[str, Any]:
    if source is None:
        return sample_payload()

    if source == "-":
        return json.load(sys.stdin)

    payload_path = Path(source)
    with payload_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run AttentionAI notification prioritization against a JSON payload."
    )
    parser.add_argument(
        "payload",
        nargs="?",
        help="Path to a JSON payload file, or '-' for stdin. If omitted, a sample payload is used.",
    )
    parser.add_argument(
        "--profile-store",
        default="profiles.json",
        help="Path to the profile store JSON file.",
    )
    parser.add_argument(
        "--no-hash",
        action="store_true",
        help="Do not hash sender IDs in the stored profile file.",
    )
    args = parser.parse_args()

    payload = load_payload(args.payload)
    store = JsonProfileStore(args.profile_store, hash_sender_id=not args.no_hash)
    engine = AttentionAIEngine(
        policy=NotificationPolicy(config=NotificationPolicyConfig()),
        profile_store=store,
    )
    decision = engine.process(payload, adapter=DictNotificationAdapter())

    print("Decision:")
    print(json.dumps(decision.to_dict(), indent=2))
    print()
    print("Saved profile:")
    profile = engine.get_profile(payload.get("sender_id", ""))
    if profile is not None:
        print(json.dumps(profile.to_dict(), indent=2))
    else:
        print("No profile available.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
