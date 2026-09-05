package com.attentionai.service

import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import com.attentionai.Graph
import com.attentionai.core.Feedback
import com.attentionai.core.NotificationEvent

/**
 * Reads notifications, scores them, and mirrors the ones that earn a breakthrough.
 *
 * Requires the user to grant notification access in
 * Settings > Notifications > Device & app notifications. Nothing here leaves the
 * device, and message text is never written to disk -- it is scored in memory and
 * dropped.
 */
class AttentionListenerService : NotificationListenerService() {

    /**
     * Notifications this service actually scored, keyed by `sbn.key`. Bounded, because a
     * busy phone posts thousands a day and an unbounded map in a long-lived service is
     * a leak. Only entries in here produce learning signals -- otherwise `openRate`
     * would count responses to notifications the engine never saw.
     */
    private val processed = object : LinkedHashMap<String, String>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, String>?): Boolean =
            size > MAX_TRACKED
    }

    override fun onListenerConnected() {
        super.onListenerConnected()
        Graph.init(this)
        Graph.breakthrough.ensureChannels()
        Log.i(TAG, "listener connected; dnd bypass active=${Graph.breakthrough.bypassActive()}")
    }

    override fun onNotificationPosted(sbn: StatusBarNotification, rankingMap: RankingMap?) {
        Graph.init(this)
        if (!Graph.settings.enabled) return
        if (!NotificationExtractor.shouldConsider(sbn)) return

        runCatching { handle(sbn, rankingMap) }
            .onFailure { Log.w(TAG, "failed to handle ${sbn.packageName}", it) }
    }

    override fun onNotificationRemoved(
        sbn: StatusBarNotification,
        rankingMap: RankingMap?,
        reason: Int,
    ) {
        super.onNotificationRemoved(sbn, rankingMap, reason)
        Graph.init(this)

        val senderId = synchronized(processed) { processed.remove(sbn.key) } ?: return

        // Clear our mirror when the real one goes away, so the shade does not keep a
        // stale duplicate around.
        Graph.breakthrough.cancel(Breakthrough.notificationIdFor(Graph.engine.keyFor(senderId)))

        if (!Graph.settings.learningEnabled) return

        // This is the whole learning signal, and it is the user's behaviour rather than
        // the engine's own opinion: opening a notification is evidence the interrupt was
        // wanted, swiping it away is evidence it was not.
        val feedback = when (reason) {
            REASON_CLICK -> Feedback.OPENED
            REASON_CANCEL -> Feedback.DISMISSED
            else -> null
        } ?: return

        Graph.engine.recordFeedback(senderId, feedback, System.currentTimeMillis())
    }

    // ---- internals -----------------------------------------------------------

    private fun handle(sbn: StatusBarNotification, rankingMap: RankingMap?) {
        val context = Graph.contextProvider.current()
        val settings = Graph.settings

        if (settings.onlyDuringDnd && !context.dndActive) return

        // If the system is already going to let this alert through the current filter,
        // mirroring it would just be a duplicate buzz.
        if (alreadyAllowed(sbn, rankingMap)) return

        val event = NotificationExtractor.extract(sbn, context)
        seedFromContacts(event)

        val decision = Graph.engine.process(event, System.currentTimeMillis())
        val senderKey = Graph.engine.keyFor(event.senderId)

        Graph.decisionLog.add(
            atMs = System.currentTimeMillis(),
            senderKey = senderKey,
            senderName = event.senderName ?: getString(com.attentionai.R.string.unknown_sender),
            appName = event.appName,
            decision = decision,
        )

        synchronized(processed) { processed[sbn.key] = event.senderId }

        if (!decision.isInterrupt) return

        Graph.breakthrough.post(
            senderKey = senderKey,
            senderName = event.senderName ?: getString(com.attentionai.R.string.unknown_sender),
            content = event.content,
            decision = decision,
            original = sbn.notification,
        )
    }

    private fun alreadyAllowed(sbn: StatusBarNotification, rankingMap: RankingMap?): Boolean {
        val map = rankingMap ?: return false
        val ranking = Ranking()
        if (!map.getRanking(sbn.key, ranking)) return false
        return runCatching { ranking.matchesInterruptionFilter() }.getOrDefault(false)
    }

    /**
     * First contact with a new sender: borrow a starting tier from the address book if
     * we have it. Any tier the user sets by hand overrides this permanently.
     */
    private fun seedFromContacts(event: NotificationEvent) {
        if (Graph.profileStore.get(event.senderId) != null) return
        val hint = Graph.contacts.hintFor(event.senderName) ?: return
        Graph.engine.bootstrapContact(
            senderId = event.senderId,
            tier = hint.suggestedTier,
            isContact = true,
            isStarred = hint.starred,
            displayName = event.senderName,
        )
    }

    companion object {
        private const val TAG = "AttentionListener"
        private const val MAX_TRACKED = 200
    }
}
