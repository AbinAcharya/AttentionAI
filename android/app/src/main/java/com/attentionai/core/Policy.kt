package com.attentionai.core

/**
 * The decision policy. Port of `attentionai/policy.py`, held to the same corpus.
 *
 * The score is **multiplicative**, not a flat weighted sum:
 *
 *     score = need x affinity x contextFactor        (then max'd with an override)
 *
 * `need` is what the message itself demands. `affinity` is how much this particular
 * sender is allowed to demand it. Multiplying means a beloved contact sending "lol ok"
 * can never break through at 3am no matter how high their relationship score is.
 *
 * The reunion term handles "someone who hasn't texted in two years suddenly needs
 * help": it is multiplied by `need`, so silence followed by small talk stays quiet,
 * and it is gated on `peakRelationship` / `lifetimeInteractions`, so it only applies
 * to people who were once actually close. A dormant stranger is just a stranger --
 * which is what stops spam from collecting the reunion bonus.
 */
data class PolicyConfig(
    // --- bond: how much this sender is allowed to demand attention.
    // The first three weights sum to 1; wStarred is a bonus on top rather than a
    // slice of the budget, so a tier-2 contact is not permanently capped below a
    // starred one.
    val wRelationship: Double = 0.45,
    val wTier: Double = 0.35,
    val wOpenRate: Double = 0.20,
    val wStarred: Double = 0.10,

    // --- affinity assembly
    val affinityBase: Double = 0.15,
    val affinityBondWeight: Double = 0.85,
    /**
     * Diminishing returns on closeness: past a point, "very close" and "extremely
     * close" should behave the same. Without this, realistic bonds (~0.7) map to
     * affinities too low for a genuine emergency to clear the threshold.
     */
    val bondCurve: Double = 0.7,
    val reunionWeight: Double = 0.55,

    // --- reunion gating
    val reunionMinDays: Double = 30.0,
    val reunionFullDays: Double = 180.0,
    val reunionPeakThreshold: Double = 0.5,
    val reunionMinLifetime: Int = 20,

    // --- relationship decay
    val relationshipHalfLifeDays: Double = 90.0,
    val relationshipFloor: Double = 0.15,

    // --- context
    val contextDamping: Double = 0.45,
    val penaltyCalendarBusy: Double = 0.25,
    val penaltyMeeting: Double = 0.30,
    val penaltyDriving: Double = 0.35,
    // Night penalties are deliberately mild: `need` already suppresses small talk
    // multiplicatively, and 3am is precisely when a real emergency must get through.
    val penaltyNight: Double = 0.12,
    val penaltySleep: Double = 0.20,
    val penaltyLowBattery: Double = 0.10,
    val lowBatteryLevel: Int = 15,
    val maxContextPenalty: Double = 0.80,

    // --- message kinds
    val missedCallNeed: Double = 0.85,
    val groupWithoutMentionDamping: Double = 0.40,

    // --- emergency override (repeated calls from anyone, known or not)
    val overrideEnabled: Boolean = true,
    val overrideMax: Double = 0.85,
    // Critical wording ("help", "emergency", ...) bypasses affinity entirely, so a
    // one-word plea from a stranger still breaks through DND. Only overrides the mute
    // the same way repeated calls do: explicit instructions downgrade, never silence.
    val criticalOverride: Double = 0.85,

    // --- thresholds
    val interruptThreshold: Double = 0.70,
    val silentThreshold: Double = 0.40,

    val urgency: UrgencyConfig = UrgencyConfig(),
)

class NotificationPolicy(val config: PolicyConfig = PolicyConfig()) {

    fun analyze(
        event: NotificationEvent,
        profile: SenderProfile? = null,
        escalation: EscalationSignal = EscalationSignal(),
        atMs: Long = System.currentTimeMillis(),
    ): Decision {
        // Media controls, sync bars and group summaries are not conversations.
        if (event.isOngoing || event.isGroupSummary) {
            return Decision(
                action = Action.DEFER,
                priorityScore = 0.0,
                reasons = listOf("not a conversational notification"),
                suppressedBy = "non_conversational",
            )
        }

        val senderProfile = profile ?: SenderProfile(senderKey = event.senderId)
        val context = event.context

        val urgency = Urgency.score(event.content, config.urgency)
        val need = need(event, urgency, escalation)
        val (bond, bondParts) = bond(senderProfile, atMs)
        val reunion = reunion(senderProfile, atMs)
        val shapedBond = if (bond > 0) Math.pow(bond, config.bondCurve) else 0.0
        val affinity = clamp01(
            config.affinityBase +
                config.affinityBondWeight * shapedBond +
                config.reunionWeight * reunion * need
        )
        val penalty = contextPenalty(context)
        val contextFactor = 1.0 - config.contextDamping * penalty

        var score = clamp01(need * affinity * contextFactor)

        var escalationOverride = 0.0
        var criticalOverride = 0.0
        val criticalHits = urgency.matched.filter { it in config.urgency.criticalTerms }
        if (config.overrideEnabled) {
            if (escalation.overrideFactor > 0.0) {
                escalationOverride = clamp01(escalation.overrideFactor * config.overrideMax)
            }
            if (criticalHits.isNotEmpty()) {
                criticalOverride = clamp01(config.criticalOverride)
            }
        }
        val override = maxOf(escalationOverride, criticalOverride)
        score = maxOf(score, override)

        val reasons = reasons(urgency, escalation, senderProfile, reunion, penalty, escalationOverride, criticalHits, event, atMs)
        val components = buildMap {
            put("need", need)
            put("urgency", urgency.score)
            put("escalation", escalation.score)
            put("bond", bond)
            put("reunion", reunion)
            put("affinity", affinity)
            put("context_penalty", penalty)
            put("override", override)
            putAll(bondParts)
        }

        // A muted sender is held back one step: only an override -- repeated calls or
        // critical wording -- can still produce a real interrupt.
        if (senderProfile.muted) {
            val action = if (score >= config.interruptThreshold) {
                if (override > 0.0) Action.INTERRUPT else Action.SHOW_SILENTLY
            } else {
                Action.DEFER
            }
            return Decision(
                action = action,
                priorityScore = score,
                reasons = reasons + "sender is muted",
                components = components,
                suppressedBy = if (action == Action.INTERRUPT) null else "muted",
            )
        }

        return Decision(actionFor(score), score, reasons, components)
    }

