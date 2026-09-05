"""AttentionAI: on-device notification prioritisation.

The reference implementation of the decision engine that ships in the Android app.
Both are validated against ``shared/scenarios.json``.
"""

from .api import (
    FEEDBACK_DEMOTED,
    FEEDBACK_DISMISSED,
    FEEDBACK_OPENED,
    FEEDBACK_OUTBOUND,
    FEEDBACK_PROMOTED,
    FEEDBACK_REPLIED,
    AttentionAIEngine,
    AttentionEngine,
    DictNotificationAdapter,
    JsonProfileStore,
)
from .budget import BudgetConfig, BudgetVerdict, InterruptBudget
from .corpus import format_report, load_corpus, run_corpus
from .escalation import EscalationConfig, EscalationSignal, EscalationTracker
from .models import (
    DEFER,
    INTERRUPT,
    SHOW_SILENTLY,
    Decision,
    InteractionProfile,
    NotificationEvent,
    UserContext,
)
from .policy import NotificationPolicy, NotificationPolicyConfig, PolicyConfig
from .privacy import hash_contact_id, is_hashed, new_salt, sanitize_event
from .urgency import UrgencyConfig, UrgencySignal, score_text

__version__ = "0.2.0"

__all__ = [
    # models
    "Decision",
    "NotificationEvent",
    "UserContext",
    "InteractionProfile",
    "INTERRUPT",
    "SHOW_SILENTLY",
    "DEFER",
    # policy
    "NotificationPolicy",
    "PolicyConfig",
    "NotificationPolicyConfig",
    # signals
    "UrgencyConfig",
    "UrgencySignal",
    "score_text",
    "EscalationTracker",
    "EscalationConfig",
    "EscalationSignal",
    # back-pressure
    "InterruptBudget",
    "BudgetConfig",
    "BudgetVerdict",
    # engine
    "AttentionEngine",
    "AttentionAIEngine",
    "DictNotificationAdapter",
    "JsonProfileStore",
    "FEEDBACK_OPENED",
    "FEEDBACK_DISMISSED",
    "FEEDBACK_REPLIED",
    "FEEDBACK_OUTBOUND",
    "FEEDBACK_PROMOTED",
    "FEEDBACK_DEMOTED",
    # privacy
    "hash_contact_id",
    "is_hashed",
    "new_salt",
    "sanitize_event",
    # eval
    "load_corpus",
    "run_corpus",
    "format_report",
]
