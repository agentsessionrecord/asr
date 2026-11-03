# ASR Sessions for JetBrains IDEs

Use a gutter action to find the recorded sessions behind a local Git line.
Open a matched session in the bundled offline ASR viewer. Install `asr` with
its `blame` command first. See [the CLI tools](../../crates/asr-cli/TOOLS.md).

## Build and install locally

Use JDK 21, Node.js 22.13 or later, pnpm 12.11.2 and Git. The Gradle wrapper pins
Gradle 9.4.1. The SDK and platform test harness pin IntelliJ IDEA Community
2025.1.4, build 251. The first build downloads public SDK dependencies.

From the repository root:

```sh
pnpm install --frozen-lockfile
pnpm --dir apps/viewer run build
cd apps/jetbrains
./gradlew --project-cache-dir ../../target/jetbrains-gradle --no-daemon buildPlugin
```

Install `target/jetbrains/distributions/asr-sessions-0.1.0.zip` from the repository
root with **Settings > Plugins > Install Plugin from Disk**. No marketplace
registration is needed. No plugin is published by this build.

Open **Settings > ASR Sessions**. Set the installed ASR executable, absolute local
session files or directories, and optional absolute annotation files. Put one
path on each line. Do not add shell arguments to the executable field.
Settings belong to the application. A repository cannot supply its own commands.
Trust the project before using the plugin.

## Read a line

Click the history icon beside the first token on a line. Choose
**ASR Sessions Behind This Line** in the editor menu for lines without an icon.
The selected caret line is used by that menu action.

The evidence popup keeps **Edited by** and **Committed by** separate. It shows
citations, recorded prompt parts, the causing call, served or labeled requested
model, approval records, earlier alternatives and actor credit. It also shows
declared losses, gaps, related sessions, diagnostics and unresolved references.
Copied records receive no credit. A match is evidence and does not prove authorship.

Choose a session button to open the viewer dialog. The viewer runs locally
inside JCEF and needs the IDE's bundled JetBrains Runtime with JCEF. A runtime
without JCEF receives a notice. The dialog's rendering is not live-tested.
The platform harness checks its HTML and local file bridge.

The resolver uses local session headers. Duplicate or missing identities stay
unresolved. It skips symlinks and scans at most 10,000 entries and 33 levels.
Automatic viewing accepts regular files up to 64 MiB and headers up to 64 KiB.
Only the chosen session is loaded. Related files and annotations can be opened
with the viewer's file picker. Until then their links stay unresolved.

Save the buffer before looking up a line. Changes during a lookup discard its
result. There is no evidence cache. Lookups run off the UI thread and can be
cancelled. They have a 15 second deadline and a 16 MiB output limit.
The selected file must be local and belong to a Git repository.

Recorded text is inert in the popup and viewer. Commands, Markdown and resource
URLs are not executed or fetched. The viewer blocks network requests. The plugin
does not change session files or claim they are safe to share.

## Checks

Run the following from the repository root:

```sh
bash apps/jetbrains/check.sh
```

This builds the real CLI and viewer, runs the IntelliJ platform extension test
harness, and builds the installable ZIP. The tests check action registration,
gutter markers, a real local Git blame result, dirty buffers, exact numbers,
local session resolution, safe viewer HTML, and all sample and example streams.
Synthetic sessions pass the Node validator. Test fixtures are removed afterward.
`scripts/ci.sh` runs this check too.
