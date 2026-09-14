"""Store, engine wiring, and regressions for the three v1 bugs."""

import json
from pathlib import Path

import pytest

from attentionai import (
    FEEDBACK_DISMISSED,
    FEEDBACK_OPENED,
    FEEDBACK_PROMOTED,
    AttentionEngine,
    DictNotificationAdapter,
    JsonProfileStore,
    NotificationPolicy,
)
from attentionai.models import INTERRUPT, MS_PER_DAY, SHOW_SILENTLY, InteractionProfile
from attentionai.privacy import hash_contact_id, is_hashed, new_salt

NOW = 1_767_225_600_000


def make_engine(tmp_path: Path, **kwargs) -> AttentionEngine:
    store = JsonProfileStore(tmp_path / "profiles.json", hash_sender_id=True)
    return AttentionEngine(policy=NotificationPolicy(), profile_store=store, **kwargs)


# --- regression: idempotent hashing ----------------------------------------


def test_hashing_is_idempotent() -> None:
    once = hash_contact_id("friend@example.com", "salt")
    twice = hash_contact_id(once, "salt")
    assert once == twice
    assert is_hashed(once)


def test_repeated_processing_keeps_one_profile_per_sender(tmp_path: Path) -> None:
    """v1 re-hashed on every save, forking one contact into two profiles."""
    engine = make_engine(tmp_path)
    payload = {"app_name": "WA", "sender_id": "raj@x.com", "content": "hello"}

    for index in range(5):
        engine.process(payload, at_ms=NOW + index * 1000)

    raw = json.loads((tmp_path / "profiles.json").read_text(encoding="utf-8"))
    assert len(raw["profiles"]) == 1

    profile = engine.get_profile("raj@x.com")
    assert profile is not None
    assert profile.received_count == 5


def test_store_never_writes_plaintext_ids(tmp_path: Path) -> None:
    store = JsonProfileStore(tmp_path / "profiles.json", hash_sender_id=True)
    store.save(InteractionProfile(sender_key="friend@example.com"))

    raw = (tmp_path / "profiles.json").read_text(encoding="utf-8")
    assert "friend@example.com" not in raw
    assert store.get("friend@example.com") is not None


def test_store_salt_is_persisted_and_reused(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    first = JsonProfileStore(path, hash_sender_id=True)
    first.save(InteractionProfile(sender_key="friend"))

    second = JsonProfileStore(path, hash_sender_id=True)
    assert second.salt == first.salt
    assert second.get("friend") is not None


def test_different_installs_produce_different_hashes() -> None:
    # A bare SHA-256 of a phone number is trivially reversible; the salt is the fix.
    assert hash_contact_id("+919876543210", new_salt()) != hash_contact_id(
        "+919876543210", new_salt()
    )


def test_clear_resets_profiles(tmp_path: Path) -> None:
    store = JsonProfileStore(tmp_path / "profiles.json", hash_sender_id=True)
    store.save(InteractionProfile(sender_key="friend"))
    store.clear()
    assert store.get("friend") is None
    assert store.all_profiles() == []


def test_legacy_flat_file_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"abc": {"sender_id": "abc", "tier": 1}}), encoding="utf-8")

    store = JsonProfileStore(path, hash_sender_id=False)
    assert store.get("abc") is not None
    assert store.get("abc").tier == 1


