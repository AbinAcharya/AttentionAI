package com.attentionai.data

import android.content.Context
import android.content.SharedPreferences

/**
 * User-adjustable settings, on SharedPreferences.
 *
 * Only a handful of knobs are exposed. The scoring weights are not user-editable --
 * they are validated against a scenario corpus, and letting a slider move them would
 * mean the tested behaviour and the shipped behaviour are different things.
 */
class Settings(context: Context) {

    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    /** Master switch. When off, the service reads nothing and posts nothing. */
    var enabled: Boolean
        get() = prefs.getBoolean(KEY_ENABLED, true)
        set(value) = prefs.edit().putBoolean(KEY_ENABLED, value).apply()

    /**
     * When true (default), breakthroughs are only produced while Do Not Disturb is
     * actually on. Outside DND the system notification is already visible and
     * mirroring it would just be a duplicate.
     */
    var onlyDuringDnd: Boolean
        get() = prefs.getBoolean(KEY_ONLY_DND, true)
        set(value) = prefs.edit().putBoolean(KEY_ONLY_DND, value).apply()

    /** Whether observed opens/dismissals adjust relationship scores. */
    var learningEnabled: Boolean
        get() = prefs.getBoolean(KEY_LEARNING, true)
        set(value) = prefs.edit().putBoolean(KEY_LEARNING, value).apply()

    /** Sensitivity: shifts the interrupt threshold without touching the model. */
    var sensitivity: Sensitivity
        get() = Sensitivity.fromKey(prefs.getString(KEY_SENSITIVITY, null))
        set(value) = prefs.edit().putString(KEY_SENSITIVITY, value.key).apply()

    var contactsImported: Boolean
        get() = prefs.getBoolean(KEY_CONTACTS_IMPORTED, false)
        set(value) = prefs.edit().putBoolean(KEY_CONTACTS_IMPORTED, value).apply()

    var onboardingComplete: Boolean
        get() = prefs.getBoolean(KEY_ONBOARDED, false)
        set(value) = prefs.edit().putBoolean(KEY_ONBOARDED, value).apply()

    fun resetAll() {
        prefs.edit().clear().apply()
    }

    companion object {
        private const val NAME = "attentionai_settings"
        private const val KEY_ENABLED = "enabled"
        private const val KEY_ONLY_DND = "only_during_dnd"
        private const val KEY_LEARNING = "learning_enabled"
        private const val KEY_SENSITIVITY = "sensitivity"
        private const val KEY_CONTACTS_IMPORTED = "contacts_imported"
        private const val KEY_ONBOARDED = "onboarding_complete"
    }
}

/**
 * Threshold offsets, not weight changes. Moving the bar is understandable and
 * reversible; re-weighting the model behind the user's back is neither.
 */
enum class Sensitivity(val key: String, val label: String, val thresholdDelta: Double) {
    STRICT("strict", "Strict — almost nothing gets through", 0.10),
    BALANCED("balanced", "Balanced — recommended", 0.0),
    RELAXED("relaxed", "Relaxed — let more through", -0.10);

    companion object {
        fun fromKey(key: String?): Sensitivity =
            entries.firstOrNull { it.key == key } ?: BALANCED
    }
}
