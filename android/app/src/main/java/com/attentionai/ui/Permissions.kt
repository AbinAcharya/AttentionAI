package com.attentionai.ui

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat
import com.attentionai.service.AttentionListenerService

/**
 * The three permissions this app genuinely cannot work without, and how to ask for
 * each. Two of them are special-access grants that no runtime dialog can request --
 * the user has to toggle them in system Settings, so the UI has to send them there and
 * then re-check on resume.
 */
object Permissions {

    /** Notification access: without it the service is never bound and reads nothing. */
    fun listenerEnabled(context: Context): Boolean =
        NotificationManagerCompat.getEnabledListenerPackages(context)
            .contains(context.packageName)

    fun openListenerSettings(context: Context) {
        val intent = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { context.startActivity(intent) }
    }

    /**
     * Do Not Disturb access. Without this the breakthrough channel's `setBypassDnd(true)`
     * is silently ignored and the app will look like it is working while doing nothing.
     */
    fun openPolicySettings(context: Context) {
        val intent = Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { context.startActivity(intent) }
    }

    /** Ask the system to re-bind the listener, e.g. after it was killed. */
    fun requestRebind(context: Context) {
        runCatching {
            android.service.notification.NotificationListenerService.requestRebind(
                ComponentName(context, AttentionListenerService::class.java)
            )
        }
    }
}
