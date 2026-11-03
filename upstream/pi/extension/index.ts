/** Export the current durable session through Pi's public extension API. */

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { exportAgentSessionFile } from "./export.ts";

export default function (pi: ExtensionAPI) {
	pi.registerCommand("export-asr", {
		description: "Export the full session tree as ASR: /export-asr output.jsonl",
		handler: async (args, context) => {
			const file = context.sessionManager.getSessionFile();
			if (!file) throw new Error("Save the session before exporting it");
			if (!args.trim()) throw new Error("Use /export-asr output.jsonl");
			const destination = resolve(context.cwd, args.trim());
			const stream = exportAgentSessionFile(readFileSync(file, "utf8"));
			writeFileSync(destination, stream, { mode: 0o600, flag: "wx" });
			context.ui.notify(`Exported session to ${destination}`, "info");
		},
	});
}
