"""Policy behaviour, focused on the cases the additive v1 model got wrong."""

from attentionai.escalation import EscalationSignal
from attentionai.models import MS_PER_DAY, InteractionProfile, NotificationEvent, UserContext
from attentionai.policy import NotificationPolicy, PolicyConfig

NOW = 1_767_225_600_000  # 2026-01-01T00:00:00Z, fixed for determinism


def days_ago(days: float) -> int:
    return int(NOW - days * MS_PER_DAY)


def close_friend(**overrides) -> InteractionProfile:
    base = dict(
        sender_key="friend",
        tier=2,
        relationship_score=0.8,
        peak_relationship=0.85,
        lifetime_interactions=300,
        response_count=150,
        received_count=190,
        last_seen_ms=days_ago(2),
    )
    base.update(overrides)
    return InteractionProfile(**base)


def stranger(**overrides) -> InteractionProfile:
    base = dict(
        sender_key="stranger",
        tier=5,
        relationship_score=0.15,
        peak_relationship=0.2,
        lifetime_interactions=0,
        received_count=3,
    )
    base.update(overrides)
    return InteractionProfile(**base)


def event(content: str, **overrides) -> NotificationEvent:
    base = dict(
        app_name="WhatsApp",
        sender_id="friend",
        content=content,
        context=UserContext(time_of_day="night", dnd_active=True, screen_on=False),
    )
    base.update(overrides)
    return NotificationEvent(**base)


def score(policy: NotificationPolicy, ev, profile, escalation=None) -> float:
    return policy.analyze(ev, profile, escalation, at_ms=NOW).priority_score


# --- the reunion case -------------------------------------------------------


def test_dormant_close_friend_asking_for_help_interrupts() -> None:
    policy = NotificationPolicy()
    profile = close_friend(last_seen_ms=days_ago(800))
    decision = policy.analyze(event("I really need help, please call me"), profile, at_ms=NOW)

    assert decision.action == "interrupt"
    assert decision.components["reunion"] == 1.0


def test_dormant_close_friend_making_small_talk_does_not_interrupt() -> None:
    """Dormancy must scale with need, not be a flat bonus. v1 added a constant."""
    policy = NotificationPolicy()
    profile = close_friend(last_seen_ms=days_ago(800))
    decision = policy.analyze(event("happy new year! long time no see"), profile, at_ms=NOW)

    assert decision.action == "defer"


def test_reunion_bonus_requires_prior_closeness() -> None:
    """A dormant stranger is just a stranger -- this is the anti-spam gate."""
    policy = NotificationPolicy()
    never_close = stranger(
        peak_relationship=0.2,
        lifetime_interactions=0,
        last_seen_ms=days_ago(900),
    )
    decision = policy.analyze(event("emergency, call me now"), never_close, at_ms=NOW)

    assert decision.components["reunion"] == 0.0
    assert decision.action != "interrupt"


def test_reunion_ramps_with_dormancy() -> None:
    policy = NotificationPolicy()
    message = event("I really need help, please call me")

    recent = score(policy, message, close_friend(last_seen_ms=days_ago(5)))
    medium = score(policy, message, close_friend(last_seen_ms=days_ago(100)))
    dormant = score(policy, message, close_friend(last_seen_ms=days_ago(400)))

    assert recent < medium < dormant


# --- multiplicative structure ----------------------------------------------


def test_closeness_alone_never_interrupts() -> None:
    """v1's additive tier/relationship bonuses could reach the threshold alone."""
    policy = NotificationPolicy()
    partner = InteractionProfile(
        sender_key="partner",
        tier=1,
        manual_tier=1,
        relationship_score=1.0,
        peak_relationship=1.0,
        lifetime_interactions=5000,
        response_count=990,
        received_count=1000,
        is_starred=True,
        last_seen_ms=NOW,
    )
    decision = policy.analyze(event("lol ok goodnight"), partner, at_ms=NOW)

    assert decision.action == "defer"
    assert decision.priority_score < 0.1


