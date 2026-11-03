package org.agentsessionrecord.editor

import com.intellij.ide.trustedProjects.TrustedProjects
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.DialogWrapper
import com.intellij.openapi.ui.Messages
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import com.intellij.openapi.util.Disposer
import javax.swing.JComponent

object SessionViewer {
    fun open(project: Project, reference: String) {
        if (!TrustedProjects.isProjectTrusted(project)) return
        ProgressManager.getInstance().run(object : Task.Backgroundable(project, "Open ASR session", true) {
            override fun run(indicator: ProgressIndicator) {
                try {
                    val path = AsrClient.findSession(AsrSettings.get().state.sessions, reference)
                    val template = SessionViewer::class.java.getResourceAsStream("/viewer.html")?.bufferedReader()?.use { it.readText() } ?: error("Build the bundled viewer first.")
                    val html = AsrClient.viewerHtml(template, path)
                    indicator.checkCanceled()
                    ApplicationManager.getApplication().invokeLater {
                        if (project.isDisposed || indicator.isCanceled) return@invokeLater
                        if (!JBCefApp.isSupported()) {
                            Messages.showErrorDialog(project, "The offline viewer requires a JetBrains Runtime with JCEF. Use the bundled runtime.", "ASR Sessions")
                        } else ViewerDialog(project, html).show()
                    }
                } catch (cancelled: com.intellij.openapi.progress.ProcessCanceledException) {
                    throw cancelled
                } catch (error: Exception) {
                    ApplicationManager.getApplication().invokeLater {
                        if (!project.isDisposed && !indicator.isCanceled) Messages.showErrorDialog(project, "Session is unresolved, ambiguous, unavailable or above the viewer size limit.", "ASR Sessions")
                    }
                }
            }
        })
    }
    private class ViewerDialog(project: Project, private val html: String) : DialogWrapper(project, false) {
        private val browser = JBCefBrowser()
        init {
            title = "ASR Session"
            isModal = false
            Disposer.register(disposable, browser)
            init()
            setSize(1200, 850)
            browser.loadHTML(html)
        }
        override fun createCenterPanel(): JComponent = browser.component
        override fun createActions(): Array<javax.swing.Action> = arrayOf(cancelAction)
    }
}
