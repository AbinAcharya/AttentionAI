package com.attentionai.core

/**
 * Content urgency extraction. Port of `attentionai/urgency.py`.
 *
 * Word-boundary phrase matching with a negation window, a promotional-vocabulary
 * damper, and romanised Hindi/Hinglish terms. Entirely offline and deterministic --
 * no model, no network, and the message text never leaves this file.
 */
object UrgencyTerms {

    /** Phrase -> urgency weight in [0, 1]. Multi-word phrases match as units. */
    val DEFAULT: Map<String, Double> = mapOf(
        // unambiguous crisis
        "emergency" to 1.0,
        "ambulance" to 1.0,
        "accident" to 0.95,
        "hospital" to 0.9,
        "icu" to 0.95,
        "police" to 0.9,
        "fire" to 0.85,
        "bleeding" to 0.95,
        "collapsed" to 0.95,
        "passed away" to 1.0,
        "in the hospital" to 0.95,
        "life threatening" to 1.0,
        // direct demands for attention
        "call me" to 0.85,
        "call me back" to 0.9,
        "pick up" to 0.85,
        "answer your phone" to 0.9,
        "are you awake" to 0.7,
        "you there" to 0.55,
        "need you" to 0.75,
        "i need help" to 0.9,
        "need your help" to 0.85,
        "please help" to 0.9,
        "help me" to 0.9,
        "help" to 0.9,   // terse appeals match "help me"; affinity still gates the sender
        "sos" to 1.0,
        // expanded urgency vocabulary - same priority as "help" (0.9)
        "assist me" to 0.9,
        "assistance needed" to 0.9,
        "need assistance" to 0.9,
        "救命" to 0.9,  // Chinese "help"
        "ayuda" to 0.9,  // Spanish "help"
        "ajuda" to 0.9,  // Portuguese "help"
        "aide" to 0.9,  // French "help"
        "hilfe" to 0.9,  // German "help"
        "aiuto" to 0.9,  // Italian "help"
        "mayday" to 0.9,
        "crisis" to 0.9,
        "critical situation" to 0.9,
        "911" to 0.9,
        "rescue" to 0.9,
        "救急" to 0.9,  // Japanese "emergency/help"
        "in trouble" to 0.9,
        "need help now" to 0.9,
        "come quick" to 0.9,
        "come quickly" to 0.9,
        "hurry" to 0.9,
        "get here" to 0.9,
        "save me" to 0.9,
        "stuck" to 0.9,
        "stranded" to 0.9,
        "please come" to 0.9,
        "can you come" to 0.9,
        "danger" to 0.9,
        "serious problem" to 0.9,
        // time pressure
        "urgent" to 0.8,
        "urgently" to 0.8,
        "asap" to 0.75,
        "right now" to 0.7,
        "immediately" to 0.75,
        "as soon as possible" to 0.7,
        "deadline" to 0.5,
        "last chance" to 0.35,
        // romanised hindi / hinglish
        "madad" to 0.9,
        "jaldi" to 0.7,
        "turant" to 0.8,
        "zaroori" to 0.7,
        "bahut zaroori" to 0.85,
        "hospital hai" to 0.95,
        "emergency hai" to 1.0,
        // devanagari
        "आपातकाल" to 1.0,
        "मदद" to 0.9,
        "जल्दी" to 0.7,
        // standalone words that are only mildly informative
        "please" to 0.15,
        "important" to 0.4,
        "problem" to 0.35,
        "worried" to 0.45,
        "scared" to 0.6,
    )

    /** Marketing vocabulary actively lowers urgency: emergencies have no offer code. */
    val SPAM: Map<String, Double> = mapOf(
        "offer" to 0.5,
        "discount" to 0.6,
        "sale" to 0.5,
        "cashback" to 0.7,
        "claim" to 0.6,
        "prize" to 0.8,
        "winner" to 0.8,
        "lottery" to 0.9,
        "coupon" to 0.6,
        "subscribe" to 0.5,
        "unsubscribe" to 0.7,
        "limited time" to 0.6,
        "click here" to 0.7,
        "verify your account" to 0.8,
        "otp" to 0.4,
        "loan" to 0.6,
        "credit card" to 0.5,
    )

    /**
     * Un-negated matches here bypass affinity entirely: even a stranger's one-word
     * "help" breaks through DND. Excludes ambiguous words ("urgent", "police", "fire",
     * "hospital") so normal and automated traffic does not trip it.
     */
    val CRITICAL: Set<String> = setOf(
        "help",
        "help me",
        "please help",
        "i need help",
        "need your help",
        "emergency",
        "emergency hai",
        "sos",
        "ambulance",
        "accident",
        "bleeding",
        "madad",
        "आपातकाल",
        "मदद",
    )

    /** Tokens that flip an urgency term appearing shortly after them. */
    val NEGATORS: Set<String> = setOf(
        "no", "not", "nope", "never", "nothing", "isnt", "isn't", "arent", "aren't",
        "wasnt", "wasn't", "dont", "don't", "doesnt", "doesn't", "cant", "can't",
        "nvm", "nevermind", "false", "just", "only", "kidding", "jk", "joking",
    )
}

data class UrgencyConfig(
    val terms: Map<String, Double> = UrgencyTerms.DEFAULT,
    val spamTerms: Map<String, Double> = UrgencyTerms.SPAM,
    val negators: Set<String> = UrgencyTerms.NEGATORS,
    val criticalTerms: Set<String> = UrgencyTerms.CRITICAL,
    val shoutingBonus: Double = 0.10,
    val exclamationBonus: Double = 0.05,
    val questionBonus: Double = 0.05,
    val spamDamping: Double = 0.75,
    val floor: Double = 0.05,
    val ceiling: Double = 1.0,
)

data class UrgencySignal(
    val score: Double,
    val matched: List<String> = emptyList(),
    val negated: List<String> = emptyList(),
    val spamPenalty: Double = 0.0,
    val isCritical: Boolean = false,
)

object Urgency {

    private const val NEGATION_WINDOW_TOKENS = 4
    private const val NEGATION_DISCOUNT = 0.25

    // \p{L}\p{N} rather than \w so Devanagari tokenises correctly.
    private val WORD_REGEX = Regex("[\\p{L}\\p{N}_']+")

    // Tokenising every phrase on every message would be wasteful; the default tables
    // are static, so cache their tokenisation.
    private val phraseCache = HashMap<String, List<String>>()

    @Synchronized
    private fun tokensFor(phrase: String): List<String> =
        phraseCache.getOrPut(phrase) { tokenize(phrase) }

    fun tokenize(text: String): List<String> =
        WORD_REGEX.findAll(text.lowercase()).map { it.value }.toList()

    /** Score how strongly a message body asks for immediate attention. */
    fun score(content: String?, config: UrgencyConfig = UrgencyConfig()): UrgencySignal {
        val text = content?.trim().orEmpty()
        if (text.isEmpty()) return UrgencySignal(config.floor)

        val tokens = tokenize(text)
        if (tokens.isEmpty()) return UrgencySignal(config.floor)

        var best = 0.0
        val matched = mutableListOf<String>()
        val negated = mutableListOf<String>()

        for ((phrase, weight) in config.terms) {
            val positions = phrasePositions(tokens, tokensFor(phrase))
            if (positions.isEmpty()) continue
            if (positions.any { !isNegated(tokens, it, config.negators) }) {
                matched += phrase
                best = maxOf(best, weight)
            } else {
                negated += phrase
                best = maxOf(best, weight * NEGATION_DISCOUNT)
            }
        }

        if (best > 0.0) {
            if (shoutingRatio(text) >= 0.6) best += config.shoutingBonus
            if (text.contains("!!") || text.count { it == '!' } >= 2) best += config.exclamationBonus
            if (text.contains("?")) best += config.questionBonus
        }

        var spamPenalty = 0.0
        for ((phrase, weight) in config.spamTerms) {
            if (phrasePositions(tokens, tokensFor(phrase)).isNotEmpty()) {
                spamPenalty = maxOf(spamPenalty, weight)
            }
        }
        if (spamPenalty > 0.0) best *= 1.0 - config.spamDamping * spamPenalty

        return UrgencySignal(
            score = best.coerceIn(config.floor, config.ceiling),
            matched = matched.sorted(),
            negated = negated.sorted(),
            spamPenalty = spamPenalty,
            isCritical = matched.any { it in config.criticalTerms },
        )
    }

    /** Token indices where [phraseTokens] occurs as a contiguous run. */
    private fun phrasePositions(tokens: List<String>, phraseTokens: List<String>): List<Int> {
        if (phraseTokens.isEmpty() || phraseTokens.size > tokens.size) return emptyList()
        val hits = mutableListOf<Int>()
        val first = phraseTokens[0]
        val span = phraseTokens.size
        for (index in 0..(tokens.size - span)) {
            if (tokens[index] == first && tokens.subList(index, index + span) == phraseTokens) {
                hits += index
            }
        }
        return hits
    }

    private fun isNegated(tokens: List<String>, position: Int, negators: Set<String>): Boolean {
        val start = maxOf(0, position - NEGATION_WINDOW_TOKENS)
        for (index in start until position) {
            if (tokens[index] in negators) return true
        }
        return false
    }

    private fun shoutingRatio(text: String): Double {
        val letters = text.filter { it.isLetter() }
        if (letters.length < 6) return 0.0
        return letters.count { it.isUpperCase() }.toDouble() / letters.length
    }
}
