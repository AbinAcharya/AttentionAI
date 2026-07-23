from attentionai.models import InteractionProfile, NotificationEvent, UserContext
from attentionai.policy import NotificationPolicy


def test_urgent_message_overrides_low_relationship() -> None:
    policy = NotificationPolicy()
    event = NotificationEvent(
        app_name="WhatsApp",
        sender_id="friend",
        content="Bhai emergency hai, please call me",
        context=UserContext(time_of_day="day", location_category="office", calendar_busy=True),
    )
    profile = InteractionProfile(sender_id="friend", relationship_score=0.2, tier=4, last_interaction_days=1000)

    decision = policy.analyze(event, profile)

    assert decision.action == "interrupt"
    assert decision.priority_score >= 0.75


def test_casual_message_with_low_relationship_defers() -> None:
    policy = NotificationPolicy()
    event = NotificationEvent(
        app_name="Instagram",
        sender_id="stranger",
        content="Hey, how are you?",
        context=UserContext(time_of_day="day", location_category="office", calendar_busy=False),
    )
    profile = InteractionProfile(sender_id="stranger", relationship_score=0.1, tier=4, last_interaction_days=30)

    decision = policy.analyze(event, profile)

    assert decision.action == "defer"
    assert decision.priority_score < 0.45
