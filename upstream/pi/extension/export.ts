/** Offline Agent Session Record export of the complete native session tree. */
import type { FileEntry, SessionEntry, SessionHeader } from "@earendil-works/pi-coding-agent";

type RecordValue = Record<string, unknown>;

/** Export version 3 native entries in file order, including abandoned branches. */
export function exportAgentSession(header: SessionHeader, entries: readonly SessionEntry[]): string {
	if (!header.id || header.version !== 3) throw new Error("A version 3 session header is required");
	const rows: RecordValue[] = [
		{
			type: "session",
			id: "header",
			formatVersion: "0.1",
			agent: { name: "pi" },
			sessionId: header.id,
			cwd: header.cwd,
			startedAt: header.timestamp,
			producer: { name: "pi-asr-export", version: "1", method: "native", source: "pi-session-v3" },
			missing: [
				"approvals",
				"agent_settings",
				"tools",
				"file_changes",
				"commits",
				"subagents",
				"copies",
				"media",
				"native_metadata",
				"message_author",
				"usage",
				"reasoning",
			],
		},
	];
	const used = new Set(["header"]);
	const nativeIds = new Set(entries.map((entry) => entry.id));
	const resultPositions = new Map<string, number>();
	for (const entry of entries) {
		let suffix = 0;
		const append = (record: RecordValue): void => {
			let id = typeof record.id === "string" ? record.id : suffix++ === 0 ? entry.id : `${entry.id}/${suffix}`;
			if (!id || id.length > 240 || /[\u0000-\u001f\u007f]/.test(id) || used.has(id)) id = `derived-${rows.length}`;
			while (used.has(id) || (id !== entry.id && nativeIds.has(id))) id = `derived-${id}`;
			used.add(id);
			rows.push({ ts: entry.timestamp, ...record, id });
		};
		if (entry.type === "thinking_level_change") {
			append({ type: "session_info", agentSettings: { modelSettings: { reasoningEffort: entry.thinkingLevel } } });
		} else if (entry.type === "session_info") {
			if (entry.name !== undefined) append({ type: "session_info", title: entry.name });
		} else if (entry.type === "compaction" || entry.type === "branch_summary") {
			append({
				type: "message",
				role: "user",
				author: entry.fromHook ? "hook" : "harness",
				origin: "compaction",
				content: [{ type: "text", text: entry.summary }],
			});
		} else if (entry.type === "custom_message") {
			append({
				type: "message",
				role: "user",
				author: "harness",
				origin: "injected",
				content: parts(entry.content),
			});
		} else if (entry.type === "message") {
			const message = entry.message;
			if (message.role === "assistant") {
				let inferenceId = message.responseId || `${entry.id}/inference`;
				if (inferenceId.length > 220 || /[\u0000-\u001f\u007f]/.test(inferenceId))
					inferenceId = `inference-${rows.length}`;
				while (used.has(inferenceId) || nativeIds.has(inferenceId)) inferenceId = `derived-${inferenceId}`;
				// Local harness failures can produce assistant rows without any provider request.
				const identified = Boolean(message.responseId) || !["error", "aborted"].includes(message.stopReason);
				const usage = message.usage;
				const inference: RecordValue = {
					type: "inference",
					id: inferenceId,
					model: {
						provider: message.provider,
						requested: message.model,
						...(message.responseModel ? { id: message.responseModel } : {}),
					},
					stopReason: message.rawStopReason ?? message.stopReason,
				};
				const counts: RecordValue = {};
				for (const [name, value] of Object.entries({
					cacheReadTokens: usage.cacheRead,
					cacheWriteTokens: usage.cacheWrite,
					outputTokens: usage.output,
					reasoningTokens: usage.reasoning,
				})) {
					if (safeCount(value)) counts[name] = value;
				}
				if ([usage.input, usage.cacheRead, usage.cacheWrite].every(safeCount)) {
					const total = usage.input + usage.cacheRead + usage.cacheWrite;
					if (safeCount(total)) counts.inputTokens = total;
				}
				if (Object.keys(counts).length) inference.usage = counts;
				if (typeof usage.cost.total === "number" && Number.isFinite(usage.cost.total) && usage.cost.total >= 0) {
					inference.cost = {
						amount: usage.cost.total,
						currency: "USD",
						source: usage.cost.totalFromProvider ? "provider_reported" : "harness_estimated",
					};
				}
				if (message.responseId) inference._meta = { "dev.pi.export": { responseId: message.responseId } };
				const exactCounts = Object.fromEntries(
					Object.entries({
						input: usage.input,
						output: usage.output,
						cacheRead: usage.cacheRead,
						cacheWrite: usage.cacheWrite,
						reasoning: usage.reasoning,
					}).filter(([, value]) => typeof value === "string"),
				);
				if (Object.keys(exactCounts).length)
					inference._meta = {
						"dev.pi.export": { ...(message.responseId ? { responseId: message.responseId } : {}), exactCounts },
					};
				if (message.providerThinkingLevel !== undefined)
					inference.settings = { reasoningEffort: message.providerThinkingLevel };
				if (safeCount(message.durationMs)) inference.durationMs = message.durationMs;
				if (message.errorMessage !== undefined) inference.error = { message: message.errorMessage };
				for (const part of message.content) {
					if (part.type === "toolCall") {
						append({
							type: "tool_call",
							...(identified ? { inferenceId } : {}),
							callId: part.id,
							name: part.name,
							input: part.arguments,
							requestedBy: "model",
						});
					} else {
						const content =
							part.type === "text"
								? [{ type: "text", text: part.text }]
								: [
										part.redacted
											? { type: "reasoning", visibility: "encrypted" }
											: asrReasoning(
													part.thinking,
													["anthropic", "openai", "openai-codex"].includes(message.provider ?? ""),
												),
									];
						append({
							type: "message",
							role: "assistant",
							content,
							...(identified ? { author: "model", inferenceId } : {}),
							...(["error", "aborted"].includes(message.stopReason) ? { truncated: true } : {}),
						});
					}
				}
				if (identified) append(inference);
				else append({ type: "session_info", missing: ["unidentified_inference"] });
			} else if (message.role === "toolResult") {
				const previous = resultPositions.get(message.toolCallId);
				if (previous !== undefined)
					rows[previous] = { id: rows[previous].id, type: "session_info", missing: ["tool_result_updates"] };
				resultPositions.set(message.toolCallId, rows.length);
				append({
					type: "tool_result",
					callId: message.toolCallId,
					status: message.isError ? "failed" : "completed",
					content: parts(message.content),
					...(message.content.some((part) => part.type !== "text") ? { truncated: true } : {}),
					...(safeCount(message.durationMs) ? { durationMs: message.durationMs } : {}),
				});
			} else if (message.role === "user" || message.role === "system") {
				append({
					type: "message",
					role: message.role,
					content: parts(message.content),
					...(typeof message.content !== "string" && message.content.some((part) => part.type !== "text")
						? { truncated: true }
						: {}),
					...(message.role === "system" ? { author: "harness", origin: "instructions" } : {}),
				});
			} else if (message.role === "custom") {
				append({
					type: "message",
					role: "user",
					author: "harness",
					origin: "injected",
					content: parts(message.content),
				});
			} else if (message.role === "compactionSummary" || message.role === "branchSummary") {
				append({
					type: "message",
					role: "user",
					author: "harness",
					origin: "compaction",
					content: [{ type: "text", text: message.summary }],
				});
			} else {
				append({ type: "gap", reason: "not_recorded", detail: "Native shell execution is not normalized." });
			}
		}
	}
	return `${rows.map((row) => JSON.stringify(row)).join("\n")}\n`;
}

