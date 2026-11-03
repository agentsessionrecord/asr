# ASR session viewer

Open ASR format 0.1 files in a static page. Files stay on your device.
The page has no server, runtime dependencies or remote assets.

## Build and open

Install Node.js 22.13 or later and pnpm 12.11.2. From the repository root:

```sh
pnpm install --frozen-lockfile
pnpm --dir apps/viewer run build
```

Open `apps/viewer/dist/index.html` directly in a browser. You can copy the
`dist` folder to another machine. The HTML file contains the application,
styles and worker. The other built module supports the unit tests.

Use a current browser with Web Workers, local file input and JSON parse source
context support. Chromium 145 is covered by the browser tests. Firefox and
Safari have not been tested.

Choose **Open files**, choose **Open folder**, or drop files or folders onto
the page. Folder selection opens `.jsonl` files and keeps each file separate.
Native logs without an ASR header are shown with a notice. This viewer does
not convert native logs. Other file types receive an unsupported-file notice.

## Read a session

The timeline keeps file order. It shows messages with recorded authorship,
tool requests, results, approval decisions, file changes, version control,
model calls, settings, offered tools and history gaps. Unknown values stay
unknown. A tool outcome does not establish an approval decision.

Call, result and approval buttons link records by a unique call ID. Duplicate
call IDs leave the relationship unresolved. Effective input learned at tool
completion appears on the result and on its paired call. Every decision and
result stays at its own position.

Recorded patches and replacement snippets use diff colors. A comparison of
full recorded states is labeled as a display comparison. Missing edit text
stays missing. The viewer does not derive line attribution or verify Git data.

Session links resolve only against opened files. Parent links, subagent calls
and results, and child-side links all support navigation. An unavailable file
stays unresolved. Copied records have a copy marker. The model accounting
table excludes copied calls, keeps currencies separate and shows coverage for
unknown usage or cost. Reported session totals stay separate from those sums.

Annotation files show later facts and links to their targets. Corrections and
latest values determine their current or historical marker. Test and version
control annotations remain additive. An annotation does not become a session
action or a source of work credit.

Choose **Read record** to inspect more fields and original record bytes. Text
is always rendered as text. Commands, URLs, embedded resources and media are
never executed, fetched or loaded. The page does not validate a file or make
a claim about whether it can be shared safely.

## Large files and limits

The worker reads in 1 MiB chunks and keeps byte ranges and relationship
metadata instead of retaining message and tool payloads. Memory grows with
the number of records and links. Only a small window of timeline cards is in
the DOM. Virtual scrolling uses a bounded physical height to keep late
records reachable beyond browser layout limits.

One selection holds at most 64 files and 250,000 indexed lines in total.
Exceeding either limit stops loading with an error.
See [the threat model](../../SECURITY.md) for the trust boundaries.

A single line above 16 MiB is marked with a reader diagnostic and is not
decoded into structured fields. It remains available as original bytes in
64 KiB pages. Structured inspection shows at most 100 sections, 20,000
characters per section and 60,000 characters in total. Timeline cards show
shorter excerpts. The original file is never changed. A UTF-8 character split
across byte pages can appear as a replacement character at the page boundary.
Text is preserved when the complete record is decoded.

Malformed complete lines and invalid UTF-8 receive diagnostics. Reading
continues after them. An unterminated final line is marked incomplete and is
not used as a record. Reopen the file after it changes to read newly completed
lines. This page does not watch files or save edited streams.

## Tests

From the repository root:

```sh
pnpm --dir apps/viewer exec playwright install chromium --only-shell
pnpm --dir apps/viewer run ci
```

The tests also run from `scripts/ci.sh`. Set `CHROME` or
`ASR_VIEWER_CHROMIUM` to use an installed Chromium executable instead of the
Playwright browser. The workspace CI already supplies `CHROME`.

Unit tests cover ordering, conservative pairing, exact numbers, recovery,
settings, losses, copies, accounting, annotations and diff display. Browser
tests load every file under `samples/` and `examples/` through a `file:` URL.
They also test file and folder input, drops, local links, hostile content,
raw inspection, a 220 MiB stream and navigation to record 100001. Synthetic
sessions are validated with the Node validator. Scratch files are removed.

Set `ASR_VIEWER_EVIDENCE_DIR` to a directory outside Git to save two sample
screenshots and a JSON test summary. The report contains counts and timing
measurements. It does not copy session text.
