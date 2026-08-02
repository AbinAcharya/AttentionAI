# AttentionAI

A privacy-first Python module for personalized, context-aware notification prioritization.

## What is included
- A reusable package for modeling notifications, user context, and interaction history
- A policy engine that decides whether a notification should interrupt, show silently, or defer
- Tests covering urgent vs. casual notification behavior

## Project structure
- attentionai/ — reusable core module
- tests/ — behavior-focused tests
- docs/PROJECT_REFERENCE.md — project overview and architecture notes

## Install locally
```bash
pip install -e .
```

## Run the tests
```bash
python -m pytest -q
```

## Run the package
After installing locally with:
```bash
pip install -e .
```

Run the CLI directly:
```bash
python -m attentionai
```

Or, when installed, run the script:
```bash
attentionai
```

## Example usage
```python
from pathlib import Path

from attentionai import (
    AttentionAIEngine,
    DictNotificationAdapter,
    JsonProfileStore,
    NotificationPolicyConfig,
    NotificationPolicy,
    sanitize_event,
)

store = JsonProfileStore(Path("./profiles.json"), hash_sender_id=True)
policy = NotificationPolicy(config=NotificationPolicyConfig())
engine = AttentionAIEngine(policy=policy, profile_store=store)

payload = {
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

decision = engine.process(payload, adapter=DictNotificationAdapter())
print(decision.to_dict())
print(engine.get_profile("friend@example.com").to_dict())
print(sanitize_event(payload))
```

## Intended use
This module is designed to be imported by other systems that need notification prioritization logic.
It does not require a standalone app shell.

## Next steps
1. Add a pluggable input adapter for notification sources
2. Integrate multilingual urgency detection
3. Add a local learning loop from user feedback
4. Expose more configuration for custom policies
