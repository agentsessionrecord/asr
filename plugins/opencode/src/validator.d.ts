declare module "@agent-session/validate" {
  export function validate(input: Uint8Array | string, options: { mode: "session" }): {
    valid: boolean;
    records: { value: Record<string, any> }[];
  };
}
