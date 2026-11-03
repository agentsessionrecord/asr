# Envoy recorder and shared gateway core

This Python gRPC service implements Envoy's v3 external processing API.
It records buffered native Anthropic Messages and OpenAI Responses traffic.
The gateway adapters reuse LiteLLM's API mapping, identity matching, privacy,
stream folding, conservative tool pairing and inclusive token accounting.
They do not translate between provider APIs.

## Install and run

```sh
uv run --isolated --package asr-gateway-core asr-gateway --output /private/asr --port 8420
```

Use a separate environment from the Phoenix exporter. The `xds-protos` dependency
ships older OpenTelemetry modules that overlap with `opentelemetry-proto`.

Add [config.example.yaml](config.example.yaml) before the Envoy router filter.
Define an `asr_recorder` HTTP/2 cluster pointing to `127.0.0.1:8420`.
Envoy must share the receiver's network namespace.
The sample buffers request and response bodies and permits traffic if capture fails.
Set Envoy's body and connection buffer limits for your workload.
This recorder supports HTTP bodies, not WebSockets or bidirectional model transports.
It emits empty processing responses and does not change headers or bytes.
A JSON response or a complete buffered SSE response supplies the completed exchange.
Missing terminal evidence produces gaps through the shared core.

The native contract is
[external_processor.proto](https://github.com/envoyproxy/data-plane-api/blob/main/envoy/service/ext_proc/v3/external_processor.proto).
The fixture `tests/fixtures/ext-proc.json` uses its protobuf JSON shape.
Tests use the generated official gRPC client and server on loopback.
A full Envoy or Agent Router instance is not live-tested.

## Identity and privacy

Original Claude Code or Codex session headers must survive to the processor.
A trace ID or a gateway log ID is not a native agent session ID.
Unknown identities and unsupported APIs are skipped and counted.
Requests that fail before a response body arrives are outside capture.
The native API core declares missing approvals, file changes, commits, costs,
copy detection, full subagent links, tool execution timing and other unavailable facts.
See [the LiteLLM mapping](../litellm/README.md) for the detailed rules.
The gateway does not turn an inferred successful command into approval evidence.

New output directories have mode 700 and files have mode 600.
Use a new private output directory and one receiver process.
Existing files are never overwritten. Process restarts require a fresh directory.
Known credentials and secret headers are scrubbed before entering ASR state.
Opaque reasoning state is excluded. Recorded content remains untrusted.
No recorded URL is fetched and no recorded command is executed.

## Other native boundaries

Portkey uses its logging hook. Helicone uses its SDK logging endpoint.
Cloudflare uses encrypted Logpush exports.
Each has its own command and mapping notes in its recorder directory.
Live logging receivers use receipt times.
Offline conversion omits local playback times and durations and declares their loss.
The storage adapter names each gateway as the producer while reusing the API core.

```sh
uv run --all-packages pytest recorders/envoy/tests recorders/acp/tests recorders/litellm/tests
```

The suite validates every output with the reference validator.
It also validates the public ASR samples and examples.
Calls with unavailable outcomes can have expected unpaired-call warnings.
