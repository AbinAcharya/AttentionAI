"""Content urgency extraction.

Replaces the old ``"help" in text`` substring scan, which fired on "helpful" and
"unhelpful", scored a bare "now" at 0.7, and had no idea that "no emergency, just
checking in" is the opposite of an emergency.

Everything here is deterministic and offline. No model, no network, no message text
leaves the function.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

__all__ = [
    "DEFAULT_URGENCY_TERMS",
    "DEFAULT_SPAM_TERMS",
    "DEFAULT_NEGATORS",
    "UrgencyConfig",
    "UrgencySignal",
    "score_text",
]

# Phrase -> urgency weight in [0, 1]. Multi-word phrases are matched as units.
# Romanised Hindi/Hinglish is included because that is how a lot of real
# "pick up the phone" traffic is actually written.
DEFAULT_URGENCY_TERMS: Dict[str, float] = {
    # unambiguous crisis
    "emergency": 1.0,
    "ambulance": 1.0,
    "accident": 0.95,
    "hospital": 0.9,
    "icu": 0.95,
    "police": 0.9,
    "fire": 0.85,
    "bleeding": 0.95,
    "collapsed": 0.95,
    "passed away": 1.0,
    "in the hospital": 0.95,
    "life threatening": 1.0,
    # direct demands for attention
    "call me": 0.85,
    "call me back": 0.9,
    "pick up": 0.85,
    "answer your phone": 0.9,
    "are you awake": 0.7,
    "you there": 0.55,
    "need you": 0.75,
    "i need help": 0.9,
    "need your help": 0.85,
    "please help": 0.9,
    "help me": 0.9,
    "sos": 1.0,
    # time pressure
    "urgent": 0.8,
    "urgently": 0.8,
    "asap": 0.75,
    "right now": 0.7,
    "immediately": 0.75,
    "as soon as possible": 0.7,
    "deadline": 0.5,
    "last chance": 0.35,
    # romanised hindi / hinglish
    "madad": 0.9,
    "jaldi": 0.7,
    "turant": 0.8,
    "zaroori": 0.7,
    "bahut zaroori": 0.85,
    "hospital hai": 0.95,
    "emergency hai": 1.0,
    # devanagari
    "आपातकाल": 1.0,
    "मदद": 0.9,
    "जल्दी": 0.7,
    # standalone words that are only mildly informative
    "help": 0.6,
    "please": 0.15,
    "important": 0.4,
    "problem": 0.35,
    "worried": 0.45,
    "scared": 0.6,
}

# Marketing vocabulary. Presence actively *lowers* urgency: legitimate emergencies
# do not come with an offer code.
DEFAULT_SPAM_TERMS: Dict[str, float] = {
    "offer": 0.5,
    "discount": 0.6,
    "sale": 0.5,
    "cashback": 0.7,
    "claim": 0.6,
    "prize": 0.8,
    "winner": 0.8,
    "lottery": 0.9,
    "coupon": 0.6,
    "subscribe": 0.5,
    "unsubscribe": 0.7,
    "limited time": 0.6,
    "click here": 0.7,
    "verify your account": 0.8,
    "otp": 0.4,
    "loan": 0.6,
    "credit card": 0.5,
}

# Tokens that flip the meaning of an urgency term appearing shortly after them.
DEFAULT_NEGATORS = frozenset({
    "no", "not", "nope", "never", "nothing", "isnt", "isn't", "arent", "aren't",
    "wasnt", "wasn't", "dont", "don't", "doesnt", "doesn't", "cant", "can't",
    "nvm", "nevermind", "false", "just", "only", "kidding", "jk", "joking",
})

NEGATION_WINDOW_TOKENS = 4
NEGATION_DISCOUNT = 0.25

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


@dataclass
class UrgencySignal:
    """Result of scanning one message body."""

    score: float
    matched: List[str] = field(default_factory=list)
    negated: List[str] = field(default_factory=list)
    spam_penalty: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "score": self.score,
            "matched": list(self.matched),
            "negated": list(self.negated),
            "spam_penalty": self.spam_penalty,
        }


@dataclass
class UrgencyConfig:
    terms: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_URGENCY_TERMS))
    spam_terms: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SPAM_TERMS))
    negators: frozenset = DEFAULT_NEGATORS
    shouting_bonus: float = 0.10
    exclamation_bonus: float = 0.05
    question_bonus: float = 0.05
    spam_damping: float = 0.75
    floor: float = 0.05
    ceiling: float = 1.0


def _tokenize(text: str) -> List[str]:
    return _WORD_RE.findall(text.lower())


def _phrase_positions(tokens: List[str], phrase_tokens: List[str]) -> List[int]:
    """Token indices where ``phrase_tokens`` occurs as a contiguous run."""
    if not phrase_tokens or len(phrase_tokens) > len(tokens):
        return []
    hits: List[int] = []
    first = phrase_tokens[0]
    span = len(phrase_tokens)
    for index, token in enumerate(tokens):
        if token == first and tokens[index:index + span] == phrase_tokens:
            hits.append(index)
    return hits


def _is_negated(tokens: List[str], position: int, negators: frozenset) -> bool:
    start = max(0, position - NEGATION_WINDOW_TOKENS)
    return any(token in negators for token in tokens[start:position])


def _shouting_ratio(text: str) -> float:
    letters = [character for character in text if character.isalpha()]
    if len(letters) < 6:
        return 0.0
    upper = sum(1 for character in letters if character.isupper())
    return upper / len(letters)


def score_text(content: Optional[str], config: Optional[UrgencyConfig] = None) -> UrgencySignal:
    """Score how strongly a message body asks for immediate attention."""
    config = config or UrgencyConfig()
    text = (content or "").strip()
    if not text:
        return UrgencySignal(score=config.floor)

    tokens = _tokenize(text)
    if not tokens:
        return UrgencySignal(score=config.floor)

    best = 0.0
    matched: List[str] = []
    negated: List[str] = []

    for phrase, weight in config.terms.items():
        phrase_tokens = _tokenize(phrase)
        positions = _phrase_positions(tokens, phrase_tokens)
        if not positions:
            continue
        # A phrase counts at full weight if it appears at least once un-negated.
        if any(not _is_negated(tokens, position, config.negators) for position in positions):
            matched.append(phrase)
            best = max(best, weight)
        else:
            negated.append(phrase)
            best = max(best, weight * NEGATION_DISCOUNT)

    if best > 0.0:
        if _shouting_ratio(text) >= 0.6:
            best += config.shouting_bonus
        if "!!" in text or text.count("!") >= 2:
            best += config.exclamation_bonus
        if "?" in text:
            best += config.question_bonus

    spam_penalty = 0.0
    for phrase, weight in config.spam_terms.items():
        if _phrase_positions(tokens, _tokenize(phrase)):
            spam_penalty = max(spam_penalty, weight)

    if spam_penalty > 0.0:
        best *= 1.0 - config.spam_damping * spam_penalty

    score = max(config.floor, min(config.ceiling, best))
    return UrgencySignal(
        score=score,
        matched=sorted(matched),
        negated=sorted(negated),
        spam_penalty=spam_penalty,
    )
