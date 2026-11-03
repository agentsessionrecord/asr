# ASR documentation site

The website for Agent Session Record uses [Mintlify](https://mintlify.com) and is served from Cloudflare at https://agentsessionrecord.org.

## Commands

Run these from `site/` with Node.js 22 and pnpm. Build the white paper PDF first with `node whitepaper/build.mjs` from the repository root.

| Command | What it does |
|---|---|
| `pnpm install` | Install the build and publishing dependencies. |
| `pnpm build` | Assemble `.mint/` and check internal links and anchors. |
| `pnpm dev` | Build and preview at `http://localhost:3000`. |
| `pnpm check` | Require the PDF, then run Mintlify validation and link checks. |
| `pnpm run deploy` | Check, export and publish the site with Wrangler. |
| `node deploy.mjs --dry-run` | Prepare the export and run Wrangler without uploading. |

## Content sources

Hand-written pages live in `pages/`. Navigation is in `pages/docs.json`. The build generates `.mint/`, which is ignored by Git. Rebuild after source changes. Edits to generated files are overwritten.

| Source | Route |
|---|---|
| `spec/*.md` | `/spec/<name>` |
| `guides/*.md` | `/guides/<name>` |
| `agents/index.md` | `/agents` |
| `agents/*.md` | `/agents/<name>` |
| `agents/agents.json` | `/agents/agents.json` |
| `whitepaper/whitepaper.md` | `/whitepaper` |
| `whitepaper/dist/agent-session-record-whitepaper.pdf` | `/downloads/agent-session-record-whitepaper.pdf` |

Markdown sources use repository-relative links. The build converts them to site routes, preserves heading links and pretty-prints JSON examples. Sources keep one record per JSONL line. Add navigable pages to `pages/docs.json`.

## Published assets

`public-assets.mjs` supplies the same explicit asset list to the assembly and export steps:

- `schema/v0/agent-session.schema.json`
- `schema/v0/annotation.schema.json`
- `schema/v0/discovery.schema.json`
- `schema/v0/manifest.schema.json`
- `examples/collection.manifest.json`
- `agents/agents.json`

All listed assets are required. A missing asset fails the copy. The build does not generate or validate schemas.

Mintlify's static export omits JSON assets, so `deploy.mjs` restores them after export. It copies only the assets listed above.

## Hosting

`wrangler.jsonc` configures the Worker and static assets. Deployment requires an authenticated account authorized for the domain.

`deploy.mjs` moves exported `<page>/index.html` files to `<page>.html`, adds Markdown page copies and the public assets, then copies the headers and error page from `cloudflare/`.

`cloudflare/worker.js` redirects the `www` host to the bare domain. Client-side navigation requests receive the exported `index.txt` payload for the page. Other requests use the static assets.

## Tool catalog

The pages in `pages/tools/` group integrations by convert, record, collect, view,
export, import and patch jobs. They link to repository READMEs for installation,
source limits and test evidence. Add each page to `pages/docs.json`.
Run `node scripts/check-tool-docs.mjs` from the repository root to check registry
coverage, README targets and navigation. It performs no remote link requests.
The site records no session data. Its build checks documentation links and
anchors, not the behavior of each listed tool.
