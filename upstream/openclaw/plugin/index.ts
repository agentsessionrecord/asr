import { writeFileSync } from "node:fs";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { readSessionTranscriptEvents } from "openclaw/plugin-sdk/session-transcript-runtime";
import { exportTranscript } from "./transcript.mjs";

export default definePluginEntry({
  id: "asr-export",
  name: "ASR export",
  description: "Export retained session messages and tool calls as ASR",
  register(api) {
    api.registerCli(({ program }) => {
      program.command("asr-export")
        .requiredOption("--agent <id>", "Selected agent")
        .requiredOption("--session-key <key>", "Selected session key")
        .requiredOption("--session <id>", "Selected native session ID")
        .requiredOption("--output <file>", "New private ASR output file")
        .action(async (options: { agent: string; sessionKey: string; session: string; output: string }) => {
          const events = await readSessionTranscriptEvents({ agentId: options.agent, sessionKey: options.sessionKey, sessionId: options.session });
          const stream = exportTranscript(options.session, events);
          writeFileSync(options.output, stream, { mode: 0o600, flag: "wx" });
        });
    }, { descriptors: [{ name: "asr-export", description: "Export one retained session as ASR", hasSubcommands: false }] });
  },
});
