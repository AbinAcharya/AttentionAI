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

## Intended use
This module is designed to be imported by other systems that need notification prioritization logic.
It does not require a standalone app shell.

## Next steps
1. Add a pluggable input adapter for notification sources
2. Integrate multilingual urgency detection
3. Add a local learning loop from user feedback
4. Expose more configuration for custom policies
