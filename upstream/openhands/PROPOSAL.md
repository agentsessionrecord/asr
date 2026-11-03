# Native ASR export for OpenHands Canvas

Export a saved session in an open format that search and code history tools can read. The export keeps the source facts available for later review.

This patch adds Agent Session Record to the transcript export dialog. It downloads one UTF-8 JSONL file for the selected conversation. The producer method is `native`.

Open a conversation and choose its transcript export action. Select **Agent Session Record (.jsonl)** and export. ASR includes available tool details and event times. The presentation filters do not apply to this format.

The patch applies to OpenHands/OpenHands at `4ce9c4b874c178297d591f9d01a7e21dc50d757a`, Canvas 1.34.0. Apply the patch listed in `manifest.json` with `git am` in a writable checkout at that commit. The backend and SDK contracts stay in their owning repositories.

The export keeps messages, system prompt text, requested tool names, effective action input and model-facing text results. Explicit native rejection observations supply denied decisions with unknown answerer and scope. Result updates occupy their final observation. Native event IDs are kept when valid and unique. Derived IDs handle header collisions.

The export uses the existing complete-history pagination and retains the returned source order. The API sorts history by timestamps and exposes no independent recording sequence. This limit is declared as `event_order`. The exporter cannot reconstruct a recording sequence that the API does not expose. Native timestamps without an offset stay in `dev.openhands` metadata. They do not acquire an invented timezone.

Known credential fields, recognized credential text and secret-request tool payloads are excluded. Encrypted reasoning and provider signatures are excluded. The export does not fetch attachments or look up current files, configuration or Git state.

Known losses include model-call usage, model identity, policy history, complete approval history, offered tool definitions, reasoning, media, file edits, commits, lineage and copies. Unmapped native events become positional gaps. User roles do not establish human authorship. Current model selections do not become historical inference records. Integers outside JavaScript's exact range stop export rather than being rounded.

The native tests cover the export dialog, source ordering, result completion, rejection, secret exclusion, unknown outcomes and timezone-free timestamps. Focused frontend tests, ESLint, TypeScript and translation checks pass. The live test used an SDK 1.42.1 conversation through a verified OpenAI-compatible or Anthropic-compatible endpoint. Its four events exported as five ASR records with zero validator errors and warnings. The dialog was tested with synthetic service data. Full Local and Cloud browser sessions were not run.

`samples/native/native.json` and `samples/asr/session.jsonl` are synthetic. The package check verifies source facts, patch syntax and integrity, privacy and ASR validation. The upstream tests are included in the patch. No command-line export, discovery registration or live ASR writer is added to this frontend patch.

## Verification scope

The live evidence above is from a prior revision. The current source has focused
regressions and package checks. Its full agent and model path has not been rerun.
