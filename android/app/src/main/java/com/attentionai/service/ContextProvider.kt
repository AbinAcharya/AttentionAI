package com.attentionai.service

import android.app.NotificationManager
import android.app.UiModeManager
import android.content.Context
import android.content.res.Configuration
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.BatteryManager
import android.os.PowerManager
import com.attentionai.core.UserContext
import java.util.Calendar

/**
 * Reads the user's current situation from real system state.
 *
 * Every field here comes from something the OS actually reports. Fields the app has no
 * permission to know -- calendar busy, precise location -- are left at their defaults
 * rather than guessed at, because a fabricated signal is worse than a missing one: the
 * policy would weight it as if it were true.
 */
class ContextProvider(context: Context) {

    private val appContext = context.applicationContext
    private val notificationManager =
        appContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
    private val powerManager =
        appContext.getSystemService(Context.POWER_SERVICE) as PowerManager
    private val audioManager =
        appContext.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val uiModeManager =
        appContext.getSystemService(Context.UI_MODE_SERVICE) as UiModeManager
    private val batteryManager =
        appContext.getSystemService(Context.BATTERY_SERVICE) as BatteryManager

    fun current(): UserContext = UserContext(
        timeOfDay = timeOfDay(),
        locationCategory = "unknown",
        calendarBusy = false,
        screenOn = runCatching { powerManager.isInteractive }.getOrDefault(true),
        batteryLevel = batteryLevel(),
        driving = isDriving(),
        headphonesConnected = headphonesConnected(),
        dndActive = isDndActive(),
    )

    /** True when any interruption filter other than "allow all" is in force. */
    fun isDndActive(): Boolean = runCatching {
        notificationManager.currentInterruptionFilter != NotificationManager.INTERRUPTION_FILTER_ALL
    }.getOrDefault(false)

    private fun timeOfDay(): String {
        val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
        return when {
            hour in 0..5 -> "sleep"
            hour in 6..17 -> "day"
            hour in 18..21 -> "evening"
            else -> "night"
        }
    }

    private fun batteryLevel(): Int = runCatching {
        batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
            .takeIf { it in 0..100 } ?: 100
    }.getOrDefault(100)

    private fun isDriving(): Boolean = runCatching {
        uiModeManager.currentModeType == Configuration.UI_MODE_TYPE_CAR
    }.getOrDefault(false)

    private fun headphonesConnected(): Boolean = runCatching {
        audioManager.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any { device ->
            device.type in setOf(
                AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
                AudioDeviceInfo.TYPE_WIRED_HEADSET,
                AudioDeviceInfo.TYPE_BLUETOOTH_A2DP,
                AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
                AudioDeviceInfo.TYPE_USB_HEADSET,
            )
        }
    }.getOrDefault(false)
}
