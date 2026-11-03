# JSON hook recorder

This shared core records JSON command hooks as ASR 0.1. Each agent has a small
adapter beside it. Python 3.11 or later and a POSIX host are required. The core
uses the standard library so hooks need no package install or service.

Run setup from the repository root. Choose a private install prefix and a
separate capture directory. See each agent's README for its native config path.

```sh
python3 plugins/hooks-core/install.py qoder \
  --prefix "$HOME/.local/share/asr-hooks" \
  --config "$HOME/.qoder/settings.json" \
  --output-dir "$HOME/.local/share/asr-captures"
```

The installer copies the core and selected adapter. It merges only its own
registrations into the chosen native config file. Existing settings and other
hooks stay in place. Repeating setup updates the registrations without adding
duplicates. Close the agent before changing its hooks. Back up its config first.
The file must be JSON. JSON with comments is not accepted by this installer.

Uninstall with the same prefix and config path plus `--uninstall`. Capture files
are retained. Once all agents are disabled, you can remove the install prefix.
A local Claude plugin can also be loaded for one run with `--plugin-dir`.

## Capture policy

Metadata is the default. It retains native IDs, known tool names, lifecycle
observations, settings, decisions when explicit, and tool outcomes when stated.
It omits prompt and reply text, arbitrary tool names, input, output and paths.
Pass `--content full` to setup to keep available content. This mode still excludes
known credential values from the environment, common credential forms, secret
fields, interaction answers and opaque provider state. Redaction is best effort.
Keep captured files private.
If a required session identity contains a known credential, that observation is
not stored. A credential in another native identity produces a redacted gap.

For direct calls, set `ASR_OUTPUT_DIR` to an absolute private directory. Set
`ASR_CONTENT=full` to opt into content. The content policy is fixed when a
session file is created. Restart with a new native session or output directory
to change it. A resumed session keeps its native identity and stream.

Output is `<capture-dir>/<agent>/<safe-session-id>.jsonl`. Unsafe filename
characters cause a SHA-256 filename. The header keeps the native ID verbatim.
Directories use mode `0700`. Files use `0600`. Symlink output files, hard links,
FIFOs and shared or foreign-owned output directories are refused.

The recorder appends complete lines. It never repairs or rewrites a stream.
A private state sidecar tracks pairing and buffered results. A lock waits at most 100 ms. A later callback records a gap when it sees a contention marker. A deadline or oversized input also leaves a loss marker. A stream with stale
state writes a terminal gap and seals capture. If its final line is torn, a
separate capture of the same session declares the stop. Use a fresh capture
directory to restart it.
State is capped at 512 KiB and streams at 16 MiB. A storage cap adds a gap and
stops capture. Input is capped at 1 MiB. The callback has a 150 ms deadline after
Python starts. Capture failures produce no diagnostics or payload output and
do not change the native protocol response.

Cursor's permission and prompt hooks use exit code `1` with `failClosed: false`.
Its documented protocol treats empty or invalid output on exit `0` as blocking
for permission hooks. Exit `1` takes its fail-open path and can appear in its
hook error log. Other registered events exit `0`. Registrations never approve
or deny a permission, rewrite input, add context or submit a follow-up prompt.

Junie uses advisory async handlers. A synchronous PermissionRequest success can
approve an action with empty output, so these registrations must remain async.
Firebender's beforeMCPExecution and beforeReadFile fail closed and are omitted.
Its generic preToolUse callback still observes those requests. Antigravity
requires a PreToolUse response. Its entry point writes the fixed neutral
`{"decision":"allow"}` response before capture. That value delegates to the next
hook or default policy. It does not approve a permission request. Stop gets
`{"decision":""}` and other Antigravity events get `{}`. No payload enters these
responses. See each adapter README for the native contract and limitations.

## ASR mapping

The producer is `asr-hooks-<agent>`, method `recorder`. All `ts` values are receipt
times. An explicit new session event can set `startedAt`. A resume first seen
by this recorder leaves the original start and cwd unknown and emits a gap.
In full-content mode, a new session observes Git in the supplied cwd. The header
keeps the repository root and any available branch, full HEAD and safe origin
remote. Git failure leaves cwd available. Resumes never replace these facts.
Only `SessionEnd` sets `session_info.endedAt`. Stop and subagent stop do not.

Pre-tool arguments are requests that another hook can rewrite. They stay in
`_meta.org.agentsessionrecord.hooks.requestedInput`. Core call input stays absent
until the first observation itself has effective arguments. Later effective
arguments use `tool_result.input`. JSON null and empty values stay supplied.

Claude results fold post-tool outcomes and final model-facing batch content.
They occupy the batch receipt position. Intervening events retain their place.
Batch request arguments never replace post-tool arguments. A terminal callback
flushes an outcome if no batch arrived and marks `batchNotObserved`. It does not
invent model-facing text. The first outcome receipt is `firstObservedAt` in
metadata. Other adapters complete a result at their post-tool callback.

