from attentionai import NotificationPolicy, NotificationPolicyConfig
from attentionai.models import InteractionProfile, NotificationEvent, UserContext


def test_custom_policy_config_changes_thresholds() -> None:
    config = NotificationPolicyConfig(interrupt_threshold=0.5, show_silently_threshold=0.2)
    policy = NotificationPolicy(config=config)

    event = NotificationEvent(
        app_name="WhatsApp",
        sender_id="friend",
        content="Urgent help needed now",
        context=UserContext(time_of_day="day", location_category="office", calendar_busy=False),
    )
    profile = InteractionProfile(sender_id="friend", relationship_score=0.1, tier=5, last_interaction_days=10)

    decision = policy.analyze(event, profile)

    assert decision.action == "interrupt"
    assert decision.priority_score >= 0.5


def test_policy_uses_custom_keywords() -> None:
    config = NotificationPolicyConfig(urgency_keywords={"ping": 0.9})
    policy = NotificationPolicy(config=config)

    event = NotificationEvent(
        app_name="TestApp",
        sender_id="user",
        content="Please ping me ASAP",
        context=UserContext(),
    )
    profile = InteractionProfile(sender_id="user")

    decision = policy.analyze(event, profile)

    assert decision.action == "interrupt"
