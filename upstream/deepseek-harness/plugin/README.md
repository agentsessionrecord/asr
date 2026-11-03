# dsh-plugin-asr-export

An unofficial Agent Session Record export plugin for DeepSeek Harness. It uses the public Cordis plugin API and does not modify the harness.

Requires Node 24.15 or newer and DeepSeek Harness 0.2.2-alpha.3. Build and pack locally:

```sh
npm ci
npm run build
npm run typecheck
npm test
npm pack
```

The standalone development graph pins Zod 4.6.6 with an npm override to fix
GHSA-mrhx-c7xc-m3w5. npm does not apply a dependency package's overrides to its
consumer. Set `"overrides": {"zod": "4.6.6"}` in the consuming profile's root
package.json and reinstall before installing this plugin. The tarball smoke
tests that consumer override and requires a clean production audit.

Install the resulting tarball in the web profile:

```sh
dsh plugin --profile web add /path/to/dsh-plugin-asr-export-0.1.0.tgz
dsh web --patch /path/to/cordis.patch.yml
```

Use this package's `cordis.patch.yml`. It inserts the `asr-export` plugin into a profile that already supplies `connection` and `sessionQuery`. The plugin serves `GET` and `HEAD /api/session.asr?sessionId=SESSION_ID` through the Host's authenticated owner connection. A browser with an active Host session can download the URL. The response uses the ASR media type and disables caching. Unloading the plugin removes the route.

The export reads one detached session-query observation. It retains source order, text, visible reasoning, calls, and final results. Fork-inherited events are excluded with a gap because their original ASR record identities are unavailable. Usage, model identity, settings, approvals, media, relationships, edits, and commits are declared missing. Unknown payloads and provider replay state are excluded. The export is not a redactor. Review conversation content before sharing.

This package is prepared for a separate repository with the `dsh-plugin` topic. It has not been published.