Structured or display output stays in metadata unless the source identifies it
as model-facing content. Copilot's `textResultForLlm` and Claude's batch output
supply core result content. Tool names use each adapter's fixed `kinds` map.
Unknown tool names do not get a guessed kind. No exit code is inferred from text.
Droid's post callback does not state success, so its status stays `unknown`.

Permission requests and notifications are observations. They are never approval
decisions. Explicit permission-denied hooks supply denied approvals. Qoder's
contract identifies its denial callback as a classifier decision. Claude's hook
alone does not establish a decider. Scope and person stay absent. The recorder
cannot observe what other hooks return or every person's choice. It declares
`approvals`, `hook_outcomes`, `hook_input_rewrites` and `hook_output_rewrites` as
incomplete even when some facts exist.

Missing call IDs stay missing. A pre-tool callback then gets a derived request
ID. A later result stays unpaired. Names, argument equality and proximity never
establish a pair. Child IDs are used only by adapters that document them. A
containing session ID alone does not establish the child's immediate parent.
Claude Agent results can supply a child session reference.

Every stream declares `org.agentsessionrecord.hooks/v1`.
Every completed callback has an `org.agentsessionrecord.hooks/hook` record.
Streaming display callbacks fold before emission. This extension retains event
occurrence, correlation keys and selected facts that core records do not model.
Native fields outside the adapter's allowlist are omitted and declared missing.
The complete common loss list is `LOSSES` in `projection.py`. Adapter losses and
metadata-mode losses are added to the header. Inference, reasoning, usage, cost,
offered tools, instructions, complete file change history, commits, copies, full lineage, user
identity and complete approval history are not available from this capture.

## Add an adapter

1. Read the agent's official hook contract. Add its source URLs and checked date
   to `plugins/<agent>/README.md`. State the supported payload version and live
   test status. Check whether events expose stable call IDs and final content.
2. Create `adapter.json`. `events` maps native event names to the shared names in
   `projection.py`. `fields` lists unchanged field names. `rename` maps native
   names to shared field names. Only these fields cross the adapter boundary.
   An event command argument is required when stdin omits the event name.
   `payload_event_aliases` handles a documented event spelling mismatch.
3. Define `kinds`, `shell_tools`, `agent_tools`, `secret_tools`,
   `new_session_sources`, and any extra `missing` names. Set `child_ids` only
   when the native contract identifies the child. Use `model_facing` only for
   documented final model content. Set `batch` only for a final batch protocol.
   `post_status` defaults to `completed`. Override it when the callback does not
   establish success. `asks_sometimes` requires a documented effective policy.
   Set `session_start_is_new` only when the event itself explicitly means a new
   session and no source discriminator is needed. `observations` lists extra
   native fields retained only in full-content hook metadata. Source-specific
   boolean or error status fields are normalized in adapters.py. Request-only
   post-tool input must stay in metadata rather than result input.
4. Add a thin `record.py` entry point. Keep it silent and fail open, including
   import errors. Extend normalization for real field-shape differences. Do not
   read transcripts, global agent config or unrelated files from a hook. Only an
   explicit live start can read Git metadata in the supplied working directory.
5. Add the agent's native registration shape to `install.py`. Read its rules for
   empty output, nonzero exits and timeouts. A passive recorder must not grant
   permissions or change a tool result. Test install and uninstall preservation.
   Native configuration can be an unwrapped event map, a versioned array or
   named hook groups. Timeout units differ. Use merge_native for these formats.
6. Add synthetic payloads under `fixtures/`. Cover absent IDs, request-only
   permissions, rewrites, effective input, failure, lifecycle and interleaving.
   Add the adapter to tests and registry. Run the validator on every output.

The shared core is the only ASR writer used by these command adapters. The
package writer creates new files and requires schema packages at startup. This
core instead resumes one private stream across short independent hook processes.
It owns locking, append state, folding, bounds and privacy for this hook format.

## Checks

Install the repository's Node dependencies for the validator, then run:

```sh
bash plugins/hooks-core/check.sh
```

The suite validates every generated ASR file with zero errors. Warnings for the
named extension and hook type are expected. Protocols without call IDs produce
unpaired-result and call-without-result warnings. Isolated callbacks can also
produce missing-tool-name warnings. A deliberately interrupted tail produces an
incomplete-line warning. These warnings describe the tested limits.

The optional Claude live check needs an authorized loopback Anthropic-compatible
endpoint, a model name and its existing credential file. It runs in disposable
config, home and working directories. It prints
counts and boolean checks, deletes its scratch files, and starts no service.
It writes the credential only to an owner-only provider settings file consumed
by Claude and verifies the endpoint before starting the agent. It commits the
scratch edit locally and checks its session citation with `asr blame`.
Run it through your build runner. It is not part of offline CI.

```sh
python3 -I -S plugins/hooks-core/tests/live_claude.py \
  --base-url "$ANTHROPIC_ENDPOINT" --model "$MODEL" \
  --key-file "$PROXY_KEY_FILE" --asr target/debug/asr --report "$REPORT_FILE"
```
