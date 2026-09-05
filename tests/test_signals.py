from attentionai.budget import BudgetConfig, InterruptBudget
from attentionai.escalation import EscalationConfig, EscalationTracker

NOW = 1_767_225_600_000
MINUTE = 60_000


# --- escalation -------------------------------------------------------------


def test_first_message_is_not_escalation() -> None:
    tracker = EscalationTracker()
    assert tracker.record("a", NOW).score == 0.0


def test_burst_raises_the_score() -> None:
    tracker = EscalationTracker()
    scores = [tracker.record("a", NOW + index * 10_000).score for index in range(5)]
    assert scores == sorted(scores)
    assert scores[-1] > 0.5


def test_calls_count_more_than_messages() -> None:
    messages = EscalationTracker()
    calls = EscalationTracker()
    for index in range(3):
        message_score = messages.record("a", NOW + index * 10_000).score
        call_score = calls.record("a", NOW + index * 10_000, is_call=True).score
    assert call_score > message_score


def test_repeated_calls_trigger_the_override() -> None:
    tracker = EscalationTracker()
    signals = [tracker.record("a", NOW + index * 30_000, is_call=True) for index in range(5)]
    assert signals[0].override_factor == 0.0
    assert signals[2].override_factor > 0.0
    assert signals[4].override_factor >= signals[2].override_factor


def test_events_outside_the_window_are_forgotten() -> None:
    tracker = EscalationTracker(EscalationConfig(window_ms=10 * MINUTE))
    tracker.record("a", NOW)
    tracker.record("a", NOW + MINUTE)
    assert tracker.record("a", NOW + 60 * MINUTE).score == 0.0


def test_senders_are_tracked_independently() -> None:
    tracker = EscalationTracker()
    for index in range(4):
        tracker.record("noisy", NOW + index * 1000)
    assert tracker.record("quiet", NOW).score == 0.0


def test_reset_clears_state() -> None:
    tracker = EscalationTracker()
    for index in range(4):
        tracker.record("a", NOW + index * 1000)
    tracker.reset("a")
    assert tracker.peek("a", NOW).score == 0.0


# --- budget -----------------------------------------------------------------


def test_hourly_cap_is_enforced() -> None:
    budget = InterruptBudget(BudgetConfig(max_interrupts_per_window=2))
    for index in range(2):
        sender = f"s{index}"
        assert budget.check(sender, 0.8, NOW + index * MINUTE).allowed
        budget.commit(sender, NOW + index * MINUTE)

    verdict = budget.check("s3", 0.8, NOW + 5 * MINUTE)
    assert not verdict.allowed
    assert verdict.reason == "hourly_budget_exhausted"


def test_budget_refills_after_the_window() -> None:
    budget = InterruptBudget(BudgetConfig(max_interrupts_per_window=1))
    budget.commit("a", NOW)
    assert not budget.check("b", 0.8, NOW + MINUTE).allowed
    assert budget.check("b", 0.8, NOW + 61 * MINUTE).allowed


def test_per_sender_cooldown() -> None:
    budget = InterruptBudget(BudgetConfig(per_sender_cooldown_ms=10 * MINUTE))
    budget.commit("a", NOW)
    assert budget.check("a", 0.8, NOW + 2 * MINUTE).reason == "sender_cooldown"
    assert budget.check("a", 0.8, NOW + 11 * MINUTE).allowed


def test_high_scores_bypass_cooldown_and_cap() -> None:
    """A real emergency must not be rate-limited because two other things got in."""
    budget = InterruptBudget(BudgetConfig(max_interrupts_per_window=1, bypass_score=0.9))
    budget.commit("a", NOW)
    assert not budget.check("a", 0.85, NOW + MINUTE).allowed
    assert budget.check("a", 0.95, NOW + MINUTE).allowed


def test_duplicate_notifications_are_suppressed() -> None:
    budget = InterruptBudget()
    budget.commit("a", NOW, dedup_key="thread-1")
    verdict = budget.check("a", 0.95, NOW + MINUTE, dedup_key="thread-1")
    assert not verdict.allowed
    assert verdict.reason == "duplicate_notification"


def test_duplicates_expire() -> None:
    budget = InterruptBudget(BudgetConfig(duplicate_ttl_ms=5 * MINUTE))
    budget.note_shown("thread-1", NOW)
    assert budget.check("a", 0.95, NOW + 6 * MINUTE, dedup_key="thread-1").allowed


def test_remaining_reports_headroom() -> None:
    budget = InterruptBudget(BudgetConfig(max_interrupts_per_window=3))
    assert budget.remaining(NOW) == 3
    budget.commit("a", NOW)
    assert budget.remaining(NOW) == 2
