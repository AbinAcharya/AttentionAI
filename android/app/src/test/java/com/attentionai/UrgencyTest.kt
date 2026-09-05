package com.attentionai

import com.attentionai.core.Urgency
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class UrgencyTest {

    private fun score(text: String) = Urgency.score(text).score

    @Test
    fun `explicit crisis wording scores high`() {
        assertTrue(score("there has been an accident, call an ambulance") >= 0.9)
        assertTrue(score("I need help right now") >= 0.85)
        assertTrue(score("SOS") >= 0.9)
    }

    @Test
    fun `small talk scores low`() {
        assertTrue(score("lol ok goodnight") <= 0.1)
        assertTrue(score("happy new year! long time no see") <= 0.25)
    }

    @Test
    fun `negation flips an urgent phrase`() {
        val negated = Urgency.score("no emergency, just checking in")
        assertTrue("expected low score, got ${negated.score}", negated.score <= 0.3)
        assertTrue(negated.negated.contains("emergency"))
    }

    @Test
    fun `negation only reaches back a few tokens`() {
        // The negator is far enough away that it is not negating "emergency".
        val text = "no I did not get your message earlier but there is an emergency now"
        assertTrue(score(text) >= 0.8)
    }

    @Test
    fun `promotional wording damps urgency`() {
        val spam = Urgency.score("URGENT! Claim your prize now, limited time offer")
        assertTrue("expected damped score, got ${spam.score}", spam.score <= 0.45)
        assertTrue(spam.spamPenalty >= 0.5)
    }

    @Test
    fun `romanised hindi is recognised`() {
        assertTrue(score("bhai emergency hai, jaldi call me") >= 0.9)
        assertTrue(score("madad chahiye") >= 0.85)
    }

    @Test
    fun `devanagari is tokenised correctly`() {
        // \p{L} rather than \w -- with \w this scored the floor.
        assertTrue(score("मदद") >= 0.85)
    }

    @Test
    fun `phrases match as units, not as loose words`() {
        // "pick up" the phrase, versus the two words in unrelated positions.
        assertTrue(score("pick up the phone") >= 0.85)
        assertTrue(score("I will pick the kids up from school tomorrow") <= 0.3)
    }

    @Test
    fun `empty content returns the floor`() {
        assertEquals(0.05, score(""), 1e-9)
        assertEquals(0.05, score("   "), 1e-9)
        assertEquals(0.05, Urgency.score(null).score, 1e-9)
    }

    @Test
    fun `shouting and punctuation add a little, never a lot`() {
        val calm = score("there is a problem")
        val shouted = score("THERE IS A PROBLEM!!")
        assertTrue(shouted > calm)
        assertTrue("bonuses should be modest", shouted - calm <= 0.2)
    }
}
