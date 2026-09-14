package com.attentionai

import com.attentionai.core.Action
import com.attentionai.core.AttentionEngine
import com.attentionai.core.InMemoryProfileStore
import com.attentionai.core.NotificationEvent
import com.attentionai.core.NotificationPolicy
import com.attentionai.core.SenderProfile
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BudgetTest {

    private val now = 1_767_225_600_000L

    private fun event(content: String, key: String, atMs: Long = now) = NotificationEvent(
        appName = "WhatsApp",
        senderId = "someone",
        content = content,
        timestampMs = atMs,
        notificationKey = key,
    )

    private fun engine(store: InMemoryProfileStore) =
        AttentionEngine(policy = NotificationPolicy(), profileStore = store)

    /**
     * Regression for the "second help is silent" report: a repeat message arrives as an
     * *update* to the same conversation notification, so `notificationKey` (and hence the
     * budget dedup key) is identical. The budget treated the second critical plea as a
     * duplicate and denied it. Critical wording must never be rate-limited.
     */
    @Test
    fun `a second help updating the same notification interrupts again`() {
        val engine = engine(InMemoryProfileStore())
        val key = "0|com.whatsapp|123|tx"

        val first = engine.process(event("help", key), now)
        val second = engine.process(event("help", key), now + 60_000)

        assertEquals(Action.INTERRUPT, first.action)
        assertEquals(Action.INTERRUPT, second.action)
    }

    /**
     * A stranger's repeated calls open the emergency override, but it ramps:
     * callCount >= 3 opens it (0.6 factor), and it only reaches the 0.70
     * interrupt threshold at 5 calls (overrideFactor 1.0 * 0.85 max). Once
     * engaged, a quick repeat must not be held back by the budget dedup/cooldown.
     */
    @Test
    fun `repeated calls from an unknown number are not budget-denied`() {
        val engine = engine(InMemoryProfileStore())
        val base = event("", "call-key", now).copy(isMissedCall = true)

        // Calls 1-4 are too few to clear the threshold; call 5 triggers the override.
        for (i in 0 until 5) {
            engine.process(base.copy(timestampMs = now + i * 30_000), now + i * 30_000)
        }

        // The 6th call (still within the window) must NOT be budget-denied.
        val repeat = engine.process(base.copy(timestampMs = now + 150_000), now + 150_000)
        assertEquals(Action.INTERRUPT, repeat.action)
        assertTrue("must not be suppressed", repeat.suppressedBy == null)
    }

    /**
     * The back-pressure must survive: an ordinary (non-critical) repeat within the
     * per-sender cooldown is still held back. Only the emergency override is exempted.
     */
    @Test
    fun `ordinary urgent repeats still respect the sender cooldown`() {
        val store = InMemoryProfileStore()
        store.save(
            SenderProfile(
                senderKey = "someone",
                tier = 1,
                manualTier = 1,
                relationshipScore = 0.95,
                peakRelationship = 0.95,
                isStarred = true,
                lastSeenMs = now,
            ),
        )
        val engine = engine(store)
        val key = "0|com.whatsapp|456|tx"

        val first = engine.process(event("call me back, it is urgent", key), now)
        val second = engine.process(event("call me back, it is urgent", key), now + 60_000)

        assertEquals(Action.INTERRUPT, first.action)
        assertEquals(Action.SHOW_SILENTLY, second.action)
        assertTrue(second.suppressedBy != null)
    }
}