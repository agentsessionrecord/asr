# Helicone recorder

This local receiver implements the Helicone Python SDK manual logging boundary.
It reuses the [shared gateway core](../envoy/README.md).
It targets
[manual_logger.py](https://github.com/Helicone/helicone/blob/7720d286110391c3e3776bb46a18fb2a13f7567c/sdk/python/helpers/helicone_helpers/manual_logger.py)
at revision `7720d286110391c3e3776bb46a18fb2a13f7567c`.

```sh
uv sync --all-packages
uv run asr-helicone --output /private/asr --port 8421
```

Set the SDK's `logging_endpoint` to `http://127.0.0.1:8421`.
Use a local placeholder for its logging key.
Include the original agent headers in `additional_headers`.
Use provider `anthropic` for Messages at `/anthropic/v1/log`.
Use the custom logging route for native OpenAI Responses at `/custom/v1/log`.
OpenAI Chat Completions at `/oai/v1/log` is unsupported.
This receiver never forwards logs to Helicone or fetches the logged request URL.

The receiver reads `providerRequest.json` and `providerResponse.json` or `textBody`.
SDK-only `_type` and `toolName` fields are removed from the provider response.
Native SSE text uses the shared stream folder.
A trace or Helicone session header alone does not establish the original agent identity.
Preserve the original Claude Code or Codex headers.
The SDK can omit response details and does not reliably preserve error status.
Recorded HTTP status is retained as SDK evidence, not proof that a tool succeeded.

The synthetic fixture `tests/fixtures/manual.jsonl` follows the pinned SDK body.
The suite exercises the local HTTP receiver.
A full Helicone server is not live-tested.

```sh
uv run asr-helicone --output /private/replay --input recorders/helicone/tests/fixtures/manual.jsonl
uv run --all-packages pytest recorders/envoy/tests
```

Offline fixtures use `payload`, `headers` and `path` fields.
Offline conversion omits playback timestamps and declares their loss.
