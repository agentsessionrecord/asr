# Local agent observability records

Draft scope for [GH7834](https://github.com/warpdotdev/warp/issues/7834).
Users need to inspect what an agent did and give local tools a portable record.
This draft covers explicit saved-conversation export first. Live lifecycle hooks
need a separate decision about payloads, permissions and delivery.

1. Export is an explicit user action. Installing Warp does not enable capture.
2. A selected conversation exports as UTF-8 ASR 0.1 JSON Lines in native order.
3. The native conversation ID identifies the stream. Export time is not event time.
4. The saved-text implementation accepts one task. More tasks cause a clear error
   before output rather than a silently incomplete conversation.
5. Retained user and assistant text and reasoning keep their recorded content.
   Unsupported items have positioned gaps and declared losses.
6. Invalid source times and unavailable input fail without modifying the database.
7. Missing tool data, models, usage, settings and approvals remain unknown.
8. Native files and the existing Markdown export remain usable.
9. Known secrets are excluded. Exported text remains private until reviewed.
10. No account or network request is required to export a local saved conversation.

This draft does not promise lifecycle hooks, cloud traces, conversation replay,
or cost attribution. Those need additional source evidence and acceptance tests.
