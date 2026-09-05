package com.attentionai.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import com.attentionai.Graph
import com.attentionai.core.Action
import com.attentionai.core.Decision
import com.attentionai.core.Feedback
import com.attentionai.core.NotificationEvent
import com.attentionai.core.SenderProfile
import com.attentionai.data.Sensitivity
import com.attentionai.service.Breakthrough

class MainActivity : ComponentActivity() {

    // Bumped on resume and after any action, so the screen re-reads system permission
    // state. Special-access grants happen in system Settings, outside this process --
    // there is no callback, so re-checking on resume is the only reliable signal.
    private val refreshTick = mutableIntStateOf(0)

    private lateinit var permissionLauncher: ActivityResultLauncher<Array<String>>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Graph.init(this)

        permissionLauncher = registerForActivityResult(
            ActivityResultContracts.RequestMultiplePermissions()
        ) {
            Graph.contacts.refresh()
            refreshTick.intValue++
        }

        setContent {
            AttentionTheme {
                val tick by refreshTick
                val state = remember(tick) { readState() }
                val people = remember(tick) { readPeople() }

                HomeScreen(
                    state = state,
                    people = people,
                    decisions = Graph.decisionLog.recent,
                    actions = HomeActions(
                        openListenerSettings = { Permissions.openListenerSettings(this) },
                        openPolicySettings = { Permissions.openPolicySettings(this) },
                        requestPostNotifications = ::requestPostNotifications,
                        requestContacts = ::requestContacts,
                        setEnabled = { Graph.settings.enabled = it; refreshTick.intValue++ },
                        setOnlyDuringDnd = { Graph.settings.onlyDuringDnd = it; refreshTick.intValue++ },
                        setLearning = { Graph.settings.learningEnabled = it; refreshTick.intValue++ },
                        setSensitivity = {
                            Graph.settings.sensitivity = it
                            Graph.rebuildEngine()
                            refreshTick.intValue++
                        },
                        setTier = { key, tier ->
                            Graph.engine.recordFeedback(
                                key,
                                if (tier <= 2) Feedback.PROMOTED else Feedback.DEMOTED,
                                tier = tier,
                            )
                            refreshTick.intValue++
                        },
                        setMuted = { key, muted ->
                            Graph.engine.setMuted(key, muted)
                            refreshTick.intValue++
                        },
                        sendTest = ::sendTestBreakthrough,
                        resetData = {
                            Graph.profileStore.clear()
                            Graph.decisionLog.clear()
                            Graph.escalation.reset()
                            Graph.budget.reset()
                            refreshTick.intValue++
                        },
                    ),
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refreshTick.intValue++
    }

    // ---- state ---------------------------------------------------------------

    private fun readState(): SetupState {
        val settings = Graph.settings
        return SetupState(
            listenerEnabled = Permissions.listenerEnabled(this),
            policyAccess = Graph.breakthrough.hasPolicyAccess(),
            postNotifications = Graph.breakthrough.canPostNotifications(),
            contactsGranted = Graph.contacts.hasPermission(),
            bypassActive = Graph.breakthrough.bypassActive(),
            dndActive = Graph.contextProvider.isDndActive(),
            enabled = settings.enabled,
            onlyDuringDnd = settings.onlyDuringDnd,
            learningEnabled = settings.learningEnabled,
            sensitivity = settings.sensitivity,
            interruptsRemaining = Graph.budget.remaining(System.currentTimeMillis()),
        )
    }

    private fun readPeople(): List<SenderProfile> =
        Graph.profileStore.all()
            .sortedWith(compareBy({ it.effectiveTier }, { -it.relationshipScore }))
            .take(50)

    // ---- actions -------------------------------------------------------------

    private fun requestPostNotifications() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        permissionLauncher.launch(arrayOf(Manifest.permission.POST_NOTIFICATIONS))
    }

    private fun requestContacts() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_CONTACTS)
            == PackageManager.PERMISSION_GRANTED
        ) return
        permissionLauncher.launch(arrayOf(Manifest.permission.READ_CONTACTS))
    }

    /**
     * End-to-end check of the part that is easy to get silently wrong: whether a
     * notification posted on the bypass channel is actually audible during DND. Runs a
     * synthetic event through the real policy, but against a throwaway profile so it
     * cannot teach the engine anything.
     */
    private fun sendTestBreakthrough() {
        Graph.breakthrough.ensureChannels()
        val event = NotificationEvent(
            appName = packageName,
            senderId = "attentionai:self-test",
            senderName = getString(com.attentionai.R.string.test_sender),
            content = getString(com.attentionai.R.string.test_message),
        )
        val profile = SenderProfile(
            senderKey = "attentionai:self-test",
            tier = 1,
            relationshipScore = 0.8,
            peakRelationship = 0.8,
            isStarred = true,
        )
        val decision: Decision = Graph.engine.policy.analyze(
            event = event,
            profile = profile,
            atMs = System.currentTimeMillis(),
        )
        Graph.breakthrough.post(
            senderKey = "attentionai:self-test",
            senderName = event.senderName.orEmpty(),
            content = event.content,
            decision = if (decision.action == Action.INTERRUPT) decision
            else decision.copy(action = Action.INTERRUPT),
            original = null,
        )
        refreshTick.intValue++
    }
}

/** Everything the home screen needs to render, gathered in one place. */
data class SetupState(
    val listenerEnabled: Boolean,
    val policyAccess: Boolean,
    val postNotifications: Boolean,
    val contactsGranted: Boolean,
    val bypassActive: Boolean,
    val dndActive: Boolean,
    val enabled: Boolean,
    val onlyDuringDnd: Boolean,
    val learningEnabled: Boolean,
    val sensitivity: Sensitivity,
    val interruptsRemaining: Int,
) {
    /** All three hard requirements met -- anything less and breakthroughs will not fire. */
    val ready: Boolean get() = listenerEnabled && policyAccess && postNotifications
}

data class HomeActions(
    val openListenerSettings: () -> Unit,
    val openPolicySettings: () -> Unit,
    val requestPostNotifications: () -> Unit,
    val requestContacts: () -> Unit,
    val setEnabled: (Boolean) -> Unit,
    val setOnlyDuringDnd: (Boolean) -> Unit,
    val setLearning: (Boolean) -> Unit,
    val setSensitivity: (Sensitivity) -> Unit,
    val setTier: (String, Int) -> Unit,
    val setMuted: (String, Boolean) -> Unit,
    val sendTest: () -> Unit,
    val resetData: () -> Unit,
)

/** Exposed for the notification-id round trip in tests and previews. */
internal fun testNotificationId(): Int = Breakthrough.notificationIdFor("attentionai:self-test")
