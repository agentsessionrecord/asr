import { configured } from "./adapter.js";
import type { Data } from "./privacy.js";

/** Structural boundary keeps this adapter independent of the host's Effect runtime. */
interface Context {
  tool: { hook(name: string, callback: (event: Data) => void): Promise<{ dispose(): Promise<void> }> };
  permission: { hook(name: string, callback: (event: Data) => void): Promise<{ dispose(): Promise<void> }> };
  event: { subscribe(options?: { signal?: AbortSignal }): AsyncIterable<Data> };
}

export default {
  id: "org.agentsessionrecord.recorder",
  async setup(context: Context) {
    const recorder = configured("opencode");
    const controller = new AbortController();
    const registrations: { dispose(): Promise<void> }[] = [];
    const exit = () => recorder.close();
    process.once("exit", exit);
    try {
      registrations.push(await context.tool.hook("execute.before", event => recorder.observe("v2.before", event)));
      registrations.push(await context.tool.hook("execute.after", event => recorder.observe("v2.after", event)));
      registrations.push(await context.permission.hook("evaluate", event => recorder.observe("v2.permission", event)));
      void (async () => {
        try { for await (const event of context.event.subscribe({ signal: controller.signal })) recorder.observe("event", { event }); }
        catch { /* A disconnected subscription must not fail the agent. */ }
      })();
    } catch { /* Unsupported hosts keep running without this recorder. */ }
    return async () => {
      controller.abort();
      for (const registration of registrations) { try { await registration.dispose(); } catch {} }
      process.removeListener("exit", exit);
      recorder.close();
    };
  },
};
