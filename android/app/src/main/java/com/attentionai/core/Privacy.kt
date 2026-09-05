package com.attentionai.core

import java.security.MessageDigest
import java.security.SecureRandom

/**
 * Privacy helpers. Port of `attentionai/privacy.py`.
 *
 * Two rules the rest of the engine relies on:
 *
 * 1. Hashing is **idempotent**. A load/save round trip cannot re-hash a key and
 *    silently fork one contact into two profiles.
 * 2. Hashing is **salted per install**. A phone number carries about ten digits of
 *    entropy, so a bare SHA-256 of one is reversible with a laptop and an afternoon.
 *    The salt is generated once on the device and never leaves it.
 */
object Privacy {

    const val HASH_PREFIX = "ak_"
    private const val HASH_LENGTH = 24
    private val HASHED_LENGTH = HASH_PREFIX.length + HASH_LENGTH

    fun newSalt(): String {
        val bytes = ByteArray(16)
        SecureRandom().nextBytes(bytes)
        return bytes.toHex()
    }

    fun isHashed(value: String?): Boolean =
        value != null && value.startsWith(HASH_PREFIX) && value.length == HASHED_LENGTH

    /** Map a raw sender identifier to a stable, opaque key. Idempotent. */
    fun hashContactId(value: String, salt: String = ""): String {
        if (isHashed(value)) return value
        val digest = MessageDigest.getInstance("SHA-256")
            .digest("$salt|$value".toByteArray(Charsets.UTF_8))
        return HASH_PREFIX + digest.toHex().take(HASH_LENGTH)
    }

    private fun ByteArray.toHex(): String {
        val builder = StringBuilder(size * 2)
        for (byte in this) builder.append("%02x".format(byte))
        return builder.toString()
    }
}

/** Where sender profiles live. Implementations own their own hashing boundary. */
interface ProfileStore {
    fun keyFor(senderId: String): String
    fun get(senderId: String): SenderProfile?
    fun save(profile: SenderProfile)
    fun all(): List<SenderProfile>
    fun clear()

    fun getOrCreate(senderId: String): SenderProfile =
        get(senderId) ?: SenderProfile(senderKey = keyFor(senderId))
}

/** Test/preview store. Hashing is applied so behaviour matches the real one. */
class InMemoryProfileStore(
    private val salt: String = "",
    private val hashIds: Boolean = false,
) : ProfileStore {

    private val data = HashMap<String, SenderProfile>()

    override fun keyFor(senderId: String): String =
        if (hashIds) Privacy.hashContactId(senderId, salt) else senderId

    @Synchronized
    override fun get(senderId: String): SenderProfile? = data[keyFor(senderId)]?.copy()

    @Synchronized
    override fun save(profile: SenderProfile) {
        val key = keyFor(profile.senderKey)
        data[key] = profile.copy(senderKey = key)
    }

    @Synchronized
    override fun all(): List<SenderProfile> = data.values.map { it.copy() }

    @Synchronized
    override fun clear() = data.clear()
}
