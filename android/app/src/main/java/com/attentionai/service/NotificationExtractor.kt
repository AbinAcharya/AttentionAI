package com.attentionai.service

import android.app.Notification
import android.os.Build
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat
import com.attentionai.core.NotificationEvent
import com.attentionai.core.UserContext

/**
 * Turns a [StatusBarNotification] into the engine's app-agnostic [NotificationEvent].
 *
 * The important part is [senderIdFor]. Using the display title as the identity key is
 * what makes this kind of app feel broken: two contacts named "Mom", a contact who
 * renames themselves, or a title that is really a group name all collapse or split the
 * learned history. So the extractor prefers, in order:
 *
 * 1. the `Person.key` from `MessagingStyle` -- stable, app-provided, survives renames;
 * 2. the conversation shortcut id (`shortcutId`), stable per conversation since API 26;
 * 3. the notification's own `tag`;
 * 4. only then the title text.
 *
 * The key is always namespaced by package, so "Alex" on WhatsApp and "Alex" on
 * Telegram do not share a profile.
 */
object NotificationExtractor {

    /** Packages whose notifications are never conversations worth interrupting for. */
    private val IGNORED_PACKAGES = setOf(
        "android",
        "com.android.systemui",
        "com.android.providers.downloads",
        "com.google.android.gms",
        "com.attentionai",
    )

    private val MISSED_CALL_HINTS = listOf("missed call", "missed video call", "छूटी हुई कॉल")

    fun shouldConsider(sbn: StatusBarNotification): Boolean {
        if (sbn.packageName in IGNORED_PACKAGES) return false
        val notification = sbn.notification ?: return false
        // Ranker-only / silent-by-design entries carry no user-facing text.
        val hasText = !textOf(notification).isNullOrBlank() || !titleOf(notification).isNullOrBlank()
        return hasText || isMissedCall(notification, null)
    }

    fun extract(
        sbn: StatusBarNotification,
        context: UserContext = UserContext(),
    ): NotificationEvent {
        val notification = sbn.notification
        val extras = notification.extras

        val style = runCatching {
            NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(notification)
        }.getOrNull()

        val lastMessage = style?.messages?.lastOrNull()
        val title = titleOf(notification)
        val senderName = lastMessage?.person?.name?.toString()
            ?: style?.conversationTitle?.toString()
            ?: title

        val content = lastMessage?.text?.toString()
            ?: extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()
            ?: textOf(notification)
            ?: ""

        val isGroup = style?.isGroupConversation
            ?: (style?.conversationTitle != null)

        return NotificationEvent(
            appName = sbn.packageName,
            senderId = senderIdFor(sbn, style, senderName),
            senderName = senderName,
            content = content,
            timestampMs = sbn.postTime,
            threadId = threadIdFor(sbn, style),
            notificationKey = sbn.key,
            isGroup = isGroup,
            mentionsUser = mentionsUser(content, isGroup),
            isMissedCall = isMissedCall(notification, title),
            isOngoing = sbn.isOngoing || notification.flags and Notification.FLAG_ONGOING_EVENT != 0,
            isGroupSummary = notification.flags and Notification.FLAG_GROUP_SUMMARY != 0,
            context = context,
        )
    }

    /** Stable identity for a sender, namespaced by package. See the class docs. */
    fun senderIdFor(
        sbn: StatusBarNotification,
        style: NotificationCompat.MessagingStyle?,
        senderName: String?,
    ): String {
        val personKey = style?.messages?.lastOrNull()?.person?.key
        val shortcut = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) sbn.notification.shortcutId else null

        val raw = personKey?.takeIf { it.isNotBlank() }
            ?: shortcut?.takeIf { it.isNotBlank() }
            ?: sbn.tag?.takeIf { it.isNotBlank() }
            ?: senderName?.takeIf { it.isNotBlank() }
            ?: "unknown"

        return "${sbn.packageName}:$raw"
    }

    private fun threadIdFor(
        sbn: StatusBarNotification,
        style: NotificationCompat.MessagingStyle?,
    ): String? {
        val conversation = style?.conversationTitle?.toString()
        val shortcut = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) sbn.notification.shortcutId else null
        val raw = shortcut ?: conversation ?: sbn.tag ?: return null
        return "${sbn.packageName}:$raw"
    }

    /**
     * Heuristic, and honestly labelled as one: an "@" immediately followed by a letter.
     * A notification listener cannot see the user's own display name in every app, so
     * this cannot be exact. Getting it wrong only damps a group message by 0.4 -- it
     * never suppresses a direct message.
     */
    private fun mentionsUser(content: String, isGroup: Boolean): Boolean {
        if (!isGroup) return false
        return Regex("@\\p{L}").containsMatchIn(content)
    }

    private fun isMissedCall(notification: Notification, title: String?): Boolean {
        if (notification.category == Notification.CATEGORY_MISSED_CALL) return true
        val haystack = (title ?: textOf(notification) ?: "").lowercase()
        return MISSED_CALL_HINTS.any { haystack.contains(it) }
    }

    private fun titleOf(notification: Notification): String? =
        notification.extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()

    private fun textOf(notification: Notification): String? =
        notification.extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()
}
