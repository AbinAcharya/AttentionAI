"""Loader and runner for the shared scenario corpus.

The corpus at ``shared/scenarios.json`` is the contract between the Python reference
engine and the Kotlin engine that ships in the Android app. Both run the same cases
and must produce the same actions, which is what keeps the two from drifting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "DEFAULT_CORPUS_PATH",
    "Scenario",
    "ScenarioResult",
    "load_corpus",
    "run_corpus",
    "format_report",
]

from .escalation import EscalationSignal
from .models import DEFER, INTERRUPT, SHOW_SILENTLY, MS_PER_DAY, InteractionProfile, NotificationEvent, UserContext
from .policy import NotificationPolicy

DEFAULT_CORPUS_PATH = Path(__file__).resolve().parent.parent / "shared" / "scenarios.json"


@dataclass
class Scenario:
    id: str
    expect: str
    event: NotificationEvent
    profile: InteractionProfile
    escalation: EscalationSignal
    note: str = ""


@dataclass
class ScenarioResult:
    id: str
    expect: str
    actual: str
    score: float
    reasons: List[str] = field(default_factory=list)
    components: Dict[str, float] = field(default_factory=dict)
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.expect == self.actual


def _profile_from(raw: Optional[Dict[str, Any]], now_ms: int) -> InteractionProfile:
    raw = dict(raw or {})
    days_ago = raw.pop("last_seen_days_ago", None)
    if days_ago is not None:
        raw["last_seen_ms"] = now_ms - int(float(days_ago) * MS_PER_DAY)
    raw.setdefault("sender_key", "scenario")
    return InteractionProfile.from_dict(raw)


def _escalation_from(raw: Optional[Dict[str, Any]]) -> EscalationSignal:
    raw = raw or {}
    return EscalationSignal(
        score=float(raw.get("score", 0.0)),
        burst_count=int(raw.get("burst_count", 1)),
        call_count=int(raw.get("call_count", 0)),
        override_factor=float(raw.get("override_factor", 0.0)),
    )


def load_corpus(path: Optional[Path] = None) -> tuple:
    """Return ``(now_ms, [Scenario, ...])``."""
    path = Path(path) if path is not None else DEFAULT_CORPUS_PATH
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if not isinstance(payload, dict):
        raise ValueError(f"Corpus {path}: top level must be a JSON object")
    if "scenarios" not in payload:
        raise ValueError(f"Corpus {path}: missing required 'scenarios' list")
    if not isinstance(payload["scenarios"], list):
        raise ValueError(f"Corpus {path}: 'scenarios' must be a list")

    now_ms = int(payload["now_ms"])
    scenarios: List[Scenario] = []

    for index, raw in enumerate(payload["scenarios"]):
        if not isinstance(raw, dict):
            raise ValueError(f"Corpus {path}: scenario #{index} is not an object")
        scenario_id = raw.get("id", f"<{index}>")

        expected = raw.get("expect")
        if expected not in (INTERRUPT, SHOW_SILENTLY, DEFER):
            raise ValueError(
                f"Corpus {path}: scenario {scenario_id!r} has invalid 'expect' "
                f"{expected!r} (expected one of {INTERRUPT!r}, {SHOW_SILENTLY!r}, {DEFER!r})"
            )

        event_payload = raw.get("event")
        if not isinstance(event_payload, dict):
            raise ValueError(f"Corpus {path}: scenario {scenario_id!r} missing 'event' object")

        event_payload = dict(event_payload)
        event_payload["context"] = raw.get("context") or {}
        scenarios.append(
            Scenario(
                id=scenario_id,
                expect=expected,
                note=raw.get("note", ""),
                event=NotificationEvent.from_dict(event_payload),
                profile=_profile_from(raw.get("profile"), now_ms),
                escalation=_escalation_from(raw.get("escalation")),
            )
        )
    return now_ms, scenarios


def run_corpus(
    policy: Optional[NotificationPolicy] = None,
    path: Optional[Path] = None,
) -> List[ScenarioResult]:
    """Score every scenario with a bare policy (no budget, no tracker state)."""
    policy = policy or NotificationPolicy()
    now_ms, scenarios = load_corpus(path)

    results: List[ScenarioResult] = []
    for scenario in scenarios:
        decision = policy.analyze(
            scenario.event,
            scenario.profile,
            scenario.escalation,
            at_ms=now_ms,
        )
        results.append(
            ScenarioResult(
                id=scenario.id,
                expect=scenario.expect,
                actual=decision.action,
                score=decision.priority_score,
                reasons=decision.reasons,
                components=decision.components,
                note=scenario.note,
            )
        )
    return results


def format_report(results: List[ScenarioResult], verbose: bool = False) -> str:
    """Human-readable pass/fail table plus the two rates that actually matter."""
    lines: List[str] = []
    width = max((len(result.id) for result in results), default=10)

    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        lines.append(
            f"[{mark}] {result.id:<{width}}  expect={result.expect:<13} "
            f"actual={result.actual:<13} score={result.score:.3f}"
        )
        if verbose or not result.passed:
            if result.reasons:
                lines.append(f"         reasons: {', '.join(result.reasons)}")
            if result.components:
                parts = ", ".join(f"{k}={v}" for k, v in sorted(result.components.items()))
                lines.append(f"         {parts}")

    passed = sum(1 for result in results if result.passed)
    total = len(results)

    # Asymmetric costs: missing a real emergency is far worse than one wrong buzz.
    missed_urgent = [
        result for result in results
        if result.expect == "interrupt" and result.actual != "interrupt"
    ]
    false_interrupts = [
        result for result in results
        if result.expect != "interrupt" and result.actual == "interrupt"
    ]

    lines.append("")
    lines.append(f"{passed}/{total} scenarios passed")
    lines.append(f"missed interrupts : {len(missed_urgent)}  {[r.id for r in missed_urgent]}")
    lines.append(f"false interrupts  : {len(false_interrupts)}  {[r.id for r in false_interrupts]}")
    return "\n".join(lines)
