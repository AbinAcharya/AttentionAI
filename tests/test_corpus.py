"""The shared corpus is the contract between the Python and Kotlin engines."""

import json
from pathlib import Path

import pytest

from attentionai.corpus import DEFAULT_CORPUS_PATH, format_report, load_corpus, run_corpus

ANDROID_COPY = (
    Path(__file__).resolve().parent.parent
    / "android" / "app" / "src" / "test" / "resources" / "scenarios.json"
)


def test_every_scenario_produces_its_expected_action() -> None:
    results = run_corpus()
    failures = [result for result in results if not result.passed]
    assert not failures, "\n" + format_report(results)


def test_no_missed_interrupts() -> None:
    """The expensive direction: a real emergency that never reached the user."""
    results = run_corpus()
    missed = [r.id for r in results if r.expect == "interrupt" and r.actual != "interrupt"]
    assert missed == []


def test_no_false_interrupts() -> None:
    results = run_corpus()
    false = [r.id for r in results if r.expect != "interrupt" and r.actual == "interrupt"]
    assert false == []


def test_corpus_covers_both_reunion_directions() -> None:
    _, scenarios = load_corpus()
    ids = {scenario.id for scenario in scenarios}
    assert {"reunion-emergency", "reunion-small-talk", "dormant-stranger-urgent-words"} <= ids


def test_expectations_use_known_actions() -> None:
    _, scenarios = load_corpus()
    for scenario in scenarios:
        assert scenario.expect in {"interrupt", "show_silently", "defer"}, scenario.id


@pytest.mark.skipif(not ANDROID_COPY.exists(), reason="android module not present")
def test_android_copy_is_in_sync() -> None:
    """If these drift, the app stops behaving like the thing that was tested."""
    source = json.loads(DEFAULT_CORPUS_PATH.read_text(encoding="utf-8"))
    android = json.loads(ANDROID_COPY.read_text(encoding="utf-8"))
    assert source == android, (
        "shared/scenarios.json and the Android test resource have diverged; "
        "re-run: python tools/sync_corpus.py"
    )