function safeCount(value: unknown): value is number {
	return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function parts(content: string | readonly { type: string; text?: string }[]): RecordValue[] {
	return typeof content === "string"
		? [{ type: "text", text: content }]
		: content.filter((part) => part.type === "text").map((part) => ({ type: "text", text: part.text }));
}

/** Decode durable JSONL without silently discarding malformed lines or rounding native values. */
export function exportAgentSessionFile(content: string): string {
	const entries: FileEntry[] = [];
	for (const line of content.split("\n").slice(0, -1)) {
		entries.push(
			JSON.parse(line, (_key: string, value: unknown, context?: { source: string }) => {
				if (typeof value === "number" && Number.isInteger(value) && !Number.isSafeInteger(value)) {
					if (!context) throw new Error("This Node version cannot preserve large native numbers");
					return context.source;
				}
				return value;
			}) as FileEntry,
		);
	}
	if (!content.endsWith("\n")) throw new Error("Incomplete native session file");
	const header = entries.shift();
	if (header?.type !== "session" || entries.some((entry) => entry.type === "session"))
		throw new Error("Invalid native session header");
	return exportAgentSession(header, entries as SessionEntry[]);
}

function asrReasoning(
	text: unknown,
	summary = false,
): { type: string; visibility?: string; text?: string; summary?: string[] } {
	if (typeof text !== "string" || text.length === 0) return { type: "reasoning", visibility: "omitted" };
	if (summary) return { type: "reasoning", visibility: "summary", summary: [text] };
	return { type: "reasoning", text };
}
