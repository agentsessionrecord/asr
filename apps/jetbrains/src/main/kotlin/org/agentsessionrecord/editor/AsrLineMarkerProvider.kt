package org.agentsessionrecord.editor

import com.intellij.codeInsight.daemon.LineMarkerInfo
import com.intellij.codeInsight.daemon.LineMarkerProvider
import com.intellij.icons.AllIcons
import com.intellij.ide.trustedProjects.TrustedProjects
import com.intellij.openapi.editor.markup.GutterIconRenderer
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.util.TextRange
import com.intellij.psi.PsiDocumentManager
import com.intellij.psi.PsiElement
import com.intellij.psi.PsiWhiteSpace

class AsrLineMarkerProvider : LineMarkerProvider {
    override fun getLineMarkerInfo(element: PsiElement): LineMarkerInfo<*>? {
        if (element.firstChild != null || element is PsiWhiteSpace || element.textLength == 0 || !TrustedProjects.isProjectTrusted(element.project) || AsrSettings.get().state.sessions.isEmpty()) return null
        val document = PsiDocumentManager.getInstance(element.project).getDocument(element.containingFile) ?: return null
        val start = element.textRange.startOffset
        val line = document.getLineNumber(start)
        if (!document.getText(TextRange(document.getLineStartOffset(line), start)).isBlank()) return null
        return LineMarkerInfo(element, TextRange(start, start + 1), AllIcons.Vcs.History,
            { "Show ASR sessions behind this line" },
            { _, source ->
                val editor = FileEditorManager.getInstance(source.project).selectedTextEditor
                if (editor != null && editor.document === document) ShowLineAction.show(source.project, editor, line)
            }, GutterIconRenderer.Alignment.RIGHT, { "ASR sessions behind this line" })
    }
}
