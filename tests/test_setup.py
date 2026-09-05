"""End-to-end smoke test for every module in the attentionai package.

Run with:  python -m pytest tests/test_setup.py -v
"""

import json
import tempfile
from pathlib import Path

import pytest

from attentionai import (
    DEFER,
    INTERRUPT,
    SHOW_SILENTLY,
    Decision,
    InteractionProfile,
    NotificationEvent,
    UserContext,
    AttentionEngine,
    DictNotificationAdapter,
    JsonProfileStore,
    NotificationPolicy,
    PolicyConfig,
    InterruptBudget,
    BudgetConfig,
    BudgetVerdict,
    EscalationTracker,
    EscalationConfig,
    EscalationSignal,
    UrgencyConfig,
    UrgencySignal,
    score_text,
    hash_contact_id,
    is_hashed,
    new_salt,
    sanitize_event,
    load_corpus,
    run_corpus,
    format_report,
    FEEDBACK_OPENED,
    FEEDBACK_DISMISSED,
    FEEDBACK_REPLIED,
    FEEDBACK_OUTBOUND,
    FEEDBACK_PROMOTED,
    FEEDBACK_DEMOTED,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW_MS = 1_700_000_000_000  # fixed reference point


def _make_event(**overrides) -> NotificationEvent:
    """Build a minimal valid NotificationEvent, with easy overrides."""
    base = {
        "app_name": "com.example.messenger",
        "sender_id": "alice",
        "sender_name": "Alice",
        "content": "Hello!",
        "timestamp_ms": NOW_MS,
    }
    base.update(overrides)
    return NotificationEvent.from_dict(base)


def _make_profile(**overrides) -> InteractionProfile:
    """Build a default InteractionProfile with overrides."""
    defaults = dict(sender_key="alice", tier=3, is_contact=True)
    defaults.update(overrides)
    return InteractionProfile(**defaults)


def _make_context(**overrides) -> UserContext:
    defaults = dict(time_of_day="day", location_category="home")
    defaults.update(overrides)
    return UserContext(**defaults)


# ===================================================================
# 1. Models
# ===================================================================

class TestUserContext:
    def test_defaults(self):
        ctx = UserContext()
        assert ctx.time_of_day == "day"
        assert ctx.battery_level == 100
        assert not ctx.driving
        assert not ctx.dnd_active

    def test_from_dict(self):
        ctx = UserContext.from_dict({"time_of_day": "sleep", "battery_level": 30})
        assert ctx.time_of_day == "sleep"
        assert ctx.battery_level == 30

    def test_from_dict_none(self):
        ctx = UserContext.from_dict(None)
        assert ctx.time_of_day == "day"

    def test_to_dict_roundtrip(self):
        ctx = UserContext(time_of_day="night", driving=True)
        d = ctx.to_dict()
        ctx2 = UserContext.from_dict(d)
        assert ctx2.time_of_day == "night"
        assert ctx2.driving is True

    def test_is_quiet_time(self):
        assert UserContext(dnd_active=True).is_quiet_time()
        assert UserContext(time_of_day="sleep").is_quiet_time()
        assert UserContext(time_of_day="night").is_quiet_time()
        assert UserContext(location_category="meeting").is_quiet_time()
        assert UserContext(driving=True).is_quiet_time()
        assert not UserContext().is_quiet_time()


class TestInteractionProfile:
    def test_effective_tier_prefers_manual(self):
        p = _make_profile(tier=4, manual_tier=1)
        assert p.effective_tier == 1

    def test_effective_tier_falls_back(self):
        p = _make_profile(tier=2, manual_tier=None)
        assert p.effective_tier == 2

    def test_open_rate_laplace_smoothing(self):
        p = _make_profile(response_count=0, received_count=0)
        assert p.open_rate == pytest.approx(0.5)
        p = _make_profile(response_count=5, received_count=5)
        assert p.open_rate == pytest.approx(6 / 7)  # Laplace: (5+1)/(5+2)

    def test_record_response(self):
        p = _make_profile(relationship_score=0.3)
        p.record_response(NOW_MS, response_seconds=60)
        assert p.response_count == 1
        assert p.relationship_score > 0.3
        assert p.peak_relationship >= p.relationship_score

    def test_record_dismissal(self):
        p = _make_profile(relationship_score=0.5)
        p.record_dismissal(NOW_MS)
        assert p.relationship_score < 0.5

    def test_record_outbound(self):
        p = _make_profile(relationship_score=0.3)
        p.record_outbound(NOW_MS)
        assert p.lifetime_interactions == 1
        assert p.relationship_score > 0.3

    def test_set_manual_tier_clamps(self):
        p = _make_profile()
        p.set_manual_tier(0)
        assert p.manual_tier == 1
        p.set_manual_tier(99)
        assert p.manual_tier == 5

    def test_from_dict_sender_id_alias(self):
        p = InteractionProfile.from_dict({"sender_id": "bob"})
        assert p.sender_key == "bob"

    def test_to_dict_roundtrip(self):
        p = _make_profile(tier=2, is_starred=True)
        d = p.to_dict()
        p2 = InteractionProfile.from_dict(d)
        assert p2.tier == 2
        assert p2.is_starred is True

    def test_from_dict_corrupt_manual_tier_does_not_crash(self):
        """A stored manual_tier that is not an int must not raise on load."""
        p = InteractionProfile.from_dict(
            {"sender_key": "a", "manual_tier": {"$oid": "fake"}, "tier": 99}
        )
        assert p.manual_tier is None
        # tier 99 is clamped to 5 by __post_init__
        assert p.tier == 5

    def test_post_init_clamps_tier(self):
        p = _make_profile(tier=99)
        assert p.tier == 5
        p = _make_profile(tier=-3)
        assert p.tier == 1

    def test_post_init_clamps_manual_tier(self):
        p = _make_profile(manual_tier=99)
        assert p.manual_tier == 5

    def test_repr_is_human_readable(self):
        p = _make_profile(tier=1, relationship_score=0.8)
        assert "tier=1" in repr(p)
        assert "rel=0.80" in repr(p)


class TestNotificationEvent:
    def test_from_dict_valid(self):
        e = _make_event()
        assert e.app_name == "com.example.messenger"
        assert e.sender_id == "alice"

    def test_from_dict_missing_app(self):
        with pytest.raises(ValueError, match="app_name"):
            NotificationEvent.from_dict({"sender_id": "x"})

    def test_from_dict_missing_sender(self):
        with pytest.raises(ValueError, match="sender_id"):
            NotificationEvent.from_dict({"app_name": "x"})

    def test_dedup_key_fallback(self):
        e = _make_event()
        assert e.dedup_key() == "com.example.messenger:alice"

    def test_dedup_key_notification_key(self):
        e = _make_event(notification_key="key-123")
        assert e.dedup_key() == "key-123"

    def test_summary(self):
        e = _make_event(sender_name="Alice")
        s = e.summary()
        assert "Alice" in s


class TestDecision:
    def test_actions(self):
        assert Decision(action=INTERRUPT, priority_score=1.0).is_interrupt()
        assert Decision(action=SHOW_SILENTLY, priority_score=0.5).is_show_silently()
        assert Decision(action=DEFER, priority_score=0.1).is_defer()
        assert not Decision(action=INTERRUPT, priority_score=1.0).is_defer()

    def test_to_dict(self):
        d = Decision(action=INTERRUPT, priority_score=0.9, reasons=["test"]).to_dict()
        assert d["action"] == "interrupt"
        assert d["reasons"] == ["test"]

    def test_repr_roundtrip(self):
        d = Decision(action=INTERRUPT, priority_score=0.9, reasons=["test"])
        assert "interrupt" in repr(d)
        assert "0.900" in repr(d)


# ===================================================================
# 2. Privacy
# ===================================================================

class TestPrivacy:
    def test_hash_is_idempotent(self):
        salt = new_salt()
        h = hash_contact_id("+1234567890", salt)
        assert hash_contact_id(h, salt) == h

    def test_hash_startswith_prefix(self):
        h = hash_contact_id("test", "")
        assert h.startswith("ak_")
        assert len(h) == 24 + 3  # prefix + 24 hex chars

    def test_is_hashed(self):
        h = hash_contact_id("test", "")
        assert is_hashed(h)
        assert not is_hashed("raw-sender-id")
        assert not is_hashed(None)

    def test_different_salts_differ(self):
        h1 = hash_contact_id("test", "salt-a")
        h2 = hash_contact_id("test", "salt-b")
        assert h1 != h2

    def test_sanitize_event_removes_content(self):
        e = _make_event(content="super secret message")
        result = sanitize_event(e.to_dict(), salt="s")
        assert "super secret" not in json.dumps(result)
        assert result["content_length"] == 20

    def test_sanitize_event_works_on_object(self):
        e = _make_event(content="hello")
        result = sanitize_event(e, salt="s")
        assert result["content_length"] == 5

    def test_sanitize_event_strips_thread_and_key(self):
        """Thread/notification ids can identify a conversation; only presence survives."""
        e = _make_event(
            thread_id="mean-reply-chain",
            notification_key="app.123",
        )
        result = sanitize_event(e.to_dict(), salt="s")
        raw = json.dumps(result)
        assert "mean-reply-chain" not in raw
        assert "app.123" not in raw
        assert result["has_thread"] is True
        assert result["has_notification_key"] is True

    def test_sanitize_event_no_thread_flags_false(self):
        e = _make_event()
        result = sanitize_event(e, salt="s")
        assert result["has_thread"] is False
        assert result["has_notification_key"] is False

    def test_new_salt_length(self):
        salt = new_salt()
        assert len(salt) == 32  # 16 bytes hex


# ===================================================================
# 3. Urgency scoring
# ===================================================================

class TestUrgency:
    def test_empty_content(self):
        sig = score_text("")
        assert sig.score == pytest.approx(0.05)

    def test_emergency_keyword(self):
        sig = score_text("this is an emergency")
        assert sig.score >= 0.9

    def test_spam_dampens(self):
        sig = score_text("FREE PRIZE winner click here")
        assert sig.spam_penalty > 0.3

    def test_negation_reduces(self):
        sig_normal = score_text("I need help")
        sig_negated = score_text("I don't need help")
        assert sig_negated.score < sig_normal.score

    def test_hinglish_terms(self):
        sig = score_text("madad karo please")
        assert sig.score >= 0.8

    def test_shouting_bonus(self):
        sig = score_text("HELP HELP HELP HELP HELP HELP")
        assert sig.score > 0.6

    def test_spam_offers(self):
        sig = score_text("LIMITED TIME offer discount 50%")
        assert sig.spam_penalty >= 0.5

    def test_custom_config(self):
        cfg = UrgencyConfig(terms={"customword": 0.99}, floor=0.0)
        sig = score_text("customword", cfg)
        assert sig.score >= 0.9


# ===================================================================
# 4. Escalation
# ===================================================================

class TestEscalation:
    def test_single_message_no_escalation(self):
        tracker = EscalationTracker()
        sig = tracker.record("alice", NOW_MS)
        assert sig.score == 0.0
        assert sig.burst_count == 1

    def test_burst_increases_score(self):
        tracker = EscalationTracker()
        for i in range(5):
            sig = tracker.record("alice", NOW_MS + i * 10_000)
        assert sig.score > 0.3
        assert sig.burst_count >= 4

    def test_call_override(self):
        cfg = EscalationConfig(override_call_count=3)
        tracker = EscalationTracker(cfg)
        for i in range(3):
            sig = tracker.record("alice", NOW_MS + i * 10_000, is_call=True)
        assert sig.override_factor > 0.0

    def test_peek_does_not_record(self):
        tracker = EscalationTracker()
        tracker.record("alice", NOW_MS)
        sig_before = tracker.peek("alice", NOW_MS + 1000)
        assert sig_before.burst_count == 1
        # peek doesn't add
        sig_after = tracker.peek("alice", NOW_MS + 1000)
        assert sig_after.burst_count == 1

    def test_reset_single_sender(self):
        tracker = EscalationTracker()
        tracker.record("alice", NOW_MS)
        tracker.record("bob", NOW_MS)
        tracker.reset("alice")
        assert tracker.peek("alice", NOW_MS).burst_count == 0
        assert tracker.peek("bob", NOW_MS).burst_count == 1

    def test_reset_all(self):
        tracker = EscalationTracker()
        tracker.record("alice", NOW_MS)
        tracker.reset()
        assert tracker.peek("alice", NOW_MS).burst_count == 0

    def test_mentions_boost_weight(self):
        tracker = EscalationTracker()
        tracker.record("alice", NOW_MS)
        sig_no_mention = tracker.peek("alice", NOW_MS)
        tracker.reset()
        tracker.record("alice", NOW_MS, mentions_user=True)
        sig_with_mention = tracker.peek("alice", NOW_MS)
        # Mention weight > message weight, but first message is always 0 escalation
        assert sig_with_mention.score >= sig_no_mention.score


# ===================================================================
# 5. Budget
# ===================================================================

class TestBudget:
    def test_allows_within_budget(self):
        budget = InterruptBudget()
        v = budget.check("alice", 0.8, NOW_MS)
        assert v.allowed

    def test_exhausts_budget(self):
        cfg = BudgetConfig(max_interrupts_per_window=2)
        budget = InterruptBudget(cfg)
        budget.commit("a", NOW_MS, "d1")
        budget.commit("b", NOW_MS + 1, "d2")
        v = budget.check("c", 0.8, NOW_MS + 2)
        assert not v.allowed
        assert v.reason == "hourly_budget_exhausted"

    def test_sender_cooldown(self):
        cfg = BudgetConfig(per_sender_cooldown_ms=60_000)
        budget = InterruptBudget(cfg)
        budget.commit("alice", NOW_MS, "d1")
        v = budget.check("alice", 0.8, NOW_MS + 30_000)
        assert not v.allowed
        assert v.reason == "sender_cooldown"

    def test_sender_cooldown_expires(self):
        cfg = BudgetConfig(per_sender_cooldown_ms=60_000)
        budget = InterruptBudget(cfg)
        budget.commit("alice", NOW_MS, "d1")
        v = budget.check("alice", 0.8, NOW_MS + 70_000)
        assert v.allowed

    def test_high_score_bypasses_budget(self):
        cfg = BudgetConfig(max_interrupts_per_window=1, bypass_score=0.90)
        budget = InterruptBudget(cfg)
        budget.commit("a", NOW_MS, "d1")
        v = budget.check("b", 0.95, NOW_MS + 1000)
        assert v.allowed

    def test_dedup_suppresses(self):
        cfg = BudgetConfig(duplicate_ttl_ms=300_000)
        budget = InterruptBudget(cfg)
        budget.commit("a", NOW_MS, "dedup-key")
        v = budget.check("b", 0.8, NOW_MS + 10_000, dedup_key="dedup-key")
        assert not v.allowed
        assert v.reason == "duplicate_notification"

    def test_remaining(self):
        cfg = BudgetConfig(max_interrupts_per_window=3)
        budget = InterruptBudget(cfg)
        assert budget.remaining(NOW_MS) == 3
        budget.commit("a", NOW_MS, "d1")
        assert budget.remaining(NOW_MS) == 2

    def test_reset(self):
        budget = InterruptBudget()
        budget.commit("a", NOW_MS, "d1")
        budget.reset()
        assert budget.remaining(NOW_MS) == BudgetConfig().max_interrupts_per_window

    def test_budget_verdict_to_dict(self):
        v = BudgetVerdict(allowed=False, reason="test", remaining=1)
        d = v.to_dict()
        assert d["allowed"] is False
        assert d["remaining"] == 1


# ===================================================================
# 6. Policy
# ===================================================================

class TestPolicy:
    def test_high_urgency_high_bond_interrupts(self):
        policy = NotificationPolicy()
        event = _make_event(content="emergency call me back")
        profile = _make_profile(tier=1, relationship_score=0.8, is_starred=True)
        decision = policy.analyze(event, profile, at_ms=NOW_MS)
        assert decision.is_interrupt()
        assert decision.priority_score > 0.7

    def test_spam_is_deferred(self):
        policy = NotificationPolicy()
        event = _make_event(content="FREE PRIZE winner lottery click here")
        decision = policy.analyze(event, at_ms=NOW_MS)
        assert decision.is_defer()

    def test_ongoing_notification_deferred(self):
        policy = NotificationPolicy()
        event = _make_event(is_ongoing=True)
        decision = policy.analyze(event, at_ms=NOW_MS)
        assert decision.is_defer()
        assert "non_conversational" in decision.suppressed_by

    def test_group_without_mention_damped(self):
        policy = NotificationPolicy()
        event = _make_event(is_group=True, mentions_user=False, content="hello")
        decision = policy.analyze(event, _make_profile(), at_ms=NOW_MS)
        # Group without mention should lower need
        components = decision.components
        assert components.get("need", 0) < 0.5

    def test_missed_call_boosts(self):
        policy = NotificationPolicy()
        event = _make_event(is_missed_call=True, content="hi")
        profile = _make_profile(tier=2, relationship_score=0.6)
        decision = policy.analyze(event, profile, at_ms=NOW_MS)
        assert decision.components["need"] >= 0.85

    def test_muted_sender_suppressed(self):
        policy = NotificationPolicy()
        event = _make_event(content="emergency")
        profile = _make_profile(tier=1, muted=True, relationship_score=0.9)
        decision = policy.analyze(event, profile, at_ms=NOW_MS)
        # Muted sender should not get interrupt (unless override)
        assert not decision.is_interrupt()
        assert "sender is muted" in decision.reasons

    def test_context_penalties_apply(self):
        policy = NotificationPolicy()
        event = _make_event(content="call me")
        ctx = _make_context(driving=True, time_of_day="sleep")
        event.context = ctx
        profile = _make_profile(tier=2, relationship_score=0.6)
        decision_driving = policy.analyze(event, profile, at_ms=NOW_MS)
        # Same event, normal context
        event.context = _make_context()
        decision_normal = policy.analyze(event, profile, at_ms=NOW_MS)
        assert decision_driving.priority_score < decision_normal.priority_score

    def test_negated_urgency_noted(self):
        policy = NotificationPolicy()
        event = _make_event(content="no emergency just checking in")
        decision = policy.analyze(event, at_ms=NOW_MS)
        assert any("negated" in r for r in decision.reasons)

    def test_components_populated(self):
        policy = NotificationPolicy()
        event = _make_event(content="urgent help")
        decision = policy.analyze(event, _make_profile(), at_ms=NOW_MS)
        expected_keys = {"need", "urgency", "escalation", "bond", "affinity", "context_penalty"}
        assert expected_keys.issubset(set(decision.components.keys()))


# ===================================================================
# 7. Engine (end-to-end wiring)
# ===================================================================

class TestAttentionEngine:
    def test_process_dict(self):
        engine = AttentionEngine()
        payload = {
            "app_name": "com.whatsapp",
            "sender_id": "alice",
            "sender_name": "Alice",
            "content": "emergency call me",
        }
        decision = engine.process(payload, at_ms=NOW_MS)
        assert decision.action in (INTERRUPT, SHOW_SILENTLY, DEFER)
        assert decision.priority_score > 0

    def test_process_event_with_profile_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "profiles.json")
            engine = AttentionEngine(profile_store=store)
            event = _make_event(content="hello there")
            decision = engine.process_event(event, at_ms=NOW_MS)
            assert decision.action in (INTERRUPT, SHOW_SILENTLY, DEFER)
            # Profile should be stored
            profile = store.get("alice")
            assert profile is not None
            assert profile.received_count >= 1

    def test_record_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "profiles.json")
            engine = AttentionEngine(profile_store=store)
            profile = engine.record_feedback("alice", FEEDBACK_OPENED, at_ms=NOW_MS)
            assert profile is not None
            assert profile.response_count == 1
            profile2 = engine.record_feedback("alice", FEEDBACK_DISMISSED, at_ms=NOW_MS)
            assert profile2.response_count == 1  # unchanged

    def test_record_feedback_no_store(self):
        engine = AttentionEngine()
        result = engine.record_feedback("alice", FEEDBACK_OPENED)
        assert result is None

    def test_record_feedback_invalid_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "profiles.json")
            engine = AttentionEngine(profile_store=store)
            with pytest.raises(ValueError, match="unknown feedback"):
                engine.record_feedback("alice", "nonsense")

    def test_bootstrap_contact(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "profiles.json")
            engine = AttentionEngine(profile_store=store)
            profile = engine.bootstrap_contact(
                "alice", tier=1, is_starred=True, lifetime_interactions=50
            )
            assert profile.tier == 1
            assert profile.is_starred is True
            assert profile.lifetime_interactions >= 50

    def test_get_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "profiles.json")
            engine = AttentionEngine(profile_store=store)
            engine.bootstrap_contact("alice")
            p = engine.get_profile("alice")
            assert p is not None

    def test_get_profile_no_store(self):
        engine = AttentionEngine()
        assert engine.get_profile("alice") is None

    def test_budget_suppresses(self):
        cfg = BudgetConfig(max_interrupts_per_window=1)
        budget = InterruptBudget(cfg)
        engine = AttentionEngine(budget=budget)
        # First high-score notification gets through
        d1 = engine.process(
            {"app_name": "a", "sender_id": "alice", "content": "emergency call me back"},
            at_ms=NOW_MS,
        )
        # Second from different sender should be suppressed by budget
        d2 = engine.process(
            {"app_name": "a", "sender_id": "bob", "content": "emergency call me back"},
            at_ms=NOW_MS + 100,
        )
        if d1.is_interrupt():
            assert not d2.is_interrupt()
            assert "hourly_budget_exhausted" in d2.suppressed_by

    def test_attentionai_engine_alias(self):
        assert AttentionEngine is not None
        from attentionai import AttentionAIEngine
        assert AttentionAIEngine is AttentionEngine


