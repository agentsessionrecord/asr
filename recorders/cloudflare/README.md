# Cloudflare AI Gateway Logpush recorder

This offline consumer converts local AI Gateway Logpush files to ASR.
It reuses the [shared gateway core](../envoy/README.md).
It reads plain JSONL and gzip JSONL. It makes no network requests.
The contract follows the
[Logpush documentation](https://developers.cloudflare.com/ai-gateway/observability/logging/logpush/)
checked on November 1, 2026.
Cloudflare offers a hosted gateway. This integration is not deployed or live-tested.

```sh
uv sync --all-packages
uv run asr-cloudflare --input /private/gateway.log.gz --output /private/asr \
  --private-key-file /private/logpush-rsa.pem
```

The consumer decrypts `Metadata`, `RequestBody` and `ResponseBody`.
It uses RSA OAEP with SHA-256 to unwrap the per-log AES key.
It uses AES-GCM with the recorded IV to decrypt the payload and authenticate its tag.
Private keys and decrypted source files are never written into ASR.
An encrypted field without a key or with a bad authentication tag fails conversion.
The command reports accepted and skipped counts and exits nonzero for skipped logs.

Configure the gateway's custom metadata with two string fields.
Set `asr_api` to `anthropic-messages` or `openai-responses`.
Set `asr_headers` to a JSON string containing only the original agent identity headers.
Use Claude Code or Codex native session evidence. Do not include authorization headers.
These two fields fit the gateway's five metadata field limit.
The consumer does not infer sessions from log IDs, trace IDs or similar text.
Logs without supported API and identity evidence are skipped.
A caller can supply an optional `ResponseStatus` enrichment when it has observed it.
Absent HTTP status stays unknown.

Original provider request and response shapes are required.
Translated, truncated or missing bodies can lose information.
The consumer uses the core's gap handling for incomplete SSE.
Offline conversion has no invented local receipt times or model-call durations.
It declares those losses. It does not claim a per-request time from conversion time.
File order is retained. Repeated histories use the shared conservative alignment.
Copy detection, approvals and tool outcomes remain subject to gateway visibility limits.

`tests/fixtures/logpush.jsonl` is synthetic decrypted native traffic.
Tests encrypt all three fields with a temporary key and verify decryption and rejection.
No key material is committed.

```sh
uv run asr-cloudflare --input recorders/cloudflare/tests/fixtures/logpush.jsonl --output /private/replay
uv run --all-packages pytest recorders/envoy/tests
```
