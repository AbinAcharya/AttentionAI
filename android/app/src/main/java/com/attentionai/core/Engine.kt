package com.attentionai.core

/**
 * Engine wiring: event -> profile -> policy -> budget -> decision.
 * Port of `attentionai/api.py`.
 *
 * The engine does not train on its own output. [process] records only that a
 * notification was *delivered*; `relationshipScore` moves solely through
 * [recordFeedback], which the service layer drives from real user behaviour
 * (`onNotificationRemoved` with `REASON_CLICK` vs `REASON_CANCEL`).
 */

/** Observed user actions. The only inputs allowed to move a relationship score. */
enum class Feedback {
    OPENED,
    DISMISSED,
    REPLIED,
    OUTBOUND,
    PROMOTED,
    DEMOTED,
}

class AttentionEngine(
    val policy: NotificationPolicy = NotificationPolicy(),
    val profileStore: ProfileStore? = null,
    val escalation: EscalationTracker = EscalationTracker(),
    val budget: InterruptBudget = InterruptBudget(),
) {

    // ---- decisioning ---------------------------------------------------------

    fun process(event: NotificationEvent, atMs: Long? = null): Decision {
        val at = atMs ?: (event.timestampMs.takeIf { it > 0L } ?: System.currentTimeMillis())
        val key = keyFor(event.senderId)

        // Media controls and group summaries never reach the profile store, so they
        // cannot pollute what the app has learned about real people.
        if (event.isOngoing || event.isGroupSummary) {
            return policy.analyze(event, null, EscalationSignal(), at)
        }

        val profile = profileStore?.getOrCreate(event.senderId)
            ?: SenderProfile(senderKey = key)

        val escalationSignal = escalation.record(
            senderKey = key,
            atMs = at,
            isCall = event.isMissedCall,
            mentionsUser = event.mentionsUser,
        )

        val decision = policy.analyze(event, profile, escalationSignal, at)

        profile.recordDelivery(at)
        profileStore?.save(profile)

        return applyBudget(decision, key, event, at)
    }

    private fun applyBudget(
        decision: Decision,
        key: String,
        event: NotificationEvent,
        atMs: Long,
    ): Decision {
        val dedupKey = event.dedupKey()
        if (!decision.isInterrupt) {
            budget.noteShown(dedupKey, atMs)
            return decision
        }

        // A genuine emergency must never be de-duplicated, rate-limited or cooled
        // down: the second "help" is exactly as urgent as the first. Overrides
        // (critical wording, repeated calls) cap at 0.85 -- *below* the budget's
        // 0.90 bypass -- so they were being held back while ordinary high-affinity
        // traffic swept past. We still commit() so normal traffic from the same
        // sender keeps its back-pressure once the emergency has passed.
        if ((decision.components["override"] ?: 0.0) > 0.0) {
            budget.commit(key, atMs, dedupKey)
            return decision
        }

        val verdict = budget.check(key, decision.priorityScore, atMs, dedupKey)
        if (verdict.allowed) {
            budget.commit(key, atMs, dedupKey)
            return decision
        }

        return decision.copy(
            action = Action.SHOW_SILENTLY,
            reasons = decision.reasons + "held back: ${verdict.reason}",
            suppressedBy = verdict.reason,
        )
    }

    // ---- learning ------------------------------------------------------------

    fun recordFeedback(
        senderId: String,
        kind: Feedback,
        atMs: Long = System.currentTimeMillis(),
        responseSeconds: Double? = null,
        tier: Int? = null,
    ): SenderProfile? {
        val store = profileStore ?: return null
        val profile = store.getOrCreate(senderId)

        when (kind) {
            Feedback.OPENED, Feedback.REPLIED -> profile.recordResponse(atMs, responseSeconds)
            Feedback.DISMISSED -> profile.recordDismissal()
            Feedback.OUTBOUND -> profile.recordOutbound(atMs)
            Feedback.PROMOTED -> profile.setManualTierValue(tier ?: 1)
            Feedback.DEMOTED -> profile.setManualTierValue(tier ?: 5)
        }

        store.save(profile)
        return profile
    }

    /**
     * Seed a profile from the address book at onboarding. Without this every sender
     * starts at tier 3 with no history -- the worst possible cold start for a feature
     * whose entire job is knowing who matters.
     */
    fun bootstrapContact(
        senderId: String,
        tier: Int = 3,
        isContact: Boolean = true,
        isStarred: Boolean = false,
        lifetimeInteractions: Int = 0,
        displayName: String? = null,
    ): SenderProfile? {
        val store = profileStore ?: return null
        val profile = store.getOrCreate(senderId)
        profile.tier = tier.coerceIn(1, 5)
        profile.isContact = isContact
        profile.isStarred = isStarred
        if (displayName != null) profile.displayName = displayName
        if (lifetimeInteractions > 0) {
            profile.lifetimeInteractions = maxOf(profile.lifetimeInteractions, lifetimeInteractions)
        }
        if (isStarred) {
            profile.peakRelationship = maxOf(profile.peakRelationship, 0.75)
            profile.relationshipScore = maxOf(profile.relationshipScore, 0.6)
        }
        store.save(profile)
        return profile
    }

    fun setMuted(senderId: String, muted: Boolean): SenderProfile? {
        val store = profileStore ?: return null
        val profile = store.getOrCreate(senderId)
        profile.muted = muted
        store.save(profile)
        return profile
    }

    fun profile(senderId: String): SenderProfile? = profileStore?.get(senderId)

    fun keyFor(senderId: String): String = profileStore?.keyFor(senderId) ?: senderId
}
