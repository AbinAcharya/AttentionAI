"""Keep the Kotlin engine's test corpus in sync with the Python reference.

The file ``shared/scenarios.json`` is the single behavioural contract between the
Python reference engine (``attentionai/``) and the Kotlin engine that ships in the
Android app. Both run the same cases and must produce the same actions.

The Kotlin test reads a *copy* at ``android/app/src/test/resources/scenarios.json``,
because Android unit tests cannot reference files outside the module -- see
``android/app/src/test/java/com/attentionai/Corpus.kt``. That copy must therefore be
kept byte-identical to the shared original.

Run this after editing the corpus:

    python tools/sync_corpus.py

Exit code is 0 on success, 1 if the source is missing or the copy fails.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "shared" / "scenarios.json"
DEST = ROOT / "android" / "app" / "src" / "test" / "resources" / "scenarios.json"


def main() -> int:
    if not SOURCE.exists():
        print(f"sync_corpus: missing source {SOURCE}", file=sys.stderr)
        return 1

    DEST.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(SOURCE, DEST)
    except OSError as error:
        print(f"sync_corpus: failed to copy {SOURCE} -> {DEST}: {error}", file=sys.stderr)
        return 1

    if not SOURCE.read_bytes() == DEST.read_bytes():
        print("sync_corpus: copy succeeded but bytes differ (unexpected)", file=sys.stderr)
        return 1

    print(f"sync_corpus: {SOURCE} -> {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())