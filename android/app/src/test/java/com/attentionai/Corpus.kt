package com.attentionai

import com.attentionai.core.Action
import com.attentionai.core.EscalationSignal
import com.attentionai.core.MS_PER_DAY
import com.attentionai.core.NotificationEvent
import com.attentionai.core.NotificationPolicy
import com.attentionai.core.SenderProfile
import com.attentionai.core.UserContext
import org.json.JSONObject

/**
 * Loader for the shared labelled corpus.
 *
 * The Kotlin engine and the Python reference engine are held to the *same file*
 * (`shared/scenarios.json`, copied to test resources by `tools/sync_corpus.py`). That is
 * the only thing that keeps two implementations of the same policy from drifting apart
 * in ways nobody notices until a real emergency is silently deferred.
 */
object Corpus {

    data class Scenario(
        val id: String,
        val note: String?,
        val expected: Action,
        val event: NotificationEvent,
        val profile: SenderProfile?,
        val escalation: EscalationSignal,
    )

    data class Result(
        val scenario: Scenario,
        val actual: Action,
        val score: Double,
        val reasons: List<String>,
    ) {
        val passed: Boolean get() = actual == scenario.expected
        /** Deferring something the corpus says must interrupt. The expensive failure. */
        val missedInterrupt: Boolean
            get() = scenario.expected == Action.INTERRUPT && actual != Action.INTERRUPT
        val falseInterrupt: Boolean
            get() = scenario.expected != Action.INTERRUPT && actual == Action.INTERRUPT
    }

    fun load(resource: String = "/scenarios.json"): Pair<Long, List<Scenario>> {
        val text = requireNotNull(Corpus::class.java.getResourceAsStream(resource)) {
            "corpus resource $resource not found; run `python tools/sync_corpus.py`"
        }.bufferedReader().use { it.readText() }

        val root = JSONObject(text)
        val nowMs = root.getLong("now_ms")
        val array = root.getJSONArray("scenarios")

        val scenarios = (0 until array.length()).map { index ->
            parse(array.getJSONObject(index), nowMs)
        }
        return nowMs to scenarios
    }

    fun run(policy: NotificationPolicy, nowMs: Long, scenarios: List<Scenario>): List<Result> =
        scenarios.map { scenario ->
            val decision = policy.analyze(
                event = scenario.event,
                profile = scenario.profile,
                escalation = scenario.escalation,
                atMs = nowMs,
            )
            Result(scenario, decision.action, decision.priorityScore, decision.reasons)
        }

    fun report(results: List<Result>): String = buildString {
        val passed = results.count { it.passed }
        appendLine("corpus: $passed/${results.size} passed")
        results.filterNot { it.passed }.forEach { result ->
            appendLine(
                "  FAIL ${result.scenario.id}: expected ${result.scenario.expected.wire}, " +
                    "got ${result.actual.wire} (score ${"%.3f".format(result.score)})"
            )
            result.scenario.note?.let { appendLine("       note: $it") }
            appendLine("       reasons: ${result.reasons.joinToString(", ").ifEmpty { "none" }}")
        }
        val missed = results.filter { it.missedInterrupt }.map { it.scenario.id }
        val falsePositives = results.filter { it.falseInterrupt }.map { it.scenario.id }
        appendLine("  missed interrupts: ${missed.ifEmpty { listOf("none") }.joinToString(", ")}")
        appendLine("  false interrupts:  ${falsePositives.ifEmpty { listOf("none") }.joinToString(", ")}")
    }

    // ---- parsing -------------------------------------------------------------

    private fun parse(json: JSONObject, nowMs: Long): Scenario {
        val eventJson = json.getJSONObject("event")
        val contextJson = json.optJSONObject("context")
        val profileJson = json.optJSONObject("profile")
        val escalationJson = json.optJSONObject("escalation")

        return Scenario(
            id = json.getString("id"),
            note = json.optString("note").ifBlank { null },
            expected = Action.fromWire(json.getString("expect")),
            event = NotificationEvent(
                appName = eventJson.optString("app_name", "unknown"),
                senderId = eventJson.optString("sender_id", "unknown"),
                senderName = eventJson.optString("sender_name").ifBlank { null },
                content = eventJson.optString("content", ""),
                timestampMs = eventJson.optLong("timestamp_ms", nowMs),
                threadId = eventJson.optString("thread_id").ifBlank { null },
                notificationKey = eventJson.optString("notification_key").ifBlank { null },
                isGroup = eventJson.optBoolean("is_group", false),
                mentionsUser = eventJson.optBoolean("mentions_user", false),
                isMissedCall = eventJson.optBoolean("is_missed_call", false),
                isOngoing = eventJson.optBoolean("is_ongoing", false),
                isGroupSummary = eventJson.optBoolean("is_group_summary", false),
                context = parseContext(contextJson),
            ),
            profile = profileJson?.let { parseProfile(it, eventJson.optString("sender_id", "unknown"), nowMs) },
            escalation = parseEscalation(escalationJson),
        )
    }

    private fun parseContext(json: JSONObject?): UserContext {
        if (json == null) return UserContext()
        return UserContext(
            timeOfDay = json.optString("time_of_day", "day"),
            locationCategory = json.optString("location_category", "unknown"),
            calendarBusy = json.optBoolean("calendar_busy", false),
            screenOn = json.optBoolean("screen_on", true),
            batteryLevel = json.optInt("battery_level", 100),
            driving = json.optBoolean("driving", false),
            headphonesConnected = json.optBoolean("headphones_connected", false),
            dndActive = json.optBoolean("dnd_active", false),
        )
    }

    private fun parseProfile(json: JSONObject, senderId: String, nowMs: Long): SenderProfile {
        // The corpus expresses age as `last_seen_days_ago` so it stays readable and
        // stays deterministic against the fixed `now_ms`.
        val daysAgo = if (json.has("last_seen_days_ago")) json.optDouble("last_seen_days_ago") else null
        val lastSeen = when {
            daysAgo == null -> 0L
            else -> nowMs - (daysAgo * MS_PER_DAY).toLong()
        }
        return SenderProfile(
            senderKey = json.optString("sender_key").ifBlank { senderId },
            tier = json.optInt("tier", 3),
            manualTier = if (json.has("manual_tier")) json.optInt("manual_tier") else null,
            relationshipScore = json.optDouble("relationship_score", 0.35),
            peakRelationship = json.optDouble("peak_relationship", 0.35),
            lifetimeInteractions = json.optInt("lifetime_interactions", 0),
            responseCount = json.optInt("response_count", 0),
            receivedCount = json.optInt("received_count", 0),
            avgResponseSeconds = json.optDouble("avg_response_seconds", 300.0),
            lastSeenMs = json.optLong("last_seen_ms", lastSeen),
            muted = json.optBoolean("muted", false),
            isContact = json.optBoolean("is_contact", false),
            isStarred = json.optBoolean("is_starred", false),
        )
    }

    private fun parseEscalation(json: JSONObject?): EscalationSignal {
        if (json == null) return EscalationSignal()
        return EscalationSignal(
            score = json.optDouble("score", 0.0),
            burstCount = json.optInt("burst_count", 0),
            callCount = json.optInt("call_count", 0),
            overrideFactor = json.optDouble("override_factor", 0.0),
        )
    }
}
