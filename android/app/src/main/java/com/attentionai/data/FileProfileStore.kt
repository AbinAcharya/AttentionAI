package com.attentionai.data

import com.attentionai.core.Privacy
import com.attentionai.core.ProfileStore
import com.attentionai.core.SenderProfile
import org.json.JSONObject
import java.io.File

/**
 * File-backed profile store. Port of `JsonProfileStore` from `attentionai/api.py`.
 *
 * Deliberately plain `org.json` + a file rather than Room: no annotation processor, no
 * schema migration, no code generation to fail on a first build. The dataset is a few
 * hundred small records, so a database would buy nothing.
 *
 * Two properties matter and are both tested:
 *
 * - **Idempotent hashing.** [Privacy.hashContactId] recognises an already-hashed key, so
 *   a load/save round trip cannot fork one contact into two profiles.
 * - **Atomic writes.** A phone that loses power mid-save must not cost the user
 *   everything the app has learned, so writes go to a temp file and are then renamed.
 */
class FileProfileStore(
    private val file: File,
    private val hashSenderId: Boolean = true,
    salt: String? = null,
) : ProfileStore {

    private val data = LinkedHashMap<String, JSONObject>()
    private var saltValue: String = salt.orEmpty()

    val salt: String get() = saltValue

    init {
        file.parentFile?.mkdirs()
        load()
        if (hashSenderId && saltValue.isEmpty()) {
            saltValue = Privacy.newSalt()
            persist()
        }
    }

    override fun keyFor(senderId: String): String =
        if (hashSenderId) Privacy.hashContactId(senderId, saltValue) else senderId

    @Synchronized
    override fun get(senderId: String): SenderProfile? =
        data[keyFor(senderId)]?.let { ProfileJson.fromJson(it) }

    @Synchronized
    override fun save(profile: SenderProfile) {
        val key = keyFor(profile.senderKey)
        data[key] = ProfileJson.toJson(profile, key)
        persist()
    }

    @Synchronized
    override fun all(): List<SenderProfile> = data.values.map { ProfileJson.fromJson(it) }

    @Synchronized
    override fun clear() {
        data.clear()
        // A new salt makes the old on-disk keys unlinkable to the new ones -- the
        // "reset what the app knows about me" promise, kept properly.
        saltValue = if (hashSenderId) Privacy.newSalt() else ""
        persist()
    }

    @Synchronized
    fun delete(senderId: String) {
        data.remove(keyFor(senderId))
        persist()
    }

    // ---- internals -----------------------------------------------------------

    private fun load() {
        if (!file.exists()) {
            persist()
            return
        }
        val text = runCatching { file.readText(Charsets.UTF_8) }.getOrNull()
        if (text.isNullOrBlank()) {
            persist()
            return
        }
        val root = runCatching { JSONObject(text) }.getOrNull()
        if (root == null) {
            // Corrupt file: start clean rather than crashing the listener service on boot.
            persist()
            return
        }

        if (root.has("profiles")) {
            saltValue = root.optString("salt", saltValue)
            val profiles = root.optJSONObject("profiles") ?: JSONObject()
            for (key in profiles.keys()) {
                profiles.optJSONObject(key)?.let { data[key] = it }
            }
        } else {
            // Legacy flat layout: {senderKey: profile}
            for (key in root.keys()) {
                root.optJSONObject(key)?.let { data[key] = it }
            }
        }
    }

    private fun persist() {
        val profiles = JSONObject()
        for ((key, value) in data) profiles.put(key, value)
        val root = JSONObject()
            .put("version", 2)
            .put("salt", saltValue)
            .put("profiles", profiles)

        val parent = file.parentFile
        parent?.mkdirs()
        val temp = File(parent, "${file.name}.tmp")
        runCatching {
            temp.writeText(root.toString(), Charsets.UTF_8)
            if (!temp.renameTo(file)) {
                // renameTo fails if the destination exists on some filesystems.
                file.delete()
                if (!temp.renameTo(file)) {
                    file.writeText(root.toString(), Charsets.UTF_8)
                    temp.delete()
                }
            }
        }.onFailure { temp.delete() }
    }
}

/** Field-by-field JSON mapping, kept in one place so both directions stay in step. */
object ProfileJson {

    fun toJson(profile: SenderProfile, key: String = profile.senderKey): JSONObject =
        JSONObject()
            .put("sender_key", key)
            .put("tier", profile.tier)
            .put("manual_tier", profile.manualTier ?: JSONObject.NULL)
            .put("relationship_score", profile.relationshipScore)
            .put("peak_relationship", profile.peakRelationship)
            .put("lifetime_interactions", profile.lifetimeInteractions)
            .put("response_count", profile.responseCount)
            .put("received_count", profile.receivedCount)
            .put("avg_response_seconds", profile.avgResponseSeconds)
            .put("last_seen_ms", profile.lastSeenMs)
            .put("last_outbound_ms", profile.lastOutboundMs)
            .put("last_response_ms", profile.lastResponseMs)
            .put("muted", profile.muted)
            .put("is_contact", profile.isContact)
            .put("is_starred", profile.isStarred)
            .put("manual_overrides", profile.manualOverrides)
            .put("display_name", profile.displayName ?: JSONObject.NULL)

    fun fromJson(json: JSONObject): SenderProfile = SenderProfile(
        senderKey = json.optString("sender_key", ""),
        tier = json.optInt("tier", 3),
        manualTier = if (json.isNull("manual_tier")) null else json.optInt("manual_tier"),
        relationshipScore = json.optDouble("relationship_score", 0.35),
        peakRelationship = json.optDouble("peak_relationship", 0.35),
        lifetimeInteractions = json.optInt("lifetime_interactions", 0),
        responseCount = json.optInt("response_count", 0),
        receivedCount = json.optInt("received_count", 0),
        avgResponseSeconds = json.optDouble("avg_response_seconds", 300.0),
        lastSeenMs = json.optLong("last_seen_ms", 0L),
        lastOutboundMs = json.optLong("last_outbound_ms", 0L),
        lastResponseMs = json.optLong("last_response_ms", 0L),
        muted = json.optBoolean("muted", false),
        isContact = json.optBoolean("is_contact", false),
        isStarred = json.optBoolean("is_starred", false),
        manualOverrides = json.optInt("manual_overrides", 0),
        displayName = if (json.isNull("display_name")) null else json.optString("display_name"),
    )
}
