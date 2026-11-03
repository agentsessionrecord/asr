import { readFileSync } from 'node:fs';
import { Git } from './src/git.ts';
import { loadStore } from './src/reader.ts';
import { analyzeCommit } from './src/attribution.ts';
import { authorshipCandidates, makeAuthorship, parseAuthorship, serializeAuthorship } from './src/git-ai.ts';
import { sessionUrl, writeLinks } from './src/notes.ts';

try {
  const [command, configFile, ref = 'HEAD'] = process.argv.slice(2);
  if (!configFile || !['inspect', 'write-links', 'export-ai', 'write-ai', 'read-ai'].includes(command))
    throw new Error('Usage: cli.ts inspect|write-links|export-ai|write-ai|read-ai CONFIG.json [COMMIT]');
  const config = JSON.parse(readFileSync(configFile, 'utf8'));
  const git = new Git(config.repo), store = loadStore(config.store), commit = git.resolve(ref);
  if (command === 'read-ai') {
    const text = git.note(commit, 'refs/notes/ai');
    if (text === undefined) throw new Error('No Git AI note is available.');
    const note = parseAuthorship(text);
    console.log(JSON.stringify({ note, candidates: authorshipCandidates(note, store.sessions, config.toolNames) }, null, 2));
  } else {
    const analysis = analyzeCommit(git, commit, store.sessions, config.repositories, store.annotations);
    if (command === 'inspect') console.log(JSON.stringify({ ...analysis, storeDiagnostics: store.diagnostics }, null, 2));
    else if (command === 'write-links') {
      const refs = new Set([...analysis.committedBy.map(c => c.session), ...analysis.lines.flatMap(l => l.editedBy ? [l.editedBy.session] : [])]);
      console.log(JSON.stringify({ changed: writeLinks(git, commit, [...refs].map(session => ({ session,
        ...(config.sessionBaseUrl ? { url: sessionUrl(config.sessionBaseUrl, session) } : {}) }))), sessions: refs.size }));
    } else {
      const output = makeAuthorship(analysis, store.sessions, config.toolNames), text = serializeAuthorship(output.note);
      if (command === 'export-ai') process.stdout.write(text);
      else console.log(JSON.stringify({ changed: git.writeNote(commit, 'refs/notes/ai', text, config.replaceGitAi === true) }));
      for (const d of output.diagnostics) console.error(d.code);
    }
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : 'Exporter failed.'); process.exitCode = 1;
}
