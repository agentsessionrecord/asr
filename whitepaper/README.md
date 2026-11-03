# Agent Session Record white paper

`whitepaper.md` is the source. It is plain GitHub Markdown with YAML frontmatter, so it reads correctly on GitHub and can be rendered by a website as is. The build turns it into a print-styled HTML page and a PDF.

## Build

Requirements: Node.js 20 or later, pnpm, and Google Chrome or Chromium. Poppler's `pdftotext` and `pdfinfo` are optional. With them, the table of contents gets page numbers and the build reports the page count.

```sh
pnpm --dir whitepaper install
node whitepaper/build.mjs              # HTML and PDF
node whitepaper/build.mjs --html-only  # HTML only
node whitepaper/build.mjs --chrome=/path/to/chrome   # or set CHROME
```

Output goes to `whitepaper/dist/` (not committed):

- `whitepaper.html`: a standalone page with the stylesheet inlined.
- `agent-session-record-whitepaper.pdf`: printed from that page by headless Chrome (`--headless=new --no-pdf-header-footer --print-to-pdf`).

The build makes no network requests. Fonts come from the local system: Palatino (or URW P052, Noto Serif, Georgia) for text, Lato (or another sans serif) for headings and tables, and a local monospace font for code. Running headers and page numbers use CSS paged-media margin boxes, which need Chrome 131 or later.

When `pdftotext` is available, the PDF is printed twice: the first print is read back to find the page each heading landed on, and the second fills those numbers into the table of contents.

## Editing conventions

- Headings carry their section numbers (`## 3. The format in brief`). The build styles the number and builds the table of contents from level-2 and level-3 headings.
- Citations are written `[[3](#ref-3)]` and point at `<a id="ref-3"></a>` anchors in the numbered References list. Number references in order of first use.
- The block between `<!-- titleblock -->` and `<!-- /titleblock -->` is the title for GitHub readers. The PDF builds its own cover from the frontmatter (`title`, `subtitle`, `version`, `date`, `authors`, `repository`) and drops that block. A website that renders the frontmatter title can drop it too.
- In the PDF, the Abstract section moves onto the cover.
- Keep one record per line in JSONL source examples. The build pretty-prints them for the PDF.
