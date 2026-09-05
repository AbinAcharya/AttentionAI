package com.attentionai.core

/**
 * Interrupt budget and de-duplication. Port of `attentionai/budget.py`.
 *
 * Scoring alone will happily let twenty notifications cross the threshold in one hour,
 * which defeats the point of Do Not Disturb. This is the back-pressure: a rolling cap
 * on breakthroughs, a per-sender cooldown, and suppression of repeats.
 *
 * A high enough score bypasses both -- a real emergency must not be rate-limited
 * because two other things got through first.
 */

data class BudgetConfig(
    val windowMs: Long = 60 * 60_000L,
    val maxInterruptsPerWindow: Int = 3,
    val perSenderCooldownMs: Long = 10 * 60_000L,
    val duplicateTtlMs: Long = 5 * 60_000L,
    val bypassScore: Double = 0.90,
    val maxTrackedKeys: Int = 1024,
)

data class BudgetVerdict(
    val allowed: Boolean,
    val reason: String = BudgetReasons.ALLOWED,
    val remaining: Int = 0,
)

object BudgetReasons {
    const val ALLOWED = "allowed"
    const val BUDGET = "hourly_budget_exhausted"
    const val COOLDOWN = "sender_cooldown"
    const val DUPLICATE = "duplicate_notification"
}

class InterruptBudget(private val config: BudgetConfig = BudgetConfig()) {

    private val interrupts = mutableListOf<Long>()
    private val lastBySender = HashMap<String, Long>()
    private val seenDedup = HashMap<String, Long>()

    /** Decide whether an interrupt-scored notification may actually break through. */
    @Synchronized
    fun check(
        senderKey: String,
        score: Double,
        atMs: Long,
        dedupKey: String? = null,
    ): BudgetVerdict {
        prune(atMs)

        if (dedupKey != null) {
            val lastSeen = seenDedup[dedupKey]
            if (lastSeen != null && atMs - lastSeen < config.duplicateTtlMs) {
                return BudgetVerdict(false, BudgetReasons.DUPLICATE, remaining())
            }
        }

        if (score >= config.bypassScore) {
            return BudgetVerdict(true, BudgetReasons.ALLOWED, remaining())
        }

        val lastInterrupt = lastBySender[senderKey]
        if (lastInterrupt != null && atMs - lastInterrupt < config.perSenderCooldownMs) {
            return BudgetVerdict(false, BudgetReasons.COOLDOWN, remaining())
        }

        if (interrupts.size >= config.maxInterruptsPerWindow) {
            return BudgetVerdict(false, BudgetReasons.BUDGET, 0)
        }

        return BudgetVerdict(true, BudgetReasons.ALLOWED, remaining())
    }

    /** Record that a breakthrough actually happened. */
    @Synchronized
    fun commit(senderKey: String, atMs: Long, dedupKey: String? = null) {
        interrupts += atMs
        lastBySender[senderKey] = atMs
        if (dedupKey != null) seenDedup[dedupKey] = atMs
        prune(atMs)
    }

    /** Record a silent/deferred delivery so repeats of it are still de-duplicated. */
    @Synchronized
    fun noteShown(dedupKey: String?, atMs: Long) {
        if (dedupKey == null) return
        seenDedup[dedupKey] = atMs
        prune(atMs)
    }

    @Synchronized
    fun remaining(atMs: Long): Int {
        prune(atMs)
        return remaining()
    }

    @Synchronized
    fun reset() {
        interrupts.clear()
        lastBySender.clear()
        seenDedup.clear()
    }

    private fun remaining(): Int =
        maxOf(0, config.maxInterruptsPerWindow - interrupts.size)

    private fun prune(atMs: Long) {
        val windowCutoff = atMs - config.windowMs
        interrupts.removeAll { it <= windowCutoff }

        val cooldownCutoff = atMs - config.perSenderCooldownMs
        lastBySender.entries.removeAll { it.value <= cooldownCutoff }

        val dedupCutoff = atMs - config.duplicateTtlMs
        seenDedup.entries.removeAll { it.value <= dedupCutoff }

        if (seenDedup.size > config.maxTrackedKeys) {
            seenDedup.entries
                .sortedBy { it.value }
                .take(seenDedup.size / 2)
                .forEach { seenDedup.remove(it.key) }
        }
    }
}
