import { spawnSync } from "node:child_process";
import { isAbsolute } from "node:path";
import { environmentSecrets, redactSecrets } from "./privacy.js";

/** Observe only at an explicit live start. Git failure leaves the cwd usable. */
export function repositorySnapshot(cwd: unknown): { cwd?: string; repos?: { path: string; branch?: string; head?: string; remote?: string }[] } {
  if (typeof cwd !== "string" || !isAbsolute(cwd)) return {};
  const facts: ReturnType<typeof repositorySnapshot> = { cwd };
  const deadline = Date.now() + 80;
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("GIT_")));
  Object.assign(env, { GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null", GIT_TERMINAL_PROMPT: "0" });
  const git = (...args: string[]): string | undefined => {
    try {
      if (Date.now() >= deadline) return undefined;
      const result = spawnSync("git", ["-c", "core.fsmonitor=false", "-C", cwd, ...args], {
        env, encoding: "utf8", timeout: Math.max(1, deadline - Date.now()), maxBuffer: 65536, windowsHide: true,
      });
      return result.status === 0 ? result.stdout.replace(/\n$/, "") : undefined;
    } catch { return undefined; }
  };
  const path = git("rev-parse", "--show-toplevel");
  if (!path || !isAbsolute(path)) return facts;
  const repo: NonNullable<typeof facts.repos>[number] = { path };
  const branch = git("symbolic-ref", "--quiet", "--short", "HEAD");
  const head = git("rev-parse", "--verify", "HEAD");
  const remote = git("config", "--get", "remote.origin.url");
  if (branch) repo.branch = branch;
  if (head && /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/.test(head)) repo.head = head;
  if (remote) {
    try {
      const url = new URL(remote);
      if (!url.username && !url.password && !url.search && !url.hash) repo.remote = remote;
    } catch {
      if (!remote.includes("://") && !/[?#]/.test(remote)) repo.remote = remote;
    }
  }
  const secrets = environmentSecrets(process.env);
  for (const field of ["branch", "head", "remote"] as const) {
    if (repo[field] && redactSecrets(repo[field]!, secrets) !== repo[field]) delete repo[field];
  }
  if (redactSecrets(repo.path, secrets) !== repo.path) return facts;
  facts.repos = [repo];
  return facts;
}
