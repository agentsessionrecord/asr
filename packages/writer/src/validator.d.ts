declare module "@agent-session/validate" {
  export function validate(input: Uint8Array | string, options: { mode: "session" }): {
    valid: boolean;
    records: Array<{ value: Record<string, any> }>;
  };
  export function validateRecord(record: unknown): Array<{
    severity: "error" | "warning";
    code: string;
    pointer: string;
    message: string;
  }>;
}
