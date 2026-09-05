package com.attentionai.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.widget.Toast
import com.attentionai.Graph
import com.attentionai.R
import com.attentionai.core.Feedback

/**
 * Handles the buttons on a breakthrough notification.
 *
 * The sender key arrives already hashed. That is safe to pass straight back into the
 * engine because [com.attentionai.core.Privacy.hashContactId] is idempotent -- hashing
 * an already-hashed key returns it unchanged, so the feedback lands on the same profile
 * rather than creating a second one.
 */
class FeedbackReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        Graph.init(context)

        val senderKey = intent.getStringExtra(EXTRA_SENDER_KEY) ?: return
        val notificationId = intent.getIntExtra(EXTRA_NOTIFICATION_ID, -1)

        val message = when (intent.action) {
            ACTION_DISMISSED -> {
                Graph.engine.recordFeedback(senderKey, Feedback.DISMISSED)
                null
            }
            ACTION_NOT_IMPORTANT -> {
                // Demote rather than mute: one bad interrupt is weak evidence, and a
                // silent mute is the kind of thing users cannot find again later.
                Graph.engine.recordFeedback(senderKey, Feedback.DEMOTED, tier = 4)
                context.getString(R.string.toast_demoted)
            }
            ACTION_ALWAYS_ALLOW -> {
                Graph.engine.recordFeedback(senderKey, Feedback.PROMOTED, tier = 1)
                context.getString(R.string.toast_promoted)
            }
            else -> null
        }

        if (notificationId > 0 && intent.action != ACTION_DISMISSED) {
            Graph.breakthrough.cancel(notificationId)
        }
        message?.let { Toast.makeText(context, it, Toast.LENGTH_SHORT).show() }
    }

    companion object {
        const val ACTION_DISMISSED = "com.attentionai.action.DISMISSED"
        const val ACTION_NOT_IMPORTANT = "com.attentionai.action.NOT_IMPORTANT"
        const val ACTION_ALWAYS_ALLOW = "com.attentionai.action.ALWAYS_ALLOW"
        const val EXTRA_SENDER_KEY = "sender_key"
        const val EXTRA_NOTIFICATION_ID = "notification_id"
    }
}
