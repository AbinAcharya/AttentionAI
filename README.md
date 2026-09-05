# AttentionAI

On-device, privacy-first notification prioritisation. An Android app decides whether
each incoming message deserves to interrupt Do Not Disturb, based on what the message
says, who sent it, and what you are doing.

There are **two implementations of the same engine**, held to a single shared corpus:

- **`attentionai/`** — the Python reference engine (what this README's `python -m`
  commands run).
- **`android/`** — the Kotlin engine that ships in the Android app.

Both read `shared/scenarios.json` and must produce the same decision for every
scenario. That corpus is the behavioural contract that keeps the two from drifting
apart.

## How it decides

For each notification the engine produces one of three actions:

| Action | Meaning |
|---|---|
| `interrupt` | Break through DND and alert now (audible breakthrough). |
| `show_silently` | Show as a normal notification, no breakthrough. |
| `defer` | Do nothing. |

The score is **multiplicative** — `need × affinity × context` — so a beloved contact
saying "lol ok" at 3am stays quiet, while a genuine emergency from almost anyone gets
through:

- `need` — what the message demands: urgency vocabulary, retry/burst detection, missed
  calls, @-mentions in group chats.
- `affinity` — how much this sender is allowed to demand attention: learned relationship
  score, tier, open rate, plus a *reunion* bump for old friends resurfacing after a long
  silence (gated so dormant strangers get nothing).
- `context` — your situation: time of day, driving, meeting, battery, DND.

If the message carries **critical wording** — an un-negated "help", "emergency", "sos"
(or the romanised-Hindi/Devanagari equivalents) — affinity is bypassed entirely and the
message interrupts from anyone, even an unknown number or a muted sender. That mirrors
the existing repeated-calls override; ambiguous words ("urgent", "police", "fire",
"hospital") are deliberately excluded so normal and automated traffic does not trip it.

Anything that clears the threshold still has to pass the **interrupt budget** — an
hourly cap, a per-sender cooldown, and duplicate suppression — unless its score is high
enough to count as a real emergency.

Everything is deterministic and offline. Message text is scored in memory and dropped;
it is never logged, stored, or sent anywhere.

## Repository layout

```
attentionai/            Python reference engine
  policy.py             need × affinity × context scoring + thresholds
  urgency.py            urgency lexicon (incl. Hinglish / Devanagari), negation, spam
  escalation.py         burst / retry / repeated-call detection
  budget.py             hourly cap, per-sender cooldown, de-dup
  models.py             InteractionProfile, NotificationEvent, Decision
  api.py                engine wiring + thread-safe JSON profile store
  privacy.py            salted per-install hashing of sender ids
  corpus.py             scenario loader / runner / report
  __main__.py           CLI: eval / decide / explain
android/                Android app (Kotlin engine, service + Compose UI)
  app/src/main/java/com/attentionai/
    core/               policy, urgency, escalation, budget, models, privacy
    service/            NotificationListenerService, breakthrough, context provider
    data/               profile store, settings, contact directory, decision log
    ui/                 setup + home screen
tests/                  Python tests (incl. the end-to-end smoke suite)
shared/scenarios.json   the single parity contract (Python + Kotlin)
tools/sync_corpus.py    copies the corpus into the Android test resources
```

## Python reference engine

Requires Python ≥ 3.10.

```bash
pip install -e .
python -m pytest -q          # all tests
python -m mypy attentionai   # type checks
python -m attentionai eval   # run the shared scenario corpus (18/18 should pass)
```

The CLI also has:

```bash
python -m attentionai decide payload.json   # score one notification payload
python -m attentionai explain "call me"     # inspect urgency extraction
```

Example library use:

```python
from attentionai import AttentionEngine, DictNotificationAdapter, JsonProfileStore

store = JsonProfileStore("./profiles.json")   # sender ids hashed, salt kept per-install
engine = AttentionEngine(profile_store=store)

decision = engine.process({
    "app_name": "WhatsApp",
    "sender_id": "friend@example.com",
    "content": "Bhai emergency hai, please call me",
})
print(decision.action, decision.priority_score)   # interrupt 0.9...
```

## The parity workflow

`shared/scenarios.json` is the contract. The Android unit test reads a **copy** at
`android/app/src/test/resources/scenarios.json` (unit tests can't reach outside the
module). Keep them in sync by hand or, after editing the corpus:

```bash
python tools/sync_corpus.py
```

When you change the corpus, run both sides and commit both copies together:

```bash
python -m attentionai eval                    # Python side
cd android && ./gradlew testDebugUnitTest     # Kotlin side (CorpusTest)
```

## Android app

The app runs a `NotificationListenerService` that reads notifications, scores them with
the Kotlin engine, and re-posts the ones that earn a breakthrough on a DND-bypassing
channel. It does **not** un-suppress another app's notification — it mirrors the message
as its own notification; tapping it opens the original conversation.

### Build & install

Build in Android Studio (File → Open → this repo's `android/` dir), or from a terminal
with the Android SDK and a JDK 17+:

```bash
cd android
./gradlew testDebugUnitTest   # CorpusTest / PolicyTest / UrgencyTest
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

### On-phone setup (one time)

1. Open the app. The setup card lists the permissions:
   - **Notification access** — required to read incoming notifications.
   - **Do Not Disturb access** — required for a breakthrough to actually sound during
     DND. Open System Settings → Notifications → Do Not Disturb → set *Calls and
     notifications* to allow from this app. Without this grant the app runs but stays
     silent.
   - **Post notifications** — the app posts the breakthrough itself.
   - **Contacts** (optional) — gives brand-new senders a sensible starting priority.
2. Turn on Do Not Disturb.
3. Send yourself a message. If it reads as urgent, it should break through.
4. The home screen has a **Send test breakthrough** button to verify end to end.

### Privacy guarantees

- Nothing leaves the device: no network permission in the manifest.
- Message text is never written anywhere (see the "Recent decisions" note in-app).
- Sender identities are salted-hashed per install; `profiles.json` and all other learned
  state are excluded from cloud backup and device transfer
  (`res/xml/data_extraction_rules.xml`).
- "Reset learned data" clears profiles and rotates the hash salt.

## License / scope note

This is a personal project. The corpus, thresholds, and lexicon are intentionally small
and hand-curated; the machine learning is a local learning loop from your own behaviour,
not a trained model.