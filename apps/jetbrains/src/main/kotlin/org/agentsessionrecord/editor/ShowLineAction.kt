package org.agentsessionrecord.editor

import com.google.gson.JsonObject
import com.intellij.ide.trustedProjects.TrustedProjects
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.editor.Document
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.ui.popup.JBPopupFactory
import java.awt.BorderLayout
import java.nio.file.Path
import javax.swing.JButton
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JScrollPane
import javax.swing.JTextArea

class ShowLineAction : AnAction() {
    override fun update(event: AnActionEvent) {
        val project = event.project
        val editor = event.getData(CommonDataKeys.EDITOR)
        event.presentation.isEnabledAndVisible = project != null && editor != null && TrustedProjects.isProjectTrusted(project)
    }
    override fun actionPerformed(event: AnActionEvent) {
        val project = event.project ?: return
        val editor = event.getData(CommonDataKeys.EDITOR) ?: return
        show(project, editor, editor.caretModel.logicalPosition.line)
    }
    companion object {
        fun lookup(project: Project, document: Document, line: Int, indicator: ProgressIndicator? = null): JsonObject {
            require(TrustedProjects.isProjectTrusted(project)) { "Trust the project before running ASR." }
            val manager = FileDocumentManager.getInstance()
            require(!manager.isDocumentUnsaved(document)) { "Save the file before looking up line evidence." }
            val file = manager.getFile(document)
            require(file != null && file.isInLocalFileSystem) { "ASR requires a local file." }
            val path = Path.of(file.path)
            val state = AsrSettings.get().state
            return AsrClient.blame(state, AsrClient.gitRoot(path, indicator), path, line + 1, indicator)
        }
        fun show(project: Project, editor: Editor, line: Int) {
            if (!TrustedProjects.isProjectTrusted(project)) return
            val document = editor.document
            val stamp = document.modificationStamp
            ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Find ASR line evidence", true) {
                override fun run(indicator: ProgressIndicator) {
                    try {
                        val report = lookup(project, document, line, indicator)
                        ApplicationManager.getApplication().invokeLater {
                            if (project.isDisposed || editor.isDisposed || indicator.isCanceled) return@invokeLater
                            if (document.modificationStamp != stamp || FileDocumentManager.getInstance().isDocumentUnsaved(document)) return@invokeLater
                            val content = JTextArea(AsrClient.reportText(report), 24, 95).apply { isEditable = false; caretPosition = 0 }
                            val panel = JPanel(BorderLayout()).apply {
                                add(JScrollPane(content), BorderLayout.CENTER)
                                val buttons = JPanel()
                                buttons.add(JLabel("Open recorded session:"))
                                AsrClient.sessions(report).forEach { reference ->
                                    buttons.add(JButton(reference).apply { addActionListener { SessionViewer.open(project, reference) } })
                                }
                                add(buttons, BorderLayout.SOUTH)
                            }
                            JBPopupFactory.getInstance().createComponentPopupBuilder(panel, content).setTitle("ASR Line Evidence").setResizable(true).setMovable(true).setRequestFocus(true).createPopup().showInBestPositionFor(editor)
                        }
                    } catch (cancelled: com.intellij.openapi.progress.ProcessCanceledException) {
                        throw cancelled
                    } catch (error: Exception) {
                        ApplicationManager.getApplication().invokeLater {
                            if (!project.isDisposed && !indicator.isCanceled) Messages.showErrorDialog(project, "ASR lookup failed. Check saved file, executable, stores and Git repository.", "ASR Sessions")
                        }
                    }
                }
            })
        }
    }
}
