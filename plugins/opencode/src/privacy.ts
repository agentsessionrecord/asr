import { credentialValues, isSecretKey, isOpaqueKey, redactSecrets } from "@agent-session/writer";

export type Data = Record<string, any>;

/** Copies a bounded JSON snapshot without changing any agent-owned object. */
export function snapshot(value: unknown, full: boolean, secrets: string[]): { value: any; shortened: boolean } {
  secrets = [...secrets, ...credentialValues(value)];
  let shortened = false;
  let budget = 128 * 1024;
  let nodes = 0;
  const seen = new Set<object>();
  function copy(item: any, key = "", depth = 0): any {
    if (++nodes > 4096 || depth > 24 || budget <= 0) { shortened = true; return null; }
    if (isSecretKey(key) || isOpaqueKey(key)) {
      shortened = true;
      return "[redacted]";
    }
    if (!full && depth > 1 && /^(?:args|input|inputText|output|content|text|error|title|description|patterns|resources|parts|message|cancelReason)$/.test(key)) {
      shortened = true;
      return undefined;
    }
    if (typeof item === "string") {
      let result = redactSecrets(item, secrets);
      if (result !== item && /^(?:sessionID|sessionId|callID|requestID|messageID|id)$/.test(key)) throw new Error("Secret-valued native identity");
      if (result !== item) shortened = true;
      const limit = Math.min(64 * 1024, budget);
      if (Buffer.byteLength(result) > limit) { result = Buffer.from(result).subarray(0, limit).toString("utf8"); shortened = true; }
      budget -= Buffer.byteLength(result);
      return result;
    }
    if (typeof item === "bigint") return String(item);
    if (typeof item === "number") {
      if (!Number.isFinite(item) || Math.abs(item) > Number.MAX_SAFE_INTEGER) throw new Error("Unsafe native number");
      return item;
    }
    if (item === null || typeof item === "boolean") return item;
    if (item === undefined) return undefined;
    if (typeof item !== "object" || seen.has(item)) throw new Error("Non-JSON callback");
    seen.add(item);
    try {
      if (Array.isArray(item)) {
        if (item.length > 4096) shortened = true;
        return item.slice(0, 4096).map(entry => copy(entry, "", depth + 1));
      }
      const result: Data = {};
      for (const name of Object.keys(item)) {
        if (nodes > 4096 || budget <= 0) { shortened = true; break; }
        const keyBytes = Buffer.byteLength(name);
        if (keyBytes > budget) { shortened = true; break; }
        budget -= keyBytes;
        if (redactSecrets(name, secrets) !== name) { shortened = true; continue; }
        if (!full && key === "metadata" && !["exit", "truncated", "cancelled", "sessionId"].includes(name)) { shortened = true; continue; }
        const field = copy(item[name], name, depth + 1);
        if (field !== undefined) Object.defineProperty(result, name, { value: field, enumerable: true, configurable: true, writable: true });
      }
      return result;
    } finally { seen.delete(item); }
  }
  return { value: copy(value), shortened };
}
