package com.attentionai

import android.app.Application
import android.content.Context
import com.attentionai.core.AttentionEngine
import com.attentionai.core.EscalationTracker
import com.attentionai.core.InterruptBudget
import com.attentionai.core.NotificationPolicy
import com.attentionai.core.PolicyConfig
import com.attentionai.data.ContactDirectory
import com.attentionai.data.DecisionLog
import com.attentionai.data.FileProfileStore
import com.attentionai.data.Settings
import com.attentionai.service.Breakthrough
import com.attentionai.service.ContextProvider
import java.io.File

class AttentionApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Graph.init(this)
    }
}

/**
 * Hand-rolled singleton graph.
 *
 * A DI framework would be one more thing to configure and one more way for a first
 * build to fail; there are eight objects here and they all live for the process
 * lifetime. The escalation tracker and interrupt budget in particular *must* be shared
 * between the listener service and the UI -- two instances would mean two independent
 * hourly budgets, which is exactly the bug this component exists to prevent.
 */
object Graph {

    @Volatile private var initialised = false

    lateinit var settings: Settings
        private set
    lateinit var profileStore: FileProfileStore
        private set
    lateinit var decisionLog: DecisionLog
        private set
    lateinit var contacts: ContactDirectory
        private set
    lateinit var breakthrough: Breakthrough
        private set
    lateinit var contextProvider: ContextProvider
        private set

    val escalation = EscalationTracker()
    val budget = InterruptBudget()

    @Volatile
    lateinit var engine: AttentionEngine
        private set

    @Synchronized
    fun init(context: Context) {
        if (initialised) return
        val app = context.applicationContext

        settings = Settings(app)
        profileStore = FileProfileStore(File(app.filesDir, "profiles.json"))
        decisionLog = DecisionLog()
        contacts = ContactDirectory(app)
        breakthrough = Breakthrough(app)
        contextProvider = ContextProvider(app)
        engine = buildEngine()

        initialised = true
    }

    /** Call after the user changes sensitivity; thresholds are baked into the policy. */
    @Synchronized
    fun rebuildEngine() {
        engine = buildEngine()
    }

    private fun buildEngine(): AttentionEngine = AttentionEngine(
        policy = NotificationPolicy(policyConfig()),
        profileStore = profileStore,
        escalation = escalation,
        budget = budget,
    )

    /**
     * Sensitivity moves the *bar*, never the weights. The weights are the part that is
     * validated against the scenario corpus; shipping user-editable weights would mean
     * the tested behaviour and the running behaviour are different things.
     */
    private fun policyConfig(): PolicyConfig {
        val delta = settings.sensitivity.thresholdDelta
        val base = PolicyConfig()
        val interrupt = (base.interruptThreshold + delta).coerceIn(0.35, 0.95)
        val silent = (base.silentThreshold + delta / 2).coerceIn(0.15, interrupt)
        return base.copy(interruptThreshold = interrupt, silentThreshold = silent)
    }
}
