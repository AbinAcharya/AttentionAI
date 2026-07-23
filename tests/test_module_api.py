from pathlib import Path

from attentionai import AttentionAIEngine, DictNotificationAdapter, JsonProfileStore, UserContext


def test_engine_processes_payload_and_persists_profile(tmp_path: Path) -> None:
    store_path = tmp_path / "profiles.json"
    engine = AttentionAIEngine(profile_store=JsonProfileStore(store_path))

    payload = {
        "app_name": "WhatsApp",
        "sender_id": "friend",
        "content": "Bhai emergency hai, please call me",
        "context": {
            "time_of_day": "day",
            "location_category": "office",
            "calendar_busy": True,
        },
    }

    decision = engine.process(payload, adapter=DictNotificationAdapter())

    assert decision.action == "interrupt"
    assert engine.get_profile("friend") is not None
    assert store_path.exists()


def test_engine_can_load_existing_profile(tmp_path: Path) -> None:
    store_path = tmp_path / "profiles.json"
    engine = AttentionAIEngine(profile_store=JsonProfileStore(store_path))

    profile = engine.get_profile("friend")
    assert profile is None

    engine.process(
        {
            "app_name": "WhatsApp",
            "sender_id": "friend",
            "content": "Hey, how are you?",
            "context": {"time_of_day": "day", "location_category": "office"},
        },
        adapter=DictNotificationAdapter(),
    )

    engine2 = AttentionAIEngine(profile_store=JsonProfileStore(store_path))
    loaded_profile = engine2.get_profile("friend")

    assert loaded_profile is not None
    assert loaded_profile.sender_id == "friend"
