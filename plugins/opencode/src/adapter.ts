import { Recorder, type Agent } from "./recorder.js";
import type { Data } from "./privacy.js";

export function configured(agent: Agent): Recorder {
  return new Recorder({ agent, directory: process.env.ASR_OUTPUT_DIR, content: process.env.ASR_CONTENT === "full" ? "full" : "metadata" });
}

export function legacy(agent: Agent) {
  return async function plugin(_context: unknown) {
    const recorder = configured(agent);
    const exit = () => recorder.close();
    process.once("exit", exit);
    return {
      event: async (input: Data) => { recorder.observe("event", input); },
      "tool.execute.before": async (input: Data, output: Data) => { recorder.observe("tool.execute.before", input, output); },
      "tool.execute.after": async (input: Data, output: Data) => { recorder.observe("tool.execute.after", input, output); },
      "permission.ask": async (input: Data, output: Data) => { recorder.observe("permission.ask", input, output); },
      "chat.message": async (input: Data, _output: Data) => { recorder.observe("chat.message", input); },
      dispose: async () => { process.removeListener("exit", exit); recorder.close(); },
    };
  };
}
