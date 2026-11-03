#!/usr/bin/env node
/** Export a native Pi session without loading extensions, credentials, or the agent. */
import { readFileSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { exportAgentSessionFile } from "./export.ts";

try {
	const { values } = parseArgs({
		options: {
			session: { type: "string" },
			format: { type: "string", default: "agent-session" },
			output: { type: "string" },
		},
	});
	if (!values.session || values.format !== "agent-session")
		throw new Error("Use --session <native-file> --format agent-session");
	const stream = exportAgentSessionFile(readFileSync(values.session, "utf8"));
	if (values.output) writeFileSync(values.output, stream, { mode: 0o600, flag: "wx" });
	else process.stdout.write(stream);
} catch (error) {
	console.error(error instanceof Error ? error.message : "Export failed");
	process.exitCode = 1;
}
