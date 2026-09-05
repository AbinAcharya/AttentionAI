package com.attentionai.data

import com.attentionai.core.Action
import com.attentionai.core.Decision
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * A short, in-memory record of recent decisions, for the "why did that get through?"
 * screen.
 *
 * Message content is deliberately **not** stored -- only who it was from, what was
 * decided, and the reasons the policy gave. The log lives in RAM and dies with the
 * process; nothing here is written to disk.
 */
data class DecisionRecord(
    val atMs: Long,
    val senderKey: String,
    val senderName: String,
    val appName: String,
    val action: Action,
    val score: Double,
    val reasons: List<String>,
    val suppressedBy: String?,
) {
    val scorePercent: Int get() = Math.round(score * 100).toInt()
}

class DecisionLog(private val capacity: Int = 60) {

    private val entries = ArrayDeque<DecisionRecord>()
    private val state = MutableStateFlow<List<DecisionRecord>>(emptyList())

    val recent: StateFlow<List<DecisionRecord>> = state.asStateFlow()

    @Synchronized
    fun add(
        atMs: Long,
        senderKey: String,
        senderName: String,
        appName: String,
        decision: Decision,
    ) {
        entries.addFirst(
            DecisionRecord(
                atMs = atMs,
                senderKey = senderKey,
                senderName = senderName,
                appName = appName,
                action = decision.action,
                score = decision.priorityScore,
                reasons = decision.reasons,
                suppressedBy = decision.suppressedBy,
            )
        )
        while (entries.size > capacity) entries.removeLast()
        state.value = entries.toList()
    }

    @Synchronized
    fun clear() {
        entries.clear()
        state.value = emptyList()
    }
}
