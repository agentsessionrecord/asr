// Normalize camel case and separators without matching ordinary token counts.
function words(key: string): string {
  return key.replace(/([a-z0-9])([A-Z])/g, "$1_$2").replace(/[-. ]/g, "_").toLowerCase();
}

const credentialName = /^(?:(?:[a-z0-9]+_)*(?:api_key|access_token|refresh_token|auth_token|session_token|authorization|password|passwd|secret|secrets|cookie|cookies|set_cookie|credential|credentials|private_key|client_secret|aws_secret_access_key)|token|key)$/;

export function isSecretKey(key: string): boolean { return credentialName.test(words(key)); }

/** Environment names require a complete credential word or credential name. */
export function environmentSecrets(env: Record<string, string | undefined>): string[] {
  return Object.entries(env).filter(([key, value]) =>
    (isSecretKey(key) || /(?:^|_)(?:key|token|password|secret|credential)(?:_|$)/.test(words(key))) &&
    typeof value === "string" && value.length >= 8).map(([, value]) => value!);
}

/** Learn named values before filtering text that echoes them in the same observation. */
export function credentialValues(value: unknown): string[] {
  const values = new Set<string>(), seen = new Set<object>();
  let nodes = 0, size = 0;
  const walk = (item: unknown, depth = 0): void => {
    if (++nodes > 100_000 || depth > 40) throw new Error('Credential scan capacity');
    if (typeof item === 'string' && /^[\s]*[\[{]/.test(item)) {
      let decoded: unknown;
      try { decoded = JSON.parse(item); } catch { return; }
      walk(decoded, depth + 1);
    } else if (item && typeof item === 'object') {
      if (seen.has(item)) return;
      seen.add(item);
      for (const [key, child] of Object.entries(item)) {
        if (isSecretKey(key) && typeof child === 'string' && child && !/^\[(?:redacted|omitted)\]$/i.test(child)) {
          if (!values.has(child)) {
            size += child.length;
            if (size > 1024 * 1024) throw new Error('Credential scan capacity');
            values.add(child);
          }
        } else if (!isOpaqueKey(key)) walk(child, depth + 1);
      }
    }
  };
  walk(value);
  return [...values].sort((a, b) => b.length - a.length);
}

/** One list of recognized credential forms for every JavaScript recorder. */
export const SECRET_PATTERNS: readonly RegExp[] = [
  /\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[A-Za-z0-9_-]{35})\b/g,
  /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/g,
  /\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}/g,
  /\bBearer\s+[A-Za-z0-9._~+/-]+=*|\bBasic\s+[A-Za-z0-9+/]{16,}={0,2}/gi,
  /-----BEGIN [\w ]*PRIVATE KEY-----[\s\S]*?(?:-----END [\w ]*PRIVATE KEY-----|$)/g,
  /\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|session[_-]?token|authorization|password|passwd|client[_-]?secret|secret|cookie|private[_-]?key|token)\b["']?\s*[:=]\s*(?:"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*'|[^\s,;}"']+)/gi,
  /https?:\/\/[^/\s@]+@/g,
  /[?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|session[_-]?token|client[_-]?secret|password|secret|token)=[^&#\s"']*/gi,
];

export function redactSecrets(text: string, knownSecrets: readonly string[] = []): string {
  let clean = text;
  for (const secret of knownSecrets) if (secret) clean = clean.replaceAll(secret, "[redacted]");
  for (const pattern of SECRET_PATTERNS) clean = clean.replace(pattern, "[redacted]");
  return clean;
}

export function isOpaqueKey(key: string): boolean {
  return /^(?:signature|thoughtSignature|encrypted(?:_content|Content)?|opaque)$/i.test(key);
}
