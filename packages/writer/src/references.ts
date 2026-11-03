/** Encode only the component characters reserved by ASR-011. */
export function encodeReferenceComponent(value: string): string {
  if (!value) throw new TypeError("Reference components must be non-empty");
  return value.replace(/[%:#\x00-\x20\x7f-\x9f]/gu, character =>
    Array.from(Buffer.from(character), byte => "%" + byte.toString(16).toUpperCase().padStart(2, "0")).join(""));
}

export function sessionReference(agent: string, sessionId: string, namespace?: string): string {
  return [agent, ...(namespace === undefined ? [] : [encodeReferenceComponent(namespace)]), encodeReferenceComponent(sessionId)].join(":");
}
