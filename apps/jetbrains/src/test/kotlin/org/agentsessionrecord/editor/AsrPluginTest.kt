package org.agentsessionrecord.editor

import com.google.gson.JsonParser
import com.intellij.codeInsight.daemon.LineMarkerProviders
import com.intellij.ide.trustedProjects.TrustedProjects
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.vfs.LocalFileSystem
import com.intellij.psi.util.PsiTreeUtil
import com.intellij.testFramework.fixtures.BasePlatformTestCase
import java.nio.file.Files
import java.nio.file.Path

class AsrPluginTest : BasePlatformTestCase() {
    private lateinit var fixture: com.google.gson.JsonObject
    private lateinit var settings: SettingsState
    override fun setUp() {
        super.setUp()
        fixture = JsonParser.parseString(Files.readString(Path.of(System.getProperty("asr.test.fixture"), "fixture.json"))).asJsonObject
        settings = SettingsState().also {
            it.executable = System.getProperty("asr.test.cli")
            it.sessions.add(fixture["store"].asString)
        }
        AsrSettings.get().loadState(settings)
        TrustedProjects.setProjectTrusted(project, true)
    }
    override fun tearDown() {
        try { AsrSettings.get().loadState(SettingsState()) } finally { super.tearDown() }
    }
    private fun report() = AsrClient.blame(settings, Path.of(fixture["repo"].asString), Path.of(fixture["file"].asString), 1)
    fun testRegisteredActionAndRealBlameEvidence() {
        assertNotNull(ActionManager.getInstance().getAction("ASR.ShowLine"))
        val result = report()
        assertEquals("matched", result["editStatus"].asString)
        assertEquals(1, result["editedBy"].asJsonArray.size())
        assertEquals(1, result["committedBy"].asJsonArray.size())
        val text = AsrClient.reportText(result)
        for (expected in listOf("Edited by", "Committed by", "synthetic-served", "9007199254740993", "approvals", "not_recorded", "Use seven")) assertTrue(expected, text.contains(expected))
        assertEquals(listOf(fixture["reference"].asString), AsrClient.sessions(result))
    }
    fun testConfiguredFileAndDirtyBufferSafety() {
        val file = LocalFileSystem.getInstance().refreshAndFindFileByNioFile(Path.of(fixture["file"].asString))!!
        myFixture.configureFromExistingVirtualFile(file)
        val document = myFixture.editor.document
        assertEquals("matched", ShowLineAction.lookup(project, document, 0)["editStatus"].asString)
        WriteCommandAction.runWriteCommandAction(project) { document.insertString(0, "// unsaved\n") }
        try {
            ShowLineAction.lookup(project, document, 0)
            fail("Dirty buffers must not receive stale line evidence")
        } catch (error: IllegalArgumentException) { assertTrue(error.message!!.contains("Save the file")) }
        FileDocumentManager.getInstance().reloadFromDisk(document)
    }
    fun testGutterProviderUsesFirstLeafOfLine() {
        myFixture.configureByText("parser.txt", "recorded line\n")
        val element = PsiTreeUtil.getDeepestFirst(myFixture.file) ?: myFixture.file.firstChild
        assertNotNull(element)
        val provider = LineMarkerProviders.getInstance().allForLanguageOrAny(myFixture.file.language).filterIsInstance<AsrLineMarkerProvider>().single()
        assertNotNull(provider.getLineMarkerInfo(element))
    }
    fun testReferenceResolutionAndViewerKeepsContentInert() {
        val encoded = JsonParser.parseString("""{"type":"session","formatVersion":"0.1","agent":{"name":"com.example.agent"},"sessionId":"x y\t\u0085"}""").asJsonObject
        assertEquals("com.example.agent:x%20y%09%C2%85", AsrClient.reference(encoded))
        val file = AsrClient.findSession(settings.sessions, fixture["reference"].asString + "#change")
        assertEquals(fixture["session"].asString, file.toString())
        val template = SessionViewer::class.java.getResourceAsStream("/viewer.html")!!.bufferedReader().use { it.readText() }
        val html = AsrClient.viewerHtml(template, file)
        assertTrue(html.contains("connect-src 'none'"))
        assertTrue(html.contains("input.dispatchEvent(new Event('change'))"))
        assertFalse(html.contains("<script>globalThis.injected"))
        try { AsrClient.findSession(settings.sessions, "com.example.agent:missing"); fail("Missing session must remain unresolved") }
        catch (error: IllegalArgumentException) { assertTrue(error.message!!.contains("unresolved")) }
    }
    fun testEverySampleAndExampleStreamThroughRealBlame() {
        var count = 0
        val root = Path.of(System.getProperty("asr.test.root"))
        for (dir in listOf("samples", "examples")) Files.walk(root.resolve(dir)).use { files -> files.filter { Files.isRegularFile(it) && it.toString().endsWith(".jsonl") && !it.toString().endsWith(".annotations.jsonl") }.forEach { file ->
            val header = Files.newBufferedReader(file).use { it.readLine() }
            if (JsonParser.parseString(header).asJsonObject["type"].asString == "session") {
                val source = SettingsState().also { it.executable = settings.executable; it.sessions.add(file.toString()) }
                val result = AsrClient.blame(source, Path.of(fixture["repo"].asString), Path.of(fixture["file"].asString), 1)
                assertEquals(0, result["editedBy"].asJsonArray.size())
                assertEquals(0, result["committedBy"].asJsonArray.size())
                count++
            }
        } }
        assertTrue(count >= 17)
    }
}
