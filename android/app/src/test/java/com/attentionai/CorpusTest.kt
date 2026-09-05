package com.attentionai

import com.attentionai.core.Action
import com.attentionai.core.NotificationPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The behavioural contract. If this fails, the Kotlin engine and the Python reference
 * engine no longer agree, and one of them is wrong.
 */
class CorpusTest {

    @Test
    fun `every scenario matches its label`() {
        val (nowMs, scenarios) = Corpus.load()
        assertTrue("corpus is empty", scenarios.isNotEmpty())

        val results = Corpus.run(NotificationPolicy(), nowMs, scenarios)
        val report = Corpus.report(results)
        println(report)

        val failures = results.filterNot { it.passed }
        assertTrue("corpus regressions:\n$report", failures.isEmpty())
    }

    /**
     * Called out separately because the two error types are not equally expensive:
     * a wrong buzz is an annoyance, a missed emergency is the reason someone would
     * uninstall this app and never trust one again.
     */
    @Test
    fun `no emergency is silently deferred`() {
        val (nowMs, scenarios) = Corpus.load()
        val results = Corpus.run(NotificationPolicy(), nowMs, scenarios)
        val missed = results.filter { it.missedInterrupt }.map { it.scenario.id }
        assertEquals("missed interrupts: $missed", emptyList<String>(), missed)
    }

    @Test
    fun `the dormant-friend-needs-help case works and its twin stays quiet`() {
        val (nowMs, scenarios) = Corpus.load()
        val results = Corpus.run(NotificationPolicy(), nowMs, scenarios).associateBy { it.scenario.id }

        val emergency = requireNotNull(results["reunion-emergency"])
        val smallTalk = requireNotNull(results["reunion-small-talk"])
        val strangerSpam = requireNotNull(results["dormant-stranger-urgent-words"])

        assertEquals(Action.INTERRUPT, emergency.actual)
        assertEquals(Action.DEFER, smallTalk.actual)
        assertEquals(Action.DEFER, strangerSpam.actual)

        // Same person, same dormancy: the gap has to come from the message, not the gap
        // in contact. That is the whole design of the reunion term.
        assertTrue(
            "reunion bonus is not being gated on need",
            emergency.score > smallTalk.score + 0.4,
        )
    }
}