def test_corrupt_file_does_not_crash(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("{not json", encoding="utf-8")
    store = JsonProfileStore(path, hash_sender_id=True)
    assert store.all_profiles() == []


# --- regression: missing context -------------------------------------------


def test_payload_without_context_does_not_crash() -> None:
    # v1 built a dict full of None and then called int(None).
    adapter = DictNotificationAdapter()
    assert adapter.adapt({"app_name": "WA", "sender_id": "a", "content": "hi"}).context is not None


def test_payload_with_empty_context_does_not_crash() -> None:
    adapter = DictNotificationAdapter()
    event = adapter.adapt({"app_name": "WA", "sender_id": "a", "content": "hi", "context": {}})
    assert event.context.battery_level == 100


def test_partial_context_is_filled_with_defaults() -> None:
    adapter = DictNotificationAdapter()
    event = adapter.adapt(
        {"app_name": "WA", "sender_id": "a", "context": {"time_of_day": "night"}}
    )
    assert event.context.time_of_day == "night"
    assert event.context.screen_on is True


def test_flat_context_keys_are_accepted() -> None:
    adapter = DictNotificationAdapter()
    event = adapter.adapt(
        {"app_name": "WA", "sender_id": "a", "time_of_day": "sleep", "dnd_active": True}
    )
    assert event.context.time_of_day == "sleep"
    assert event.context.dnd_active is True


def test_adapter_rejects_payload_without_identity() -> None:
    with pytest.raises(ValueError):
        DictNotificationAdapter().adapt({"content": "hi"})


# --- regression: no self-training -------------------------------------------


def test_processing_does_not_raise_relationship_score(tmp_path: Path) -> None:
    """v1 recorded its own 'interrupt' decision as 'the user responded'."""
    engine = make_engine(tmp_path)
    payload = {"app_name": "WA", "sender_id": "raj", "content": "emergency, call me"}

    before = engine.profile_store.get_or_create("raj").relationship_score
    for index in range(10):
        engine.process(payload, at_ms=NOW + index * 60_000)
    after = engine.get_profile("raj").relationship_score

    assert after == before
    assert engine.get_profile("raj").received_count == 10


def test_feedback_is_the_only_thing_that_moves_the_score(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    before = engine.profile_store.get_or_create("raj").relationship_score

    engine.record_feedback("raj", FEEDBACK_OPENED, at_ms=NOW, response_seconds=12)
    opened = engine.get_profile("raj")
    assert opened.relationship_score > before
    assert opened.response_count == 1
    assert opened.peak_relationship >= opened.relationship_score

    engine.record_feedback("raj", FEEDBACK_DISMISSED, at_ms=NOW)
    assert engine.get_profile("raj").relationship_score < opened.relationship_score


def test_peak_relationship_never_decays(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    for index in range(10):
        engine.record_feedback("raj", FEEDBACK_OPENED, at_ms=NOW + index * 1000)

    profile = engine.get_profile("raj")
    peak = profile.peak_relationship
    for _ in range(20):
        profile.record_dismissal(NOW)

    assert profile.relationship_score < peak
    assert profile.peak_relationship == peak
    assert profile.decayed_relationship(NOW + int(900 * MS_PER_DAY)) < peak


def test_manual_promotion_wins_over_learned_tier(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    engine.bootstrap_contact("raj", tier=5)
    engine.record_feedback("raj", FEEDBACK_PROMOTED, at_ms=NOW, tier=1)

    profile = engine.get_profile("raj")
    assert profile.tier == 5
    assert profile.effective_tier == 1


def test_unknown_feedback_kind_is_rejected(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    with pytest.raises(ValueError):
        engine.record_feedback("raj", "nonsense")


# --- engine end to end ------------------------------------------------------


def test_bootstrapping_from_contacts_beats_a_cold_start(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    payload = {
        "app_name": "WA",
        "sender_id": "mum",
        "content": "please call me, it's urgent",
        "context": {"time_of_day": "night", "dnd_active": True},
    }

    cold = engine.process(payload, at_ms=NOW)
    engine.bootstrap_contact("mum", tier=1, is_starred=True, lifetime_interactions=500)
    warm = engine.process(payload, at_ms=NOW + 60 * 60_000)

    assert warm.priority_score > cold.priority_score


def test_escalation_state_accumulates_across_calls(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    engine.bootstrap_contact("sibling", tier=2, is_contact=True, lifetime_interactions=300)
    engine.record_feedback("sibling", FEEDBACK_OPENED, at_ms=NOW - 86_400_000)

    payload = {
        "app_name": "WA",
        "sender_id": "sibling",
        "content": "are you awake",
        "context": {"time_of_day": "sleep", "dnd_active": True},
    }

    first = engine.process(payload, at_ms=NOW)
    fourth = None
    for index in range(1, 4):
        fourth = engine.process(payload, at_ms=NOW + index * 30_000)

    assert fourth.priority_score > first.priority_score


# --- regression: budget must not de-duplicate a repeated emergency -----------


def _raising_profile(store: JsonProfileStore, sender_id: str, score: float = 0.95) -> None:
    """Give a sender tier-1 closeness so ordinary urgency can interrupt."""
    store.save(InteractionProfile(sender_key=sender_id, tier=1, is_starred=True, relationship_score=score))


def test_second_help_updating_the_same_notification_interrupts_again(tmp_path: Path) -> None:
    """The repeat "help" is an update of the same conversation notification, so its
    dedup key is identical. The budget used to deny it as a duplicate; critical
    wording must never be rate-limited."""
    engine = make_engine(tmp_path)
    payload = {
        "app_name": "WA",
        "sender_id": "raj@x.com",
        "content": "help",
        "notification_key": "0|com.whatsapp|123|tx",
    }
    first = engine.process(payload, at_ms=NOW)
    second = engine.process(payload, at_ms=NOW + 60_000)

    assert first.action == INTERRUPT
    assert second.action == INTERRUPT


def test_repeated_calls_from_stranger_are_not_budget_denied(tmp_path: Path) -> None:
    """A stranger's repeated calls open the emergency override, but it ramps:
    call_count >= 3 opens it (0.6), and it only reaches the 0.70 interrupt
    threshold at 5 calls (override_factor 1.0 * 0.85 max). Once engaged, a
    quick repeat must not be held back by the budget dedup/cooldown."""
    engine = make_engine(tmp_path)
    base = {
        "app_name": "WA",
        "sender_id": "+91-9876543210",
        "content": "",
        "is_missed_call": True,
        "notification_key": "0|com.whatsapp|789|call",
    }
    # Build up the burst: calls 1-4 are too few to clear the threshold (0.51, 0.68),
    # call 5 triggers the override properly.
    for i in range(5):
        engine.process(dict(base), at_ms=NOW + i * 30_000)

    # The 6th call (still within the window) must NOT be budget-denied.
    repeat = engine.process(dict(base), at_ms=NOW + 150_000)
    assert repeat.action == INTERRUPT
    assert repeat.suppressed_by is None


def test_ordinary_urgent_repeat_still_respects_the_cooldown(tmp_path: Path) -> None:
    """Back-pressure must survive the fix: only the emergency override is exempted,
    ordinary (non-critical) urgency still gets held back on a quick repeat."""
    engine = make_engine(tmp_path)
    _raising_profile(engine.profile_store, "raj@x.com")
    payload = {
        "app_name": "WA",
        "sender_id": "raj@x.com",
        "content": "call me back, it is urgent",
        "notification_key": "0|com.whatsapp|456|tx",
    }
    first = engine.process(payload, at_ms=NOW)
    second = engine.process(payload, at_ms=NOW + 60_000)

    assert first.action == INTERRUPT
    assert second.action == SHOW_SILENTLY
    assert second.suppressed_by is not None
