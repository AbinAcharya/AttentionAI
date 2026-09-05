"""Smoke tests for the ``python -m attentionai`` command line entry point."""

import json
import sys
from pathlib import Path

import pytest

from attentionai import __main__ as cli


def _run(*argv: str) -> int:
    """Run main() with the given argv, returning the exit code."""
    old = sys.argv
    sys.argv = ["attentionai", *argv]
    try:
        return cli.main()
    finally:
        sys.argv = old


def test_eval_runs(capsys) -> None:
    code = _run("eval")
    out = capsys.readouterr().out
    assert "scenarios passed" in out
    assert "missed interrupts" in out
    assert code in (0, 1)


def test_eval_exits_zero_when_all_pass(capsys) -> None:
    # The corpus is the contract; it should be green in CI.
    code = _run("eval")
    assert code == 0


def test_decide_runs_without_payload(tmp_path: Path, capsys) -> None:
    profile_path = tmp_path / "profiles.json"
    code = _run("decide", "--profile-store", str(profile_path))
    out = capsys.readouterr().out
    assert "Decision:" in out
    assert code == 0
    # A profile file should now exist on disk.
    assert profile_path.exists()


def test_decide_reads_payload_file(tmp_path: Path, capsys) -> None:
    payload = {
        "app_name": "WhatsApp",
        "sender_id": "friend@example.com",
        "content": "emergency, call me back",
    }
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    code = _run("decide", "--profile-store", str(tmp_path / "p.json"), str(payload_path))
    out = capsys.readouterr().out
    assert "Decision:" in out
    assert code == 0


def test_decide_stdin_works(tmp_path: Path, capsys, monkeypatch) -> None:
    import io

    payload = {"app_name": "a", "sender_id": "b", "content": "hi"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = _run("decide", "-", "--profile-store", str(tmp_path / "p.json"))
    out = capsys.readouterr().out
    assert "Decision:" in out
    assert code == 0


def test_explain_outputs_urgency_json(capsys) -> None:
    code = _run("explain", "emergency help")
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "score" in parsed
    assert "matched" in parsed
    assert parsed["score"] >= 0.9
    assert code == 0


def test_no_command_defaults_to_eval(capsys) -> None:
    code = _run()
    out = capsys.readouterr().out
    assert "scenarios passed" in out
    assert code == 0