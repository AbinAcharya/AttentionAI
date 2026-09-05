package com.attentionai.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.attentionai.core.Action
import com.attentionai.core.SenderProfile
import com.attentionai.data.DecisionRecord
import com.attentionai.data.Sensitivity
import kotlinx.coroutines.flow.StateFlow
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    state: SetupState,
    people: List<SenderProfile>,
    decisions: StateFlow<List<DecisionRecord>>,
    actions: HomeActions,
) {
    val recent by decisions.collectAsStateWithLifecycle()

    Scaffold(
        topBar = { TopAppBar(title = { Text("AttentionAI") }) },
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { Spacer(Modifier.height(4.dp)) }
            item { StatusCard(state) }
            if (!state.ready) item { SetupCard(state, actions) }
            item { ControlsCard(state, actions) }
            item { RecentCard(recent) }
            item { PeopleCard(people, actions) }
            item { MaintenanceCard(state, actions) }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Composable
private fun StatusCard(state: SetupState) {
    val headline = when {
        !state.enabled -> "Paused"
        !state.ready -> "Setup incomplete"
        !state.bypassActive -> "Waiting for Do Not Disturb access"
        else -> "Active"
    }
    val detail = when {
        !state.enabled -> "Nothing is being read or posted."
        !state.ready -> "Grant the permissions below — until then, nothing breaks through."
        !state.bypassActive ->
            "The breakthrough channel cannot bypass DND yet. Reopen this screen after " +
                "granting Do Not Disturb access and it will be rebuilt."
        state.dndActive -> "Do Not Disturb is on. ${state.interruptsRemaining} interrupts left this hour."
        state.onlyDuringDnd -> "Do Not Disturb is off, so nothing is being filtered right now."
        else -> "Filtering everything, DND or not."
    }

    Card(colors = CardDefaults.cardColors()) {
        Column(Modifier.padding(16.dp)) {
            Text(headline, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(6.dp))
            Text(detail, style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
private fun SetupCard(state: SetupState, actions: HomeActions) {
    Card {
        Column(Modifier.padding(16.dp)) {
            Text("Permissions", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(4.dp))
            Text(
                "Two of these are special-access grants; Android only lets you turn them " +
                    "on from system Settings.",
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.height(12.dp))

            PermissionRow(
                title = "Notification access",
                description = "Lets the app read incoming notifications so it can score them.",
                granted = state.listenerEnabled,
                onGrant = actions.openListenerSettings,
            )
            PermissionRow(
                title = "Do Not Disturb access",
                description = "Required for a notification to be heard while DND is on. " +
                    "Without it the app runs but stays silent.",
                granted = state.policyAccess,
                onGrant = actions.openPolicySettings,
            )
            PermissionRow(
                title = "Post notifications",
                description = "The breakthrough is a notification this app posts itself.",
                granted = state.postNotifications,
                onGrant = actions.requestPostNotifications,
            )
            PermissionRow(
                title = "Contacts (optional)",
                description = "Gives new senders a sensible starting priority instead of " +
                    "treating everyone as a stranger.",
                granted = state.contactsGranted,
                onGrant = actions.requestContacts,
            )
        }
    }
}

@Composable
private fun PermissionRow(
    title: String,
    description: String,
    granted: Boolean,
    onGrant: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(description, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.width(12.dp))
        if (granted) {
            Text("Granted", style = MaterialTheme.typography.labelLarge)
        } else {
            FilledTonalButton(onClick = onGrant) { Text("Grant") }
        }
    }
}

@Composable
private fun ControlsCard(state: SetupState, actions: HomeActions) {
    Card {
        Column(Modifier.padding(16.dp)) {
            Text("Behaviour", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))

            ToggleRow("Enabled", "Master switch.", state.enabled, actions.setEnabled)
            ToggleRow(
                "Only during Do Not Disturb",
                "Outside DND the system already shows notifications, so mirroring would duplicate them.",
                state.onlyDuringDnd,
                actions.setOnlyDuringDnd,
            )
            ToggleRow(
                "Learn from my behaviour",
                "Opening a breakthrough raises that person's priority; swiping it away lowers it.",
                state.learningEnabled,
                actions.setLearning,
            )

            Spacer(Modifier.height(12.dp))
            Text("Sensitivity", style = MaterialTheme.typography.bodyLarge)
            Text(
                "Moves the bar, not the model.",
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Sensitivity.entries.forEach { option ->
                    FilterChip(
                        selected = state.sensitivity == option,
                        onClick = { actions.setSensitivity(option) },
                        label = { Text(option.key.replaceFirstChar { it.uppercase() }) },
                    )
                }
            }
        }
    }
}

@Composable
private fun ToggleRow(
    title: String,
    description: String,
    checked: Boolean,
    onChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(description, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.width(12.dp))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun RecentCard(recent: List<DecisionRecord>) {
    val formatter = SimpleDateFormat("HH:mm", Locale.getDefault())
    Card {
        Column(Modifier.padding(16.dp)) {
            Text("Recent decisions", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(4.dp))
            Text(
                "Kept in memory only, and message text is never stored.",
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.height(8.dp))

            if (recent.isEmpty()) {
                Text("Nothing scored yet.", style = MaterialTheme.typography.bodyMedium)
            } else {
                recent.take(15).forEachIndexed { index, record ->
                    if (index > 0) HorizontalDivider()
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(record.senderName, style = MaterialTheme.typography.bodyLarge)
                            Text(
                                record.reasons.take(2).joinToString(" · ").ifBlank { "no strong signals" },
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(actionLabel(record.action), style = MaterialTheme.typography.labelLarge)
                            Text(
                                "${record.scorePercent}% · ${formatter.format(Date(record.atMs))}",
                                style = MaterialTheme.typography.bodySmall,
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun PeopleCard(people: List<SenderProfile>, actions: HomeActions) {
    Card {
        Column(Modifier.padding(16.dp)) {
            Text("People", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(4.dp))
            Text(
                "Anything you set here overrides what the app has learned.",
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.height(8.dp))

            if (people.isEmpty()) {
                Text("No senders seen yet.", style = MaterialTheme.typography.bodyMedium)
            } else {
                people.forEachIndexed { index, profile ->
                    if (index > 0) HorizontalDivider()
                    PersonRow(profile, actions)
                }
            }
        }
    }
}

@Composable
private fun PersonRow(profile: SenderProfile, actions: HomeActions) {
    Column(Modifier.padding(vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    profile.displayName ?: profile.senderKey.take(14),
                    style = MaterialTheme.typography.bodyLarge,
                )
                Text(
                    "tier ${profile.effectiveTier} · bond ${Math.round(profile.relationshipScore * 100)}%" +
                        if (profile.muted) " · muted" else "",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            TextButton(onClick = { actions.setMuted(profile.senderKey, !profile.muted) }) {
                Text(if (profile.muted) "Unmute" else "Mute")
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(1, 3, 5).forEach { tier ->
                FilterChip(
                    selected = profile.effectiveTier == tier,
                    onClick = { actions.setTier(profile.senderKey, tier) },
                    label = {
                        Text(
                            when (tier) {
                                1 -> "Always"
                                3 -> "Normal"
                                else -> "Rarely"
                            }
                        )
                    },
                )
            }
        }
    }
}

@Composable
private fun MaintenanceCard(state: SetupState, actions: HomeActions) {
    Card {
        Column(Modifier.padding(16.dp)) {
            Text("Check and reset", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            Text(
                "Turn on Do Not Disturb, then send a test. If you do not hear it, Do Not " +
                    "Disturb access is not granted.",
                style = MaterialTheme.typography.bodySmall,
            )
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                FilledTonalButton(onClick = actions.sendTest, enabled = state.postNotifications) {
                    Text("Send test breakthrough")
                }
                OutlinedButton(onClick = actions.resetData) { Text("Reset learned data") }
            }
        }
    }
}

private fun actionLabel(action: Action): String = when (action) {
    Action.INTERRUPT -> "Broke through"
    Action.SHOW_SILENTLY -> "Silent"
    Action.DEFER -> "Held"
}