# ===================================================================
# 8. JsonProfileStore
# ===================================================================

class TestJsonProfileStore:
    def test_create_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            store = JsonProfileStore(path)
            profile = InteractionProfile(sender_key="alice", tier=1)
            store.save(profile)
            loaded = store.get("alice")
            assert loaded is not None
            assert loaded.tier == 1

    def test_hash_sender_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            store = JsonProfileStore(path, hash_sender_id=True)
            store.save(InteractionProfile(sender_key="alice", tier=1))
            # Raw "alice" should still resolve
            loaded = store.get("alice")
            assert loaded is not None

    def test_no_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profiles.json"
            store = JsonProfileStore(path, hash_sender_id=False)
            store.save(InteractionProfile(sender_key="alice"))
            assert store.get("alice") is not None

    def test_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "p.json")
            store.save(InteractionProfile(sender_key="alice"))
            store.delete("alice")
            assert store.get("alice") is None

    def test_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "p.json")
            store.save(InteractionProfile(sender_key="a"))
            store.save(InteractionProfile(sender_key="b"))
            store.clear()
            assert len(store.all_profiles()) == 0

    def test_corrupt_json_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text("{invalid json!!!", encoding="utf-8")
            # Should recover gracefully
            store = JsonProfileStore(path)
            assert len(store.all_profiles()) == 0

    def test_all_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "p.json")
            store.save(InteractionProfile(sender_key="a"))
            store.save(InteractionProfile(sender_key="b"))
            assert len(store.all_profiles()) == 2

    def test_existing_salt_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            s1 = JsonProfileStore(path)
            salt = s1.salt
            s2 = JsonProfileStore(path)
            assert s2.salt == salt

    def test_thread_safe_concurrent_writes(self):
        """Concurrent saves from multiple senders must not lose updates or corrupt file."""
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "p.json", hash_sender_id=False)

            def writer(sender: str) -> None:
                for i in range(20):
                    store.save(InteractionProfile(sender_key=sender, tier=1 + (i % 5)))

            threads = [threading.Thread(target=writer, args=(f"sender-{i}",)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(store.all_profiles()) == 4
            for i in range(4):
                profile = store.get(f"sender-{i}")
                assert profile is not None
                assert 1 <= profile.tier <= 5


# ===================================================================
# 9. DictNotificationAdapter
# ===================================================================

class TestDictNotificationAdapter:
    def test_alias_normalisation(self):
        adapter = DictNotificationAdapter()
        event = adapter.adapt({
            "application": "com.whatsapp",
            "sender": "bob",
            "body": "Hey!",
        })
        assert event.app_name == "com.whatsapp"
        assert event.sender_id == "bob"
        assert event.content == "Hey!"

    def test_context_from_nested_dict(self):
        adapter = DictNotificationAdapter()
        event = adapter.adapt({
            "app_name": "a",
            "sender_id": "b",
            "context": {"time_of_day": "sleep", "battery_level": 10},
        })
        assert event.context.time_of_day == "sleep"
        assert event.context.battery_level == 10

    def test_context_from_flat_keys(self):
        adapter = DictNotificationAdapter()
        event = adapter.adapt({
            "app_name": "a",
            "sender_id": "b",
            "driving": True,
        })
        assert event.context.driving is True

    def test_nested_empty_dict_context(self):
        """An empty context dict should not fall through to flat keys."""
        adapter = DictNotificationAdapter()
        event = adapter.adapt({
            "app_name": "a",
            "sender_id": "b",
            "context": {},
        })
        # Should still have defaults
        assert event.context.time_of_day == "day"


# ===================================================================
# 10. Corpus
# ===================================================================

class TestCorpus:
    def test_load_corpus(self):
        corpus_path = Path(__file__).resolve().parent.parent / "shared" / "scenarios.json"
        if not corpus_path.exists():
            pytest.skip("shared/scenarios.json not found")
        now_ms, scenarios = load_corpus(corpus_path)
        assert len(scenarios) > 0
        for s in scenarios:
            assert s.id
            assert s.expect in (INTERRUPT, SHOW_SILENTLY, DEFER)

    def test_run_corpus(self):
        corpus_path = Path(__file__).resolve().parent.parent / "shared" / "scenarios.json"
        if not corpus_path.exists():
            pytest.skip("shared/scenarios.json not found")
        results = run_corpus(path=corpus_path)
        assert len(results) > 0
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        # At least 70% should pass as a baseline
        assert passed / total >= 0.7, f"Only {passed}/{total} scenarios passed"

    def test_format_report(self):
        corpus_path = Path(__file__).resolve().parent.parent / "shared" / "scenarios.json"
        if not corpus_path.exists():
            pytest.skip("shared/scenarios.json not found")
        results = run_corpus(path=corpus_path)
        report = format_report(results, verbose=True)
        assert "scenarios passed" in report
        assert "missed interrupts" in report

    def test_load_corpus_with_custom_file(self):
        """Test loading from a minimal inline corpus."""
        corpus = {
            "now_ms": NOW_MS,
            "profiles": {},
            "scenarios": [
                {
                    "id": "test-1",
                    "expect": "defer",
                    "note": "spam test",
                    "event": {
                        "app_name": "a",
                        "sender_id": "spam",
                        "content": "FREE PRIZE winner lottery",
                    },
                },
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(corpus, f)
            f.flush()
            now_ms, scenarios = load_corpus(Path(f.name))
            assert len(scenarios) == 1
            assert scenarios[0].id == "test-1"

    def _write_corpus(self, payload: dict) -> Path:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(payload, f)
            f.flush()
            return Path(f.name)

    def test_corpus_rejects_top_level_non_object(self):
        path = self._write_corpus([1, 2, 3])
        with pytest.raises(ValueError, match="top level"):
            load_corpus(path)

    def test_corpus_rejects_missing_scenarios(self):
        path = self._write_corpus({"now_ms": NOW_MS})
        with pytest.raises(ValueError, match="'scenarios'"):
            load_corpus(path)

    def test_corpus_rejects_invalid_expect(self):
        path = self._write_corpus(
            {
                "now_ms": NOW_MS,
                "scenarios": [
                    {"id": "bad", "expect": "buzz_forever", "event": {"app_name": "a", "sender_id": "b"}}
                ],
            }
        )
        with pytest.raises(ValueError, match="invalid 'expect'"):
            load_corpus(path)

    def test_corpus_rejects_missing_event(self):
        path = self._write_corpus(
            {"now_ms": NOW_MS, "scenarios": [{"id": "bad", "expect": "defer"}]}
        )
        with pytest.raises(ValueError, match="missing 'event'"):
            load_corpus(path)

    def test_corpus_rejects_non_object_scenario(self):
        path = self._write_corpus({"now_ms": NOW_MS, "scenarios": ["not-a-dict"]})
        with pytest.raises(ValueError, match="not an object"):
            load_corpus(path)


# ===================================================================
# 11. Integration: full pipeline
# ===================================================================

class TestIntegration:
    def test_full_pipeline(self):
        """Process feedback -> profile changes -> decision changes."""
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonProfileStore(Path(tmp) / "profiles.json")
            engine = AttentionEngine(profile_store=store)

            # First: unknown sender, low priority
            d1 = engine.process(
                {"app_name": "a", "sender_id": "bob", "content": "hey"},
                at_ms=NOW_MS,
            )
            assert d1.action in (DEFER, SHOW_SILENTLY)

            # User repeatedly engages -> profile improves
            for i in range(10):
                engine.record_feedback("bob", FEEDBACK_OPENED, at_ms=NOW_MS + i * 1000)
            engine.record_feedback("bob", FEEDBACK_PROMOTED, at_ms=NOW_MS, tier=1)

            # Now same sender should score higher
            d2 = engine.process(
                {"app_name": "a", "sender_id": "bob", "content": "call me"},
                at_ms=NOW_MS + 20_000,
            )
            assert d2.priority_score > d1.priority_score

    def test_escalation_drives_interrupt(self):
        """Burst of messages from one sender should escalate."""
        tracker = EscalationTracker()
        engine = AttentionEngine(escalation=tracker)

        for i in range(6):
            engine.process(
                {"app_name": "a", "sender_id": "alice", "content": "help"},
                at_ms=NOW_MS + i * 5_000,
            )

        signal = tracker.peek(engine._key_for("alice"), NOW_MS + 30_000)
        assert signal.score > 0.5
