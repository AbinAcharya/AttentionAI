package com.attentionai

import com.attentionai.core.Action
import com.attentionai.core.EscalationSignal
import com.attentionai.core.MS_PER_DAY
import com.attentionai.core.NotificationEvent
import com.attentionai.core.NotificationPolicy
import com.attentionai.core.PolicyConfig
import com.attentionai.core.SenderProfile
import com.attentionai.core.UserContext
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PolicyTest {

    private val now = 1_767_225_600_000L
    private val policy = NotificationPolicy()

    private fun event(
        content: String,
        context: UserContext = UserContext(),
        isGroup: Boolean = false,
        mentionsUser: Boolean = false,
        isMissedCall: Boolean = false,
    ) = NotificationEvent(
        appName = "WhatsApp",
        senderId = "someone",
        content = content,
        timestampMs = now,
        isGroup = isGroup,
        mentionsUser = mentionsUser,
        isMissedCall = isMissedCall,
        context = context,
    )

    private fun closeFriend(daysAgo: Long) = SenderProfile(
        senderKey = "someone",
        tier = 2,
        relationshipScore = 0.8,
        peakRelationship = 0.85,
        lifetimeInteractions = 240,
        responseCount = 180,
        receivedCount = 220,
        lastSeenMs = now - daysAgo * MS_PER_DAY,
    )

    @Test
    fun `scoring is multiplicative so closeness alone cannot interrupt`() {
        val partner = SenderProfile(
            senderKey = "partner",
            tier = 1,
            manualTier = 1,
            relationshipScore = 0.95,
            peakRelationship = 0.95,
            lifetimeInteractions = 5000,
            responseCount = 900,
            receivedCount = 1000,
            isStarred = true,
            lastSeenMs = now,
        )
        val decision = policy.analyze(
            event("lol ok goodnight", UserContext(timeOfDay = "sleep", screenOn = false)),
            partner,
            EscalationSignal(),
            now,
        )
        assertEquals(Action.DEFER, decision.action)
    }

    @Test
    fun `the same closeness plus a real emergency does interrupt at 3am`() {
        val partner = SenderProfile(
            senderKey = "partner",
            tier = 1,
            manualTier = 1,
            relationshipScore = 0.95,
            peakRelationship = 0.95,
            lifetimeInteractions = 5000,
            responseCount = 900,
            receivedCount = 1000,
            isStarred = true,
            lastSeenMs = now,
        )
        val decision = policy.analyze(
            event("I'm at the hospital, please call me", UserContext(timeOfDay = "sleep", screenOn = false)),
            partner,
            EscalationSignal(),
            now,
        )
        assertEquals(Action.INTERRUPT, decision.action)
    }

    @Test
    fun `reunion credit is multiplied by need, not added to it`() {
        val dormant = closeFriend(daysAgo = 800)
        val night = UserContext(timeOfDay = "night", screenOn = false)

        val help = policy.analyze(event("I really need help, please call me", night), dormant, EscalationSignal(), now)
        val chat = policy.analyze(event("happy new year! long time no see", night), dormant, EscalationSignal(), now)

        assertEquals(Action.INTERRUPT, help.action)
        assertEquals(Action.DEFER, chat.action)
        assertTrue((help.components["reunion"] ?: 0.0) >= 0.99)
    }

    @Test
    fun `a dormant stranger earns no reunion credit`() {
        val stranger = SenderProfile(
            senderKey = "shortcode",
            tier = 5,
            relationshipScore = 0.1,
            peakRelationship = 0.15,
            lifetimeInteractions = 0,
            receivedCount = 40,
            lastSeenMs = now - 900 * MS_PER_DAY,
        )
        val decision = policy.analyze(
            event("emergency, please call me back", UserContext(timeOfDay = "night")),
            stranger,
            EscalationSignal(),
            now,
        )
        assertEquals(0.0, decision.components["reunion"] ?: -1.0, 1e-9)
        assertEquals(Action.DEFER, decision.action)
    }

    @Test
    fun `repeated calls from an unknown number open the override`() {
        val stranger = SenderProfile(senderKey = "unknown", tier = 5, relationshipScore = 0.2)
        val decision = policy.analyze(
            event("", UserContext(timeOfDay = "night"), isMissedCall = true),
            stranger,
            EscalationSignal(score = 1.0, burstCount = 5, callCount = 5, overrideFactor = 1.0),
            now,
        )
        assertEquals(Action.INTERRUPT, decision.action)
        assertTrue(decision.reasons.any { it.contains("repeated calls") })
    }

    @Test
    fun `muting downgrades but the override still gets through`() {
        val muted = closeFriend(daysAgo = 1).apply { muted = true }

        val urgent = policy.analyze(
            event("emergency please help me right now", UserContext(timeOfDay = "night")),
            muted,
            EscalationSignal(),
            now,
        )
        assertEquals(Action.SHOW_SILENTLY, urgent.action)
        assertEquals("muted", urgent.suppressedBy)

        val calling = policy.analyze(
            event("", UserContext(timeOfDay = "night"), isMissedCall = true),
            muted,
            EscalationSignal(score = 1.0, burstCount = 4, callCount = 4, overrideFactor = 1.0),
            now,
        )
        assertEquals(Action.INTERRUPT, calling.action)
    }

    @Test
    fun `group messages without a mention are damped`() {
        val colleague = SenderProfile(
            senderKey = "colleague",
            tier = 3,
            relationshipScore = 0.5,
            peakRelationship = 0.5,
            lifetimeInteractions = 60,
            responseCount = 40,
            receivedCount = 120,
            lastSeenMs = now - MS_PER_DAY,
        )
        val text = "urgent, we need to fix the deploy"
        val night = UserContext(timeOfDay = "night")

        val unmentioned = policy.analyze(event(text, night, isGroup = true), colleague, EscalationSignal(), now)
        val mentioned = policy.analyze(
            event(text, night, isGroup = true, mentionsUser = true), colleague, EscalationSignal(), now,
        )
        assertTrue(mentioned.priorityScore > unmentioned.priorityScore)
        assertEquals(Action.DEFER, unmentioned.action)
    }

    @Test
    fun `ongoing and summary notifications are not conversations`() {
        val ongoing = NotificationEvent(appName = "Spotify", senderId = "spotify", content = "Now playing", isOngoing = true)
        val summary = NotificationEvent(appName = "WhatsApp", senderId = "s", content = "12 new messages", isGroupSummary = true)

        listOf(ongoing, summary).forEach { candidate ->
            val decision = policy.analyze(candidate, null, EscalationSignal(), now)
            assertEquals(Action.DEFER, decision.action)
            assertEquals("non_conversational", decision.suppressedBy)
        }
    }

    @Test
    fun `context penalties are capped so an emergency is never fully suppressed`() {
        val text = "I'm at the hospital, please call me"
        val profile = closeFriend(daysAgo = 1)
        val hostile = UserContext(
            timeOfDay = "sleep",
            locationCategory = "meeting",
            calendarBusy = true,
            driving = true,
            batteryLevel = 3,
        )

        val calm = policy.analyze(event(text, UserContext(timeOfDay = "day")), profile, EscalationSignal(), now)
        val worst = policy.analyze(event(text, hostile), profile, EscalationSignal(), now)

        // Raw penalties total 1.20 here; the cap holds them at 0.80, and damping of 0.45
        // means the worst possible context can still only remove 36% of the score.
        assertEquals(0.80, worst.components["context_penalty"] ?: 0.0, 1e-9)
        assertTrue(worst.priorityScore >= calm.priorityScore * 0.6)
        assertTrue(worst.priorityScore >= 0.45)
    }

    @Test
    fun `relationship decays with silence but never below the floor`() {
        val profile = closeFriend(daysAgo = 10_000)
        val decayed = profile.decayedRelationship(now)
        assertTrue(decayed >= 0.15)
        assertTrue(decayed < 0.2)
    }

    @Test
    fun `tier weights span the full range`() {
        assertEquals(1.0, NotificationPolicy.tierWeight(1), 1e-9)
        assertEquals(0.0, NotificationPolicy.tierWeight(5), 1e-9)
        assertEquals(0.5, NotificationPolicy.tierWeight(3), 1e-9)
        // Out-of-range input is clamped rather than producing a negative weight.
        assertEquals(1.0, NotificationPolicy.tierWeight(-4), 1e-9)
        assertEquals(0.0, NotificationPolicy.tierWeight(99), 1e-9)
    }

    @Test
    fun `thresholds are configurable without touching the weights`() {
        val strict = NotificationPolicy(PolicyConfig(interruptThreshold = 0.95))
        val decision = strict.analyze(
            event("I'm at the hospital, please call me", UserContext(timeOfDay = "night")),
            closeFriend(daysAgo = 1),
            EscalationSignal(),
            now,
        )
        assertTrue(decision.action != Action.INTERRUPT)
        assertNotNull(decision.components["need"])
    }
}
