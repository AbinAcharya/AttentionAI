package com.attentionai.core

/**
 * Burst / repetition detection. Port of `attentionai/escalation.py`.
 *
 * The strongest real-world urgency signal is not vocabulary, it is *retrying*. People
 * in genuine trouble send three messages in ninety seconds, or call twice then text.
 * That pattern needs no language model and survives any phrasing -- including
 * "are you awake", which no keyword list would rank highly on its own.
 *
 * State is in-memory, bounded, and never persisted. Access is synchronised because
 * `NotificationListenerService` callbacks and the UI thread can both reach it.
 */

data class EscalationConfig(
    val windowMs: Long = 10 * 60_000L,
    val messageWeight: Double = 1.0,
    val callWeight: Double = 3.0,
    val mentionWeight: Double = 1.5,
    /** Weighted units above the first that correspond to escalation == 1.0. */
    val saturation: Double = 4.0,
    /** Repeated calls from anyone -- known or not -- open the emergency override. */
    val overrideCallCount: Int = 3,
    val maxEventsPerSender: Int = 32,
    val maxSenders: Int = 512,
)

data class EscalationSignal(
    val score: Double = 0.0,
    val burstCount: Int = 0,
    val callCount: Int = 0,
    val overrideFactor: Double = 0.0,
)

class EscalationTracker(private val config: EscalationConfig = EscalationConfig()) {

    private data class Event(val atMs: Long, val weight: Double, val isCall: Boolean)

    private val events = HashMap<String, MutableList<Event>>()

    /** Record one inbound event and return the resulting escalation signal. */
    @Synchronized
    fun record(
        senderKey: String,
        atMs: Long,
        isCall: Boolean = false,
        mentionsUser: Boolean = false,
    ): EscalationSignal {
        var weight = if (isCall) config.callWeight else config.messageWeight
        if (mentionsUser && !isCall) weight = maxOf(weight, config.mentionWeight)

        events.getOrPut(senderKey) { mutableListOf() }.add(Event(atMs, weight, isCall))
        prune(senderKey, atMs)
        evictStaleSenders(atMs)

        val current = events[senderKey].orEmpty()
        val totalWeight = current.sumOf { it.weight }
        val callCount = current.count { it.isCall }

        // The first message is never escalation; only what follows it is.
        val excess = maxOf(0.0, totalWeight - config.messageWeight)
        val score = if (config.saturation > 0) minOf(1.0, excess / config.saturation) else 0.0

        var overrideFactor = 0.0
        if (config.overrideCallCount > 0 && callCount >= config.overrideCallCount) {
            val extra = callCount - config.overrideCallCount
            overrideFactor = minOf(1.0, 0.6 + 0.2 * extra)
        }

        return EscalationSignal(score, current.size, callCount, overrideFactor)
    }

    /** Read the current signal without recording a new event. */
    @Synchronized
    fun peek(senderKey: String, atMs: Long): EscalationSignal {
        prune(senderKey, atMs)
        val current = events[senderKey].orEmpty()
        if (current.isEmpty()) return EscalationSignal()
        val totalWeight = current.sumOf { it.weight }
        val excess = maxOf(0.0, totalWeight - config.messageWeight)
        return EscalationSignal(
            score = if (config.saturation > 0) minOf(1.0, excess / config.saturation) else 0.0,
            burstCount = current.size,
            callCount = current.count { it.isCall },
        )
    }

    @Synchronized
    fun reset(senderKey: String? = null) {
        if (senderKey == null) events.clear() else events.remove(senderKey)
    }

    private fun prune(senderKey: String, atMs: Long) {
        val current = events[senderKey] ?: return
        val cutoff = atMs - config.windowMs
        var kept = current.filter { it.atMs > cutoff }
        if (kept.size > config.maxEventsPerSender) {
            kept = kept.takeLast(config.maxEventsPerSender)
        }
        if (kept.isEmpty()) events.remove(senderKey) else events[senderKey] = kept.toMutableList()
    }

    private fun evictStaleSenders(atMs: Long) {
        if (events.size <= config.maxSenders) return
        val cutoff = atMs - config.windowMs
        events.entries.removeAll { (_, list) -> list.isEmpty() || list.last().atMs <= cutoff }
    }
}
