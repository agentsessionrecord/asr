import { stat } from "node:fs/promises";
import { validateStream, validateFileStream, validateDirectory } from "./stream.js";
import { runConformance } from "./conformance.js";

const help = `Usage: asr-validate [--json] [--summary] <file.jsonl|file.manifest.json|directory|->
       asr-validate [--json] conformance <directory>

Checks session streams, annotations and collection manifests offline.
Directories are traversed recursively for .jsonl and .manifest.json files.
A .annotations.jsonl filename or first annotation record selects annotations.
Use - for standard input. A .manifest.json filename or leading manifest $schema
selects a collection manifest. --summary reports counts without diagnostics.
Warnings do not fail validation. Exit codes: 0 pass, 1 errors, 2 usage or I/O.
Passing validation does not establish source faithfulness or safety to share.`;

const report = ({ recordCount, ...result }) => ({ ...result, records: recordCount });
function printFile(result, { json, summary, io }) {
  if (json) io.out(JSON.stringify(report(result), null, 2));
  else {
    if (!summary) for (const problem of result.diagnostics) io.out(`${result.file}:${problem.line}${problem.pointer}: ${problem.severity} ${problem.requirement ? problem.requirement + " " : ""}${problem.code}: ${problem.message}`);
    io.out(`${result.file}: ${result.errors} errors, ${result.warnings} warnings, ${result.recordCount} complete records.`);
    if (summary) io.out(JSON.stringify(result.counts));
  }
}

export async function main(argv, io = { out: console.log, err: console.error }) {
  const json = argv.includes("--json");
  const summary = argv.includes("--summary");
  const args = argv.filter((arg) => !["--json", "--summary"].includes(arg));
  if (args.length === 1 && ["--help", "-h"].includes(args[0])) { io.out(help); return 0; }
  const conformance = args[0] === "conformance";
  if (args.length !== (conformance ? 2 : 1) || args.some((arg) => arg.startsWith("-") && arg !== "-") || (conformance && summary)) {
    io.err(help);
    return 2;
  }
  try {
    if (conformance) {
      const cases = runConformance(args[1]);
      const passed = cases.filter((entry) => entry.passed).length;
      if (json) io.out(JSON.stringify({ valid: passed === cases.length, passed, total: cases.length, cases }, null, 2));
      else {
        for (const entry of cases.filter((entry) => !entry.passed)) io.out(`${entry.name}: expected ${JSON.stringify(entry.expected)}, got ${JSON.stringify(entry.actual)}`);
        io.out(`${passed}/${cases.length} conformance cases passed.`);
      }
      return passed === cases.length ? 0 : 1;
    }
    const filename = args[0];
    if (filename !== "-" && (await stat(filename)).isDirectory()) {
      const total = { valid: true, files: 0, records: 0, errors: 0, warnings: 0, inputFailures: 0, counts: {} };
      let first = true;
      if (json && !summary) io.out('{"files":[');
      for await (const result of validateDirectory(filename, { summary })) {
        total.files++;
        if (result.error) { total.inputFailures++; total.valid = false; }
        else {
          total.valid &&= result.valid;
          total.records += result.recordCount;
          total.errors += result.errors;
          total.warnings += result.warnings;
          for (const [code, count] of Object.entries(result.counts)) total.counts[code] = (total.counts[code] ?? 0) + count;
        }
        if (!summary) {
          if (json) { io.out((first ? "" : ",") + JSON.stringify(report(result))); first = false; }
          else if (result.error) io.err(`${result.file}: ${result.error}`);
          else printFile(result, { json, summary, io });
        }
      }
      if (!total.files) throw new Error("No session, annotations or manifest files found.");
      if (json) io.out(summary ? JSON.stringify(total, null, 2) : `],"summary":${JSON.stringify(total)}}`);
      else io.out(`${total.files} files: ${total.errors} errors, ${total.warnings} warnings, ${total.records} complete records, ${total.inputFailures} input failures.\n${JSON.stringify(total.counts)}`);
      return total.inputFailures ? 2 : total.valid ? 0 : 1;
    }
    const result = filename === "-"
      ? await validateStream(process.stdin, { summary })
      : await validateFileStream(filename, { summary });
    printFile({ file: filename, ...result }, { json, summary, io });
    return result.valid ? 0 : 1;
  } catch (error) {
    if (json) io.err(JSON.stringify({ error: error.message }));
    else io.err(error.message);
    return 2;
  }
}
