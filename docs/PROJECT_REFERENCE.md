# AttentionAI Project Reference

## Problem
Smartphones treat every notification as equally urgent. That creates focus loss, fatigue, and context-blind interruptions.

## Solution
AttentionAI is a reusable module that decides whether a notification should interrupt the user right now by combining message content, sender relationship, and live context while keeping all inference on-device.

## Core architecture
1. Capture notification preview
2. Extract urgency from text
3. Gather contextual signals
4. Use personal history and relationship profile
5. Decide whether to interrupt, defer, or silence
6. Learn from user feedback

## Privacy-first design
- Process notification previews on-device
- Never store raw message content
- Keep only hashed sender IDs and numeric features
- Allow local profile reset
