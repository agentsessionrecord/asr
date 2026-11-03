# User identity and settings

The [session](identity-and-settings.jsonl) uses a fictional agent that records an
account identity, agent settings and model calls. Its first turn records four
model settings. Both calls in that turn carry those values. The second turn
records only reasoning effort, so its inference leaves the other settings absent.
The export does not supply defaults or copy settings from a different turn.

The header's `user` groups the session under the signed-in account. It does not
establish who typed a particular prompt or made a commit. The harness notice
keeps `author: harness` even though its role is `user`.

After `mode-change`, the mode is `execute`, approval is still `on-request` and
sandbox is still `read-only`. After `policy-change`, the mode remains `execute`,
approval is `never` and sandbox is `workspace-write`. Each update changes only
the fields it supplies. These strings belong to the fictional agent's vocabulary.

The first turn's recorded temperature is zero. An absent temperature in the
second turn is unknown. The three original calls total 300 input tokens and 38
output tokens. No session total is added to them.

See [Records](../spec/records.md) for the field shapes and
[Running ASR across a company](../guides/organizations.md) for collection and
directory joins.
