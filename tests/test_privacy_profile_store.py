from pathlib import Path

from attentionai import JsonProfileStore
from attentionai.models import InteractionProfile


def test_profile_store_hashes_sender_id(tmp_path: Path) -> None:
    store_path = tmp_path / "profiles.json"
    store = JsonProfileStore(store_path, hash_sender_id=True)

    profile = InteractionProfile(sender_id="friend@example.com")
    store.save(profile)

    loaded = store.get("friend@example.com")
    assert loaded is not None
    assert loaded.sender_id != "friend@example.com"
    assert store_path.exists()


def test_profile_store_does_not_save_plain_sender_ids_when_hashed(tmp_path: Path) -> None:
    store_path = tmp_path / "profiles.json"
    store = JsonProfileStore(store_path, hash_sender_id=True)

    profile = InteractionProfile(sender_id="friend@example.com")
    store.save(profile)

    raw_data = store_path.read_text(encoding="utf-8")
    assert "friend@example.com" not in raw_data
