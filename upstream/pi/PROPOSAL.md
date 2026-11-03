# Pi ASR extension

Export a saved Pi session as ASR so it can be read outside Pi. This is an
installable Pi extension using `registerCommand` and `getSessionFile` from the
public extension API. No core patch or extra binary is required.

`/export-asr output.jsonl` exports the durable v3 session tree, including branches.
It keeps native message and response identities, tool pairing, supported reasoning
and inclusive token counts. Requested and served models stay separate.
Unsafe numeric counts stay exact in metadata. They do not enter numeric core fields.

The extension writes new private files and refuses to overwrite existing files.
An offline Node command uses the same mapper without loading agent configuration.
Approvals, edits, commits, media and opaque provider state remain declared losses.

Focused tests cover extension registration, file permissions, overwrite refusal,
branches, reasoning, model identity, unsafe numbers and malformed input.
Run `npm run check` and
`node --test packages/coding-agent/test/export-agent-session.test.ts`.

Source: [https://github.com/earendil-works/pi](https://github.com/earendil-works/pi).
Base: `8f9446a06027b075bf885189ceb0983565662174`.
