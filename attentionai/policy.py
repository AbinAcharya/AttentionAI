"""The decision policy.

Structural change from v1: the score is **multiplicative**, not a flat weighted sum.

    score = need x affinity x context_factor        (and then max'd with an override)

``need`` is what the message itself demands. ``affinity`` is how much this particular
sender is allowed to demand it. Multiplying means a beloved contact sending "lol ok"
can never break through at 3am, no matter how high their relationship score is --
which the old additive model got wrong, because tier and relationship bonuses stacked
onto the same axis as urgency and could reach the threshold on their own.

The reunion term is the piece that handles "someone who hasn't texted in two years
suddenly needs help":

* it is **multiplied by need**, so silence followed by "happy new year" stays quiet
  while silence followed by "I need help" spikes;
* it is **gated on peak_relationship / lifetime_interactions**, so it only ever
  applies to people who were once actually close. A dormant stranger is just a
  stranger, which is what stops spam from collecting the reunion bonus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = ["PolicyConfig", "NotificationPolicy", "NotificationPolicyConfig"]

from .escalation import EscalationSignal
from .models import (
    DEFER,
    INTERRUPT,
    SHOW_SILENTLY,
    Decision,
    InteractionProfile,
    NotificationEvent,
    UserContext,
    clamp01,
    now_ms,
)
from .urgency import UrgencyConfig, UrgencySignal, score_text


@dataclass
class PolicyConfig:
    # --- bond: how much this sender is allowed to demand attention
    # The first three weights sum to 1; `w_starred` is a bonus on top rather than a
    # slice of the budget, so that a tier-2 contact is not permanently capped below
    # a starred one.
    w_relationship: float = 0.45
    w_tier: float = 0.35
    w_open_rate: float = 0.20
    w_starred: float = 0.10

    # --- affinity assembly
    affinity_base: float = 0.15        # floor, so an unknown sender is not exactly zero
    affinity_bond_weight: float = 0.85
    # Diminishing returns on closeness: past a point, "very close" and "extremely
    # close" should behave the same. Without this, realistic bonds (~0.7) map to
    # affinities too low for a genuine emergency to clear the threshold.
    bond_curve: float = 0.7
    reunion_weight: float = 0.55

    # --- reunion gating
    reunion_min_days: float = 30.0     # below this, no dormancy credit at all
    reunion_full_days: float = 180.0   # at/above this, full dormancy credit
    reunion_peak_threshold: float = 0.5
    reunion_min_lifetime: int = 20

    # --- relationship decay
    relationship_half_life_days: float = 90.0
    relationship_floor: float = 0.15

    # --- context
    context_damping: float = 0.45      # max fraction of score removed by context
    penalty_calendar_busy: float = 0.25
    penalty_meeting: float = 0.30
    penalty_driving: float = 0.35
    # Night penalties are deliberately mild. `need` already suppresses small talk
    # multiplicatively, and 3am is precisely when a real emergency must get through.
    penalty_night: float = 0.12
    penalty_sleep: float = 0.20
    penalty_low_battery: float = 0.10
    low_battery_level: int = 15
    max_context_penalty: float = 0.80

    # --- message kinds
    missed_call_need: float = 0.85     # a missed call is a strong request by itself
    group_without_mention_damping: float = 0.40

    # --- emergency override (repeated calls from anyone, known or not)
    override_enabled: bool = True
    override_max: float = 0.85
    # Critical wording ("help", "emergency", ...) bypasses affinity entirely, so a
    # one-word plea from a stranger still breaks through DND. Only overrides the mute
    # the same way repeated calls do: explicit instructions downgrade, never silence.
    critical_override: float = 0.85

    # --- thresholds
    interrupt_threshold: float = 0.70
    silent_threshold: float = 0.40

    urgency: UrgencyConfig = field(default_factory=UrgencyConfig)


def _tier_weight(tier: int) -> float:
    """Tier 1 -> 1.0, tier 5 -> 0.0."""
    return clamp01((5 - max(1, min(5, tier))) / 4.0)


class NotificationPolicy:
    """Stateless scorer. All state lives in the profile, tracker, and budget."""

    def __init__(self, config: Optional[PolicyConfig] = None) -> None:
        self.config = config or PolicyConfig()

    # ---- public API ----------------------------------------------------------

    def analyze(
        self,
        event: NotificationEvent,
        profile: Optional[InteractionProfile] = None,
        escalation: Optional[EscalationSignal] = None,
        at_ms: Optional[int] = None,
    ) -> Decision:
        config = self.config
        at_ms = at_ms if at_ms is not None else now_ms()
        profile = profile or InteractionProfile(sender_key=event.sender_id)
        escalation = escalation or EscalationSignal()
        context = event.context or UserContext()

        # Media controls, sync bars and group summaries are not conversations.
        if event.is_ongoing or event.is_group_summary:
            return Decision(
                action=DEFER,
                priority_score=0.0,
                reasons=["not a conversational notification"],
                suppressed_by="non_conversational",
            )

        urgency = score_text(event.content, config.urgency)
        need = self._need(event, urgency, escalation)
        bond, bond_parts = self._bond(profile, at_ms)
        reunion = self._reunion(profile, at_ms)
        shaped_bond = bond ** config.bond_curve if bond > 0 else 0.0
        affinity = clamp01(
            config.affinity_base
            + config.affinity_bond_weight * shaped_bond
            + config.reunion_weight * reunion * need
        )
        penalty = self._context_penalty(context)
        context_factor = 1.0 - config.context_damping * penalty

        score = clamp01(need * affinity * context_factor)

        escalation_override = 0.0
        critical_override = 0.0
        critical_hits = [p for p in urgency.matched if p in config.urgency.critical_terms]
        if config.override_enabled:
            if escalation.override_factor > 0.0:
                escalation_override = clamp01(escalation.override_factor * config.override_max)
            if critical_hits:
                critical_override = clamp01(config.critical_override)
        override = max(escalation_override, critical_override)
        score = max(score, override)

        reasons = self._reasons(
            urgency=urgency,
            escalation=escalation,
            profile=profile,
            reunion=reunion,
            penalty=penalty,
            override=escalation_override,
            critical_hits=critical_hits,
            event=event,
            at_ms=at_ms,
        )

        components = {
            "need": round(need, 4),
            "urgency": round(urgency.score, 4),
            "escalation": round(escalation.score, 4),
            "bond": round(bond, 4),
            "reunion": round(reunion, 4),
            "affinity": round(affinity, 4),
            "context_penalty": round(penalty, 4),
            "override": round(override, 4),
            **{key: round(value, 4) for key, value in bond_parts.items()},
        }

        # A muted sender is held back one step: only the emergency override
        # (repeated calls) can still produce a real interrupt.
        if profile.muted:
            if score >= config.interrupt_threshold:
                action = INTERRUPT if override > 0.0 else SHOW_SILENTLY
            else:
                action = DEFER
            return Decision(
                action=action,
                priority_score=score,
                reasons=reasons + ["sender is muted"],
                components=components,
                suppressed_by=None if action == INTERRUPT else "muted",
            )

        return Decision(
            action=self._action_for(score),
            priority_score=score,
            reasons=reasons,
            components=components,
        )

    # ---- scoring pieces ------------------------------------------------------

    def _need(
        self,
        event: NotificationEvent,
        urgency: UrgencySignal,
        escalation: EscalationSignal,
    ) -> float:
        """How strongly the message itself asks for attention.

        Urgency and escalation combine as a probabilistic OR: either alone can carry
        the message, and having both saturates rather than overflows.
        """
        need = urgency.score + escalation.score * (1.0 - urgency.score)

        if event.is_missed_call:
            need = max(need, self.config.missed_call_need)

        if event.is_group and not event.mentions_user:
            need *= self.config.group_without_mention_damping

        return clamp01(need)

    def _bond(self, profile: InteractionProfile, at_ms: int) -> Tuple[float, Dict[str, float]]:
        config = self.config
        relationship = profile.decayed_relationship(
            at_ms,
            half_life_days=config.relationship_half_life_days,
            floor=config.relationship_floor,
        )
        tier = _tier_weight(profile.effective_tier)
        starred = 1.0 if (profile.is_starred or profile.effective_tier == 1) else 0.0

        bond = clamp01(
            config.w_relationship * relationship
            + config.w_tier * tier
            + config.w_open_rate * profile.open_rate
            + config.w_starred * starred
        )
        return bond, {
            "relationship_decayed": relationship,
            "tier_weight": tier,
            "open_rate": profile.open_rate,
            "bond_shaped": bond ** config.bond_curve if bond > 0 else 0.0,
        }

    def _reunion(self, profile: InteractionProfile, at_ms: int) -> float:
        """Dormancy credit, but only for people who were once close.

        Returns a 0..1 ramp. The caller multiplies it by ``need`` so that a long
        silence broken by small talk earns nothing.
        """
        config = self.config
        if not profile.is_established(config.reunion_peak_threshold, config.reunion_min_lifetime):
            return 0.0

        days = profile.days_since_last_seen(at_ms)
        span = config.reunion_full_days - config.reunion_min_days
        if span <= 0:
            return 1.0 if days >= config.reunion_full_days else 0.0
        return clamp01((days - config.reunion_min_days) / span)

    def _context_penalty(self, context: UserContext) -> float:
        config = self.config
        penalty = 0.0
        if context.calendar_busy:
            penalty += config.penalty_calendar_busy
        if context.location_category == "meeting":
            penalty += config.penalty_meeting
        if context.driving:
            penalty += config.penalty_driving
        if context.time_of_day == "sleep":
            penalty += config.penalty_sleep
        elif context.time_of_day == "night":
            penalty += config.penalty_night
        if context.battery_level < config.low_battery_level:
            penalty += config.penalty_low_battery
        # Screen state is deliberately not penalised: during DND the screen is off by
        # definition, and that is exactly when a breakthrough matters most.
        return min(config.max_context_penalty, penalty)

    def _action_for(self, score: float) -> str:
        if score >= self.config.interrupt_threshold:
            return INTERRUPT
        if score >= self.config.silent_threshold:
            return SHOW_SILENTLY
        return DEFER

    def _reasons(
        self,
        urgency: UrgencySignal,
        escalation: EscalationSignal,
        profile: InteractionProfile,
        reunion: float,
        penalty: float,
        override: float,
        critical_hits: List[str],
        event: NotificationEvent,
        at_ms: int,
    ) -> List[str]:
        reasons: List[str] = []
        if critical_hits:
            reasons.append("critical wording (" + ", ".join(critical_hits) + ")")
        if urgency.score >= 0.7:
            reasons.append("message reads as urgent")
        if urgency.negated and urgency.score < 0.4:
            reasons.append("urgent wording appears negated")
        if urgency.spam_penalty >= 0.5:
            reasons.append("promotional wording detected")
        if escalation.score >= 0.4:
            reasons.append(f"repeated contact ({escalation.burst_count} in 10 min)")
        if event.is_missed_call:
            reasons.append("missed call")
        if override > 0.0:
            reasons.append(f"repeated calls ({escalation.call_count})")
        if reunion >= 0.5:
            reasons.append(
                f"close contact resurfacing after {int(profile.days_since_last_seen(at_ms))} days"
                if profile.last_seen_ms
                else "close contact resurfacing"
            )
        if profile.effective_tier <= 2 or profile.is_starred:
            reasons.append("priority contact")
        if event.is_group and not event.mentions_user:
            reasons.append("group message without a mention")
        if penalty >= 0.3:
            reasons.append("context suggests deferring")
        return reasons


# Backwards-compatible alias for the old name.
NotificationPolicyConfig = PolicyConfig
