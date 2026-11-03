# Portkey recorder

This local receiver accepts the native `default.log` plugin's after-request context.
It reuses the [shared gateway core](../envoy/README.md).
It supports Portkey source revision
`669825cbe89ee51569918b8f78a9db486fd69dd4`.
The native context comes from
[HookSpan](https://github.com/Portkey-AI/gateway/blob/669825cbe89ee51569918b8f78a9db486fd69dd4/src/middlewares/hooks/index.ts)
and the [logging plugin](https://github.com/Portkey-AI/gateway/blob/669825cbe89ee51569918b8f78a9db486fd69dd4/plugins/default/log.ts).

```sh
uv sync --all-packages
uv run asr-portkey --output /private/asr --port 8421
```

Merge [config.example.json](config.example.json) into your gateway configuration.
Use the native Messages endpoint with `requestType: messages`.
The logging receiver and gateway must share a network namespace.
The hook sends the recorded request headers, request JSON and response JSON.
Configure this logging destination only inside a trusted local environment.
The receiver excludes credentials from ASR. The logging transport contains raw context.

The receiver rejects streaming contexts, translated contexts and other request types.
Portkey's streaming hooks do not supply the native SSE frames required by this mapping.
A transformed response does not establish the provider's original served model or usage.
Trace IDs and metadata tags do not supply an agent's session identity.
Original agent headers must be present. Unknown identities are skipped.

The synthetic fixture `tests/fixtures/after-request.jsonl` follows this pinned contract.
It is not live-tested with a full Portkey gateway.

```sh
uv run asr-portkey --output /private/replay --input recorders/portkey/tests/fixtures/after-request.jsonl
uv run --all-packages pytest recorders/envoy/tests
```

Offline input wraps each native context in `payload` and does not invent event times.
The shared suite checks the native shape, identity limits, privacy and usage.
