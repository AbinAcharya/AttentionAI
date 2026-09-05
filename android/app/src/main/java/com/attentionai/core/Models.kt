package com.attentionai.core

/**
 * Core data model. Deliberately free of any `android.*` import so the whole decision
 * engine runs in plain JVM unit tests against the same `scenarios.json` corpus the
 * Python reference implementation uses.
 */

const val MS_PER_DAY: Long = 86_400_000L

fun clamp01(value: Double): Double = value.coerceIn(0.0, 1.0)

enum class Action {
    INTERRUPT,
    SHOW_SILENTLY,
    DEFER;

    /** Wire name, matching the Python engine and the scenario corpus. */
    val wire: String
        get() = when (this) {
            INTERRUPT -> "interrupt"
            SHOW_SILENTLY -> "show_silently"
            DEFER -> "defer"
        }

    companion object {
        fun fromWire(value: String): Action = when (value) {
            "interrupt" -> INTERRUPT
            "show_silently" -> SHOW_SILENTLY
            "defer" -> DEFER
            else -> throw IllegalArgumentException("unknown action: $value")
        }
    }
}

/** The user's situation, independent of who is messaging. */
data class UserContext(
    val timeOfDay: String = "day",              // day | evening | night | sleep
    val locationCategory: String = "unknown",   // home | office | meeting | transit | unknown
    val calendarBusy: Boolean = false,
    val screenOn: Boolean = true,
    val batteryLevel: Int = 100,
    val driving: Boolean = false,
    val headphonesConnected: Boolean = false,
    val dndActive: Boolean = false,
)

/**
 * What we have learned about one sender.
 *
 * [relationshipScore] decays with silence; [peakRelationship] and
 * [lifetimeInteractions] never do. That asymmetry is what lets the policy tell an old
 * friend resurfacing apart from a stranger, long after the decaying score has
 * forgotten the difference.
 */
data class SenderProfile(
    val senderKey: String,
    var tier: Int = 3,                       // 1 = closest, 5 = furthest
    var manualTier: Int? = null,             // explicit user override, wins over `tier`
    var relationshipScore: Double = 0.35,
    var peakRelationship: Double = 0.35,
    var lifetimeInteractions: Int = 0,
    var responseCount: Int = 0,
    var receivedCount: Int = 0,
    var avgResponseSeconds: Double = 300.0,
    var lastSeenMs: Long = 0L,               // last inbound message; 0 = never
    var lastOutboundMs: Long = 0L,
    var lastResponseMs: Long = 0L,
    var muted: Boolean = false,
    var isContact: Boolean = false,
    var isStarred: Boolean = false,
    var manualOverrides: Int = 0,
    var displayName: String? = null,
) {
    val effectiveTier: Int get() = manualTier ?: tier

    /** Laplace-smoothed, so a brand-new sender sits at 0.5 rather than 0 or 1. */
    val openRate: Double get() = (responseCount + 1.0) / (receivedCount + 2.0)

    fun daysSinceLastSeen(atMs: Long): Double =
        if (lastSeenMs <= 0L) 0.0 else ((atMs - lastSeenMs).toDouble() / MS_PER_DAY).coerceAtLeast(0.0)

    fun decayedRelationship(atMs: Long, halfLifeDays: Double = 90.0, floor: Double = 0.15): Double {
        if (lastSeenMs <= 0L) return relationshipScore
        val days = daysSinceLastSeen(atMs)
        if (days <= 0.0 || halfLifeDays <= 0.0) return relationshipScore
        val decay = Math.pow(0.5, days / halfLifeDays)
        return floor + (relationshipScore - floor) * decay
    }

    /** Did this person ever actually matter to the user? Gates the reunion bonus. */
    fun isEstablished(peakThreshold: Double, minInteractions: Int): Boolean {
        val manual = manualTier
        return peakRelationship >= peakThreshold ||
            lifetimeInteractions >= minInteractions ||
            isStarred ||
            (manual != null && manual <= 2)
    }

    // --- learning -----------------------------------------------------------
    // Driven by observed user behaviour only. Never by the engine's own decision.

    fun recordDelivery(atMs: Long) {
        receivedCount += 1
        lastSeenMs = atMs
    }

    fun recordResponse(atMs: Long, responseSeconds: Double? = null) {
        responseCount += 1
        lifetimeInteractions += 1
        lastResponseMs = atMs
        relationshipScore = clamp01(relationshipScore + 0.06)
        peakRelationship = maxOf(peakRelationship, relationshipScore)
        if (responseSeconds != null && responseSeconds >= 0) {
            avgResponseSeconds = 0.7 * avgResponseSeconds + 0.3 * responseSeconds
        }
    }

    fun recordDismissal() {
        relationshipScore = maxOf(0.0, relationshipScore - 0.02)
    }

    fun recordOutbound(atMs: Long) {
        lastOutboundMs = atMs
        lifetimeInteractions += 1
        relationshipScore = clamp01(relationshipScore + 0.04)
        peakRelationship = maxOf(peakRelationship, relationshipScore)
    }

    fun setManualTierValue(tierValue: Int) {
        val bounded = tierValue.coerceIn(1, 5)
        manualTier = bounded
        manualOverrides += 1
        if (bounded <= 2) peakRelationship = maxOf(peakRelationship, 0.8)
    }
}

/** One inbound notification, normalised away from any particular messaging app. */
data class NotificationEvent(
    val appName: String,
    val senderId: String,
    val senderName: String? = null,
    val content: String = "",
    val timestampMs: Long = 0L,
    val threadId: String? = null,
    val notificationKey: String? = null,
    val isGroup: Boolean = false,
    val mentionsUser: Boolean = false,
    val isMissedCall: Boolean = false,
    val isOngoing: Boolean = false,
    val isGroupSummary: Boolean = false,
    val context: UserContext = UserContext(),
) {
    fun dedupKey(): String = notificationKey ?: threadId ?: "$appName:$senderId"
}

/** What to do, how strongly, and -- for the UI -- why. */
data class Decision(
    val action: Action,
    val priorityScore: Double,
    val reasons: List<String> = emptyList(),
    val components: Map<String, Double> = emptyMap(),
    val suppressedBy: String? = null,
) {
    val isInterrupt: Boolean get() = action == Action.INTERRUPT
}
