"""Command line entry point.

    python -m attentionai eval            # run the shared scenario corpus
    python -m attentionai decide payload.json
    python -m attentionai explain "text"  # inspect urgency extraction
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, cast

from .api import AttentionEngine, DictNotificationAdapter, JsonProfileStore
from .corpus import format_report, run_corpus
from .policy import NotificationPolicy, PolicyConfig
from .privacy import sanitize_event
from .urgency import score_text


def _sample_payload() -> Dict[str, Any]:
    return {
        "app_name": "WhatsApp",
        "sender_id": "friend@example.com",
        "sender_name": "Raj",
        "content": "Please call me ASAP, it's urgent",
        "context": {
            "time_of_day": "night",
            "location_category": "home",
            "dnd_active": True,
            "battery_level": 85,
        },
    }


def _load_payload(source: str | None) -> Dict[str, Any]:
    if source is None:
        return _sample_payload()
    if source == "-":
        return cast(Dict[str, Any], json.load(sys.stdin))
    with Path(source).open("r", encoding="utf-8") as handle:
        return cast(Dict[str, Any], json.load(handle))


def _cmd_eval(args: argparse.Namespace) -> int:
    results = run_corpus(NotificationPolicy(PolicyConfig()), args.corpus)
    print(format_report(results, verbose=args.verbose))
    return 0 if all(result.passed for result in results) else 1


def _cmd_decide(args: argparse.Namespace) -> int:
    payload = _load_payload(args.payload)
    store = JsonProfileStore(args.profile_store, hash_sender_id=not args.no_hash)
    engine = AttentionEngine(policy=NotificationPolicy(), profile_store=store)
    decision = engine.process(payload, adapter=DictNotificationAdapter())

    print("Decision:")
    print(json.dumps(decision.to_dict(), indent=2))
    print("\nStored profile:")
    profile = engine.get_profile(str(payload.get("sender_id", "")))
    print(json.dumps(profile.to_dict(), indent=2) if profile else "none")
    print("\nWhat would be persisted from this event:")
    print(json.dumps(sanitize_event(payload, store.salt), indent=2))
    return 0


def _cmd_explain(args: argparse.Namespace) -> int:
    print(json.dumps(score_text(args.text).to_dict(), indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="attentionai", description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    evaluate = subparsers.add_parser("eval", help="run the shared scenario corpus")
    evaluate.add_argument("--corpus", type=Path, default=None)
    evaluate.add_argument("-v", "--verbose", action="store_true")
    evaluate.set_defaults(func=_cmd_eval)

    decide = subparsers.add_parser("decide", help="score one notification payload")
    decide.add_argument("payload", nargs="?", help="JSON file, or '-' for stdin")
    decide.add_argument("--profile-store", default="profiles.json")
    decide.add_argument("--no-hash", action="store_true")
    decide.set_defaults(func=_cmd_decide)

    explain = subparsers.add_parser("explain", help="show urgency extraction for a string")
    explain.add_argument("text")
    explain.set_defaults(func=_cmd_explain)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        args = parser.parse_args(["eval"])
    result = cast(Any, args.func)(args)
    return int(result if result is not None else 0)


if __name__ == "__main__":
    raise SystemExit(main())
