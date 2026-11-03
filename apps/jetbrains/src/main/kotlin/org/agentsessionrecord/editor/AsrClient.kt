package org.agentsessionrecord.editor

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.execution.process.CapturingProcessHandler
import com.intellij.execution.process.ProcessAdapter
import com.intellij.execution.process.ProcessEvent
import com.intellij.openapi.util.Key
import java.util.concurrent.atomic.AtomicInteger
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.ProgressIndicator
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.Path
import java.util.Base64
import java.security.SecureRandom

object AsrClient {
    private const val MAX_INPUT = 64L * 1024 * 1024
    fun validate(settings: SettingsState) {
        require(settings.executable.isNotEmpty() && !settings.executable.contains('\u0000')) { "Set the installed ASR executable in Settings." }
        require(settings.sessions.isNotEmpty()) { "Set local ASR session stores in Settings." }
        require((settings.sessions + settings.annotations).all { Path.of(it).isAbsolute && !it.contains('\u0000') }) { "ASR stores must use absolute local paths." }
    }
    fun blame(settings: SettingsState, repo: Path, file: Path, line: Int, indicator: ProgressIndicator? = null): JsonObject {
        validate(settings)
        require(line > 0) { "Invalid line" }
        val args = mutableListOf("blame", file.toString(), "--line", line.toString(), "--repo", repo.toString())
        settings.sessions.forEach { args.addAll(listOf("--sessions", it)) }
        settings.annotations.forEach { args.addAll(listOf("--annotations", it)) }
        return parseReport(run(settings.executable, args, repo, indicator))
    }
    fun gitRoot(file: Path, indicator: ProgressIndicator? = null): Path = Path.of(run("git", listOf("-C", file.parent.toString(), "rev-parse", "--show-toplevel"), file.parent, indicator).trim())
    private fun run(executable: String, args: List<String>, cwd: Path, indicator: ProgressIndicator?): String {
        val command = GeneralCommandLine(listOf(executable) + args).withWorkDirectory(cwd.toFile()).withCharset(Charsets.UTF_8)
        val handler = CapturingProcessHandler(command)
        val size = AtomicInteger()
        handler.addProcessListener(object : ProcessAdapter() {
            override fun onTextAvailable(event: ProcessEvent, outputType: Key<*>) {
                if (size.addAndGet(event.text.length) > 16 * 1024 * 1024) handler.destroyProcess()
            }
        })
        val result = if (indicator == null) handler.runProcess(15000, true) else handler.runProcessWithProgressIndicator(indicator, 15000, true)
        require(size.get() <= 16 * 1024 * 1024 && !result.isTimeout && !result.isCancelled && result.exitCode == 0) { "ASR lookup failed. Check the executable, Git repository, stores and timeout." }
        require(result.stdout.length <= 16 * 1024 * 1024) { "ASR output exceeds 16 MiB." }
        return result.stdout
    }
    fun parseReport(text: String): JsonObject {
        val value = JsonParser.parseString(text).asJsonObject
        require(value["editStatus"]?.isJsonPrimitive == true && listOf("editedBy", "committedBy", "alternatives", "sessions", "relationships").all { value[it]?.isJsonArray == true }) { "Unsupported asr blame output" }
        return value
    }
    fun reportText(report: JsonObject): String {
        fun group(label: String, key: String): String {
            val values = report[key].asJsonArray
            return "$label\n" + if (values.isEmpty) "Unknown. No matching recorded evidence." else values.joinToString("\n") { it.toString() }
        }
        return listOf("ASR line evidence", "Edit status: ${report["editStatus"].asString}",
            "Matches are recorded evidence, not proof of authorship.", group("Edited by", "editedBy"), group("Committed by", "committedBy"),
            group("Earlier alternatives", "alternatives"), "Session losses, gaps, diagnostics and unresolved references\n${report["sessions"]}",
            "Source errors\n${report["sourceErrors"]}", "Related sessions\n${report["relationships"]}").joinToString("\n\n")
    }
    fun sessions(report: JsonObject): List<String> = listOf("editedBy", "committedBy").flatMap { key ->
        report[key].asJsonArray.mapNotNull { it.asJsonObject["session"]?.takeIf { v -> v.isJsonPrimitive }?.asString }
    }.distinct()
    fun reference(header: JsonObject): String? {
        if (header["type"]?.asString != "session" || header["formatVersion"]?.asString != "0.1") return null
        fun encode(value: String): String = buildString {
            value.forEach { ch ->
                if (ch == '%' || ch == ':' || ch == '#' || ch == ' ' || Character.isISOControl(ch)) {
                    ch.toString().toByteArray(Charsets.UTF_8).forEach { append("%%%02X".format(it.toInt() and 255)) }
                } else append(ch)
            }
        }
        val agent = header["agent"]?.asJsonObject?.get("name")?.asString ?: return null
        val id = header["sessionId"]?.asString ?: return null
        return listOfNotNull(agent, header["namespace"]?.asString?.let(::encode), encode(id)).joinToString(":")
    }
    fun findSession(roots: List<String>, reference: String): Path {
        val matches = linkedSetOf<Path>()
        var seen = 0
        for (root in roots) {
            Files.walk(Path.of(root), 33).use { paths -> paths.forEach { file ->
                ProgressManager.checkCanceled()
                require(++seen <= 10000) { "ASR store scan limit exceeded. Configure a smaller store." }
                if (Files.isRegularFile(file, NOFOLLOW_LINKS) && file.toString().endsWith(".jsonl") && !file.toString().endsWith(".annotations.jsonl")) {
                    Files.newInputStream(file).use { input ->
                        val bytes = input.readNBytes(65536)
                        val end = bytes.indexOf(10)
                        if (end >= 0) {
                            val header = runCatching { JsonParser.parseString(String(bytes, 0, end, Charsets.UTF_8)).asJsonObject }.getOrNull()
                            if (header != null && runCatching { reference(header) }.getOrNull() == reference.substringBefore('#')) matches.add(file.toAbsolutePath().normalize())
                        }
                    }
                }
            } }
        }
        require(matches.size == 1) { if (matches.isEmpty()) "Session is unresolved in the configured store." else "Session reference is ambiguous in the configured store." }
        return matches.single()
    }
    fun viewerHtml(template: String, file: Path): String {
        require(Files.isRegularFile(file, NOFOLLOW_LINKS) && Files.size(file) <= MAX_INPUT) { "Viewer input must be a regular file of at most 64 MiB." }
        val encoded = Base64.getEncoder().encodeToString(Files.readAllBytes(file))
        val nonce = ByteArray(24).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
        val policy = """<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-$nonce'; style-src 'unsafe-inline'; worker-src blob:; connect-src 'none'; img-src 'none'; frame-src 'none'; form-action 'none'; base-uri 'none'">"""
        val loader = """<script nonce="$nonce">const data=atob('$encoded');const bytes=Uint8Array.from(data,c=>c.charCodeAt(0));const transfer=new DataTransfer();transfer.items.add(new File([bytes],'session.jsonl'));const input=document.getElementById('files');input.files=transfer.files;input.dispatchEvent(new Event('change'));</script>"""
        return template.replace("<head>", "<head>$policy").replace("<script>", "<script nonce=\"$nonce\">").replace("</body>", "$loader</body>")
    }
}
