package org.agentsessionrecord.editor

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.options.Configurable
import java.awt.BorderLayout
import java.awt.GridLayout
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JScrollPane
import javax.swing.JTextArea
import javax.swing.JTextField

class SettingsState {
    var executable: String = "asr"
    var sessions: MutableList<String> = mutableListOf()
    var annotations: MutableList<String> = mutableListOf()
}

@Service(Service.Level.APP)
@State(name = "AsrSessions", storages = [Storage("asr-sessions.xml")])
class AsrSettings : PersistentStateComponent<SettingsState> {
    private var value = SettingsState()
    override fun getState(): SettingsState = value
    override fun loadState(state: SettingsState) { value = state }
    companion object {
        fun get(): AsrSettings = ApplicationManager.getApplication().getService(AsrSettings::class.java)
    }
}

class AsrConfigurable : Configurable {
    private val executable = JTextField()
    private val sessions = JTextArea(6, 60)
    private val annotations = JTextArea(4, 60)
    override fun getDisplayName(): String = "ASR Sessions"
    override fun createComponent(): JComponent {
        val panel = JPanel(GridLayout(3, 1, 8, 8))
        fun row(label: String, field: JComponent): JPanel = JPanel(BorderLayout(4, 4)).apply {
            add(JLabel(label), BorderLayout.NORTH)
            add(field, BorderLayout.CENTER)
        }
        panel.add(row("Installed asr executable (no shell arguments)", executable))
        panel.add(row("Absolute session files or directories, one per line", JScrollPane(sessions)))
        panel.add(row("Absolute annotation files, one per line", JScrollPane(annotations)))
        reset()
        return panel
    }
    private fun lines(text: String): MutableList<String> = text.lines().filter { it.isNotEmpty() }.toMutableList()
    override fun isModified(): Boolean = AsrSettings.get().state.let {
        it.executable != executable.text || it.sessions != lines(sessions.text) || it.annotations != lines(annotations.text)
    }
    override fun apply() {
        val state = SettingsState().also {
            it.executable = executable.text
            it.sessions = lines(sessions.text)
            it.annotations = lines(annotations.text)
        }
        AsrClient.validate(state)
        AsrSettings.get().loadState(state)
    }
    override fun reset() { AsrSettings.get().state.let {
        executable.text = it.executable
        sessions.text = it.sessions.joinToString("\n")
        annotations.text = it.annotations.joinToString("\n")
    } }
}