    /**
     * How strongly the message itself asks for attention. Urgency and escalation
     * combine as a probabilistic OR: either alone can carry the message, and having
     * both saturates rather than overflows.
     */
    private fun need(
        event: NotificationEvent,
        urgency: UrgencySignal,
        escalation: EscalationSignal,
    ): Double {
        var value = urgency.score + escalation.score * (1.0 - urgency.score)
        if (event.isMissedCall) value = maxOf(value, config.missedCallNeed)
        if (event.isGroup && !event.mentionsUser) value *= config.groupWithoutMentionDamping
        return clamp01(value)
    }

    private fun bond(profile: SenderProfile, atMs: Long): Pair<Double, Map<String, Double>> {
        val relationship = profile.decayedRelationship(
            atMs,
            config.relationshipHalfLifeDays,
            config.relationshipFloor,
        )
        val tier = tierWeight(profile.effectiveTier)
        val starred = if (profile.isStarred || profile.effectiveTier == 1) 1.0 else 0.0

        val value = clamp01(
            config.wRelationship * relationship +
                config.wTier * tier +
                config.wOpenRate * profile.openRate +
                config.wStarred * starred
        )
        return value to mapOf(
            "relationship_decayed" to relationship,
            "tier_weight" to tier,
            "open_rate" to profile.openRate,
            "bond_shaped" to if (value > 0) Math.pow(value, config.bondCurve) else 0.0,
        )
    }

    /**
     * Dormancy credit, but only for people who were once close. Returns a 0..1 ramp;
     * the caller multiplies it by `need` so a long silence broken by small talk earns
     * nothing.
     */
    private fun reunion(profile: SenderProfile, atMs: Long): Double {
        if (!profile.isEstablished(config.reunionPeakThreshold, config.reunionMinLifetime)) {
            return 0.0
        }
        val days = profile.daysSinceLastSeen(atMs)
        val span = config.reunionFullDays - config.reunionMinDays
        if (span <= 0) return if (days >= config.reunionFullDays) 1.0 else 0.0
        return clamp01((days - config.reunionMinDays) / span)
    }

    private fun contextPenalty(context: UserContext): Double {
        var penalty = 0.0
        if (context.calendarBusy) penalty += config.penaltyCalendarBusy
        if (context.locationCategory == "meeting") penalty += config.penaltyMeeting
        if (context.driving) penalty += config.penaltyDriving
        when (context.timeOfDay) {
            "sleep" -> penalty += config.penaltySleep
            "night" -> penalty += config.penaltyNight
        }
        if (context.batteryLevel < config.lowBatteryLevel) penalty += config.penaltyLowBattery
        // Screen state is deliberately not penalised: during DND the screen is off by
        // definition, and that is exactly when a breakthrough matters most.
        return minOf(config.maxContextPenalty, penalty)
    }

    private fun actionFor(score: Double): Action = when {
        score >= config.interruptThreshold -> Action.INTERRUPT
        score >= config.silentThreshold -> Action.SHOW_SILENTLY
        else -> Action.DEFER
    }

    private fun reasons(
        urgency: UrgencySignal,
        escalation: EscalationSignal,
        profile: SenderProfile,
        reunion: Double,
        penalty: Double,
        escalationOverride: Double,
        criticalHits: List<String>,
        event: NotificationEvent,
        atMs: Long,
    ): List<String> = buildList {
        if (criticalHits.isNotEmpty()) add("critical wording (" + criticalHits.joinToString(", ") + ")")
        if (urgency.score >= 0.7) add("message reads as urgent")
        if (urgency.negated.isNotEmpty() && urgency.score < 0.4) add("urgent wording appears negated")
        if (urgency.spamPenalty >= 0.5) add("promotional wording detected")
        if (escalation.score >= 0.4) add("repeated contact (${escalation.burstCount} in 10 min)")
        if (event.isMissedCall) add("missed call")
        if (escalationOverride > 0.0) add("repeated calls (${escalation.callCount})")
        if (reunion >= 0.5) {
            val days = profile.daysSinceLastSeen(atMs).toInt()
            add(if (profile.lastSeenMs > 0) "close contact resurfacing after $days days" else "close contact resurfacing")
        }
        if (profile.effectiveTier <= 2 || profile.isStarred) add("priority contact")
        if (event.isGroup && !event.mentionsUser) add("group message without a mention")
        if (penalty >= 0.3) add("context suggests deferring")
    }

    companion object {
        /** Tier 1 -> 1.0, tier 5 -> 0.0. */
        fun tierWeight(tier: Int): Double = clamp01((5 - tier.coerceIn(1, 5)) / 4.0)
    }
}
