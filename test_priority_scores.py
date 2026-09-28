#!/usr/bin/env python3
"""Test the priority scores for different help messages."""

import json
from attentionai import (
    AttentionEngine,
    DictNotificationAdapter,
    JsonProfileStore,
    NotificationPolicy,
)
from attentionai.models import MS_PER_DAY
from pathlib import Path
import tempfile

# Test messages
messages = [
    "help",
    "hey i need help",
    "help me",
    "hey how are you i have something urgent, so i need help",
    "please help me",
]

NOW = 1_767_225_600_000

def test_priority_scores():
    """Test priority scores for each help message."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        store = JsonProfileStore(tmp_path / "profiles.json", hash_sender_id=True)
        engine = AttentionEngine(policy=NotificationPolicy(), profile_store=store)

        print("=" * 80)
        print("PRIORITY SCORE TEST FOR HELP MESSAGES")
        print("=" * 80)
        print()

        results = []

        for i, message in enumerate(messages, 1):
            payload = {
                "app_name": "WhatsApp",
                "sender_id": "test_contact@example.com",
                "sender_name": "Test Contact",
                "content": message,
                "timestamp_ms": NOW + (i * 1000),
            }

            decision = engine.process(payload, at_ms=NOW + (i * 1000))

            score_percent = int(decision.priority_score * 100)
            override = decision.components.get("override", 0.0)
            reasons = " | ".join(decision.reasons[:2]) if decision.reasons else "N/A"
            is_interrupt = "YES" if decision.is_interrupt else "NO"

            result = {
                "message": message,
                "priority_score": decision.priority_score,
                "priority_percent": score_percent,
                "override": override,
                "reasons": decision.reasons,
                "is_interrupt": decision.is_interrupt,
                "action": str(decision.action),
            }
            results.append(result)

            print(f"Message {i}: {message}")
            print(f"  Priority Score: {score_percent}% ({decision.priority_score:.3f})")
            print(f"  Override Factor: {override:.2f}")
            print(f"  Is Interrupt: {is_interrupt}")
            print(f"  Action: {decision.action}")
            print(f"  Reasons: {reasons}")
            print()

        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print()

        for i, result in enumerate(results, 1):
            is_interrupt = "YES" if result['is_interrupt'] else "NO"
            print(f"{i}. {result['message'][:50]:50} | Score: {result['priority_percent']:3}% | Interrupt: {is_interrupt}")

        print()
        print("=" * 80)

        return results

if __name__ == "__main__":
    results = test_priority_scores()