def test_urgent_wording_alone_does_not_interrupt_from_a_stranger() -> None:
    policy = NotificationPolicy()
    decision = policy.analyze(event("EMERGENCY! call me right now"), stranger(), at_ms=NOW)
    assert decision.action != "interrupt"


def test_same_message_ranks_by_sender() -> None:
    policy = NotificationPolicy()
    message = event("please call me, it's urgent")
    assert score(policy, message, close_friend()) > score(policy, message, stranger())


# --- escalation and calls ---------------------------------------------------


def test_repetition_carries_a_message_with_no_urgent_words() -> None:
    policy = NotificationPolicy()
    profile = close_friend()
    quiet = policy.analyze(event("are you awake"), profile, EscalationSignal(), at_ms=NOW)
    burst = policy.analyze(
        event("are you awake"),
        profile,
        EscalationSignal(score=0.75, burst_count=4),
        at_ms=NOW,
    )

    assert burst.priority_score > quiet.priority_score
    assert burst.action == "interrupt"


def test_repeated_calls_open_the_override_for_unknown_numbers() -> None:
    policy = NotificationPolicy()
    signal = EscalationSignal(score=1.0, burst_count=5, call_count=5, override_factor=1.0)
    decision = policy.analyze(
        event("", sender_id="unknown", is_missed_call=True),
        stranger(),
        signal,
        at_ms=NOW,
    )

    assert decision.action == "interrupt"
    assert decision.components["override"] > 0.0


def test_single_call_from_unknown_number_does_not_interrupt() -> None:
    policy = NotificationPolicy()
    decision = policy.analyze(
        event("", sender_id="unknown", is_missed_call=True),
        stranger(),
        EscalationSignal(call_count=1),
        at_ms=NOW,
    )
    assert decision.action != "interrupt"


# --- groups, mutes, noise ---------------------------------------------------


def test_group_message_without_mention_is_damped() -> None:
    policy = NotificationPolicy()
    profile = close_friend()
    direct = score(policy, event("this is urgent"), profile)
    group = score(policy, event("this is urgent", is_group=True), profile)
    mentioned = score(policy, event("this is urgent", is_group=True, mentions_user=True), profile)

    assert group < direct
    assert mentioned == direct


def test_muted_sender_is_held_back_one_step() -> None:
    policy = NotificationPolicy()
    decision = policy.analyze(
        event("emergency please help me right now"),
        close_friend(muted=True),
        at_ms=NOW,
    )
    assert decision.action == "show_silently"
    assert decision.suppressed_by == "muted"


def test_muted_sender_can_still_reach_the_override() -> None:
    policy = NotificationPolicy()
    decision = policy.analyze(
        event("", is_missed_call=True),
        close_friend(muted=True),
        EscalationSignal(score=1.0, call_count=4, override_factor=1.0),
        at_ms=NOW,
    )
    assert decision.action == "interrupt"


def test_ongoing_and_summary_notifications_are_dropped() -> None:
    policy = NotificationPolicy()
    for kwargs in ({"is_ongoing": True}, {"is_group_summary": True}):
        decision = policy.analyze(event("emergency", **kwargs), close_friend(), at_ms=NOW)
        assert decision.action == "defer"
        assert decision.suppressed_by == "non_conversational"


# --- context ----------------------------------------------------------------


def test_context_damps_but_cannot_block_a_real_emergency() -> None:
    policy = NotificationPolicy()
    message = "I'm at the hospital, please call me"
    calm = policy.analyze(
        event(message, context=UserContext(time_of_day="day")), close_friend(), at_ms=NOW
    )
    busy = policy.analyze(
        event(message, context=UserContext(time_of_day="sleep", driving=True, calendar_busy=True)),
        close_friend(),
        at_ms=NOW,
    )

    assert busy.priority_score < calm.priority_score
    assert calm.action == "interrupt"


def test_thresholds_are_configurable() -> None:
    strict = NotificationPolicy(PolicyConfig(interrupt_threshold=0.95))
    decision = strict.analyze(event("I really need help, please call me"), close_friend(), at_ms=NOW)
    assert decision.action != "interrupt"
