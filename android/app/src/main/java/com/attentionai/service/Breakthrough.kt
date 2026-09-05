package com.attentionai.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.attentionai.R
import com.attentionai.core.Decision

/**
 * The actual breakthrough mechanism.
 *
 * This is the part people usually get wrong, so it is worth stating plainly: a
 * third-party app **cannot** un-suppress another app's notification. There is no API to
 * promote WhatsApp's notification past Do Not Disturb. What an app can do is read the
 * notification via [android.service.notification.NotificationListenerService] and then
 * post **its own** notification on a channel created with `setBypassDnd(true)` -- which
 * the system only honours once the user has granted
 * `ACCESS_NOTIFICATION_POLICY` ("Do Not Disturb access").
 *
 * A further trap: a channel's DND-bypass flag is fixed at creation. If the channel was
 * created before the user granted policy access, the flag silently did nothing and
 * re-creating the same id restores the old settings. Hence the generation counter --
 * when access appears and the current channel still cannot bypass, a *new* channel id
 * is minted.
 */
class Breakthrough(context: Context) {

    private val appContext = context.applicationContext
    private val manager =
        appContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    private val prefs =
        appContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** True once the user has granted Do Not Disturb access. */
    fun hasPolicyAccess(): Boolean =
        runCatching { manager.isNotificationPolicyAccessGranted }.getOrDefault(false)

    fun canPostNotifications(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return ContextCompat.checkSelfPermission(
            appContext,
            android.Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
    }

    /** True when a breakthrough posted right now would actually be heard during DND. */
    fun bypassActive(): Boolean =
        manager.getNotificationChannel(channelId())?.canBypassDnd() == true

    fun ensureChannels() {
        val current = manager.getNotificationChannel(channelId())
        if (current != null && !current.canBypassDnd() && hasPolicyAccess()) {
            // The flag could not be applied when this channel was born. Recreating the
            // same id would restore the old (non-bypassing) settings, so mint a new one.
            manager.deleteNotificationChannel(current.id)
            prefs.edit().putInt(KEY_GENERATION, generation() + 1).apply()
        }

        val breakthrough = NotificationChannel(
            channelId(),
            appContext.getString(R.string.channel_breakthrough_name),
            NotificationManager.IMPORTANCE_HIGH,
        ).apply {
            description = appContext.getString(R.string.channel_breakthrough_description)
            setBypassDnd(true)
            enableVibration(true)
            enableLights(true)
            lockscreenVisibility = Notification.VISIBILITY_PRIVATE
            setSound(
                android.provider.Settings.System.DEFAULT_NOTIFICATION_URI,
                AudioAttributes.Builder()
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .setUsage(AudioAttributes.USAGE_NOTIFICATION)
                    .build(),
            )
        }
        manager.createNotificationChannel(breakthrough)

        val status = NotificationChannel(
            CHANNEL_STATUS,
            appContext.getString(R.string.channel_status_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = appContext.getString(R.string.channel_status_description)
            setShowBadge(false)
        }
        manager.createNotificationChannel(status)
    }

    /**
     * Mirror an allowed notification onto the bypassing channel.
     *
     * The original `contentIntent` is reused verbatim, so tapping the breakthrough opens
     * the real conversation in the real app rather than this one.
     */
    fun post(
        senderKey: String,
        senderName: String,
        content: String,
        decision: Decision,
        original: Notification?,
    ) {
        if (!canPostNotifications()) return
        ensureChannels()

        val notificationId = notificationIdFor(senderKey)
        val builder = NotificationCompat.Builder(appContext, channelId())
            .setSmallIcon(R.drawable.ic_breakthrough)
            .setContentTitle(senderName)
            .setContentText(content.take(240))
            .setStyle(NotificationCompat.BigTextStyle().bigText(content.take(600)))
            .setSubText(reasonLine(decision))
            .setCategory(NotificationCompat.CATEGORY_MESSAGE)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setDefaults(NotificationCompat.DEFAULT_ALL)
            .setAutoCancel(true)
            .setOnlyAlertOnce(false)
            .setDeleteIntent(feedbackIntent(FeedbackReceiver.ACTION_DISMISSED, senderKey, notificationId))
            .addAction(
                0,
                appContext.getString(R.string.action_not_important),
                feedbackIntent(FeedbackReceiver.ACTION_NOT_IMPORTANT, senderKey, notificationId),
            )
            .addAction(
                0,
                appContext.getString(R.string.action_always_allow),
                feedbackIntent(FeedbackReceiver.ACTION_ALWAYS_ALLOW, senderKey, notificationId),
            )

        original?.contentIntent?.let { builder.setContentIntent(it) }

        runCatching {
            NotificationManagerCompat.from(appContext).notify(notificationId, builder.build())
        }
    }

    fun cancel(notificationId: Int) {
        runCatching { NotificationManagerCompat.from(appContext).cancel(notificationId) }
    }

    private fun reasonLine(decision: Decision): String {
        val percent = Math.round(decision.priorityScore * 100).toInt()
        val why = decision.reasons.firstOrNull()
        return if (why != null) "$percent% · $why" else "$percent%"
    }

    private fun feedbackIntent(action: String, senderKey: String, notificationId: Int): PendingIntent {
        val intent = Intent(appContext, FeedbackReceiver::class.java).apply {
            this.action = action
            putExtra(FeedbackReceiver.EXTRA_SENDER_KEY, senderKey)
            putExtra(FeedbackReceiver.EXTRA_NOTIFICATION_ID, notificationId)
        }
        return PendingIntent.getBroadcast(
            appContext,
            (action + senderKey).hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
    }

    private fun generation(): Int = prefs.getInt(KEY_GENERATION, 1)

    private fun channelId(): String = "$CHANNEL_BREAKTHROUGH_BASE${generation()}"

    companion object {
        private const val PREFS = "attentionai_channels"
        private const val KEY_GENERATION = "breakthrough_generation"
        private const val CHANNEL_BREAKTHROUGH_BASE = "attentionai_breakthrough_v"
        const val CHANNEL_STATUS = "attentionai_status"

        /** Stable per sender, so a repeat from the same person updates in place. */
        fun notificationIdFor(senderKey: String): Int =
            (senderKey.hashCode() and 0x7FFFFFFF) % 100_000 + 1000
    }
}
