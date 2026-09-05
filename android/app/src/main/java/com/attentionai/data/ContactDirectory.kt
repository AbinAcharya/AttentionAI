package com.attentionai.data

import android.content.Context
import android.content.pm.PackageManager
import android.provider.ContactsContract
import androidx.core.content.ContextCompat

/**
 * Optional cold-start help from the address book.
 *
 * A notification listener sees a sender's *display name*, not their phone number, so
 * this can only match on name -- a heuristic, and treated as one. It seeds a brand-new
 * profile with a starting tier instead of leaving every stranger and every sibling
 * identically at tier 3, which is the worst possible cold start for a feature whose job
 * is knowing who matters.
 *
 * Everything degrades cleanly: without `READ_CONTACTS` the directory is simply empty,
 * and any explicit tier the user sets always wins over a hint from here.
 */
data class ContactHint(
    val displayName: String,
    val starred: Boolean,
    val timesContacted: Int,
) {
    /** Tier 1 for starred, 2 for frequently contacted, 3 for anyone else in the book. */
    val suggestedTier: Int
        get() = when {
            starred -> 1
            timesContacted >= 50 -> 2
            else -> 3
        }
}

class ContactDirectory(context: Context) {

    private val appContext = context.applicationContext
    private var byName: Map<String, ContactHint> = emptyMap()
    private var loaded = false

    fun hasPermission(): Boolean = ContextCompat.checkSelfPermission(
        appContext,
        android.Manifest.permission.READ_CONTACTS,
    ) == PackageManager.PERMISSION_GRANTED

    @Synchronized
    fun hintFor(displayName: String?): ContactHint? {
        if (displayName.isNullOrBlank()) return null
        if (!loaded) load()
        return byName[normalise(displayName)]
    }

    @Synchronized
    fun refresh() {
        loaded = false
        byName = emptyMap()
    }

    @Synchronized
    fun load() {
        loaded = true
        if (!hasPermission()) return

        val projection = arrayOf(
            ContactsContract.Contacts.DISPLAY_NAME_PRIMARY,
            ContactsContract.Contacts.STARRED,
            ContactsContract.Contacts.TIMES_CONTACTED,
        )

        val hints = HashMap<String, ContactHint>()
        runCatching {
            appContext.contentResolver.query(
                ContactsContract.Contacts.CONTENT_URI,
                projection,
                null,
                null,
                null,
            )?.use { cursor ->
                val nameIndex = cursor.getColumnIndex(ContactsContract.Contacts.DISPLAY_NAME_PRIMARY)
                val starredIndex = cursor.getColumnIndex(ContactsContract.Contacts.STARRED)
                val timesIndex = cursor.getColumnIndex(ContactsContract.Contacts.TIMES_CONTACTED)
                while (cursor.moveToNext()) {
                    val name = if (nameIndex >= 0) cursor.getString(nameIndex) else null
                    if (name.isNullOrBlank()) continue
                    val hint = ContactHint(
                        displayName = name,
                        starred = starredIndex >= 0 && cursor.getInt(starredIndex) == 1,
                        timesContacted = if (timesIndex >= 0) cursor.getInt(timesIndex) else 0,
                    )
                    val key = normalise(name)
                    // Keep the strongest hint if two contacts normalise to the same name.
                    val existing = hints[key]
                    if (existing == null || hint.suggestedTier < existing.suggestedTier) {
                        hints[key] = hint
                    }
                }
            }
        }
        byName = hints
    }

    private fun normalise(name: String): String =
        name.trim().lowercase().replace(Regex("\\s+"), " ")
}
