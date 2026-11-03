import * as vscode from 'vscode';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { blame, findSession, gitRoot, reportText, sessionCommand, viewerHtml, type Report, type Settings } from './core';

function settings(): Settings {
  const config = vscode.workspace.getConfiguration('asr');
  return { executable: config.get('executable', 'asr'), sessions: config.get('sessions', []), annotations: config.get('annotations', []) };
}
export function activate(context: vscode.ExtensionContext) {
  const pending = new Set<AbortController>();
  context.subscriptions.push({ dispose() { for (const controller of pending) controller.abort(); } });
  async function lookup(document: vscode.TextDocument, line: number, token?: vscode.CancellationToken): Promise<Report> {
    if (!vscode.workspace.isTrusted) throw new Error('Trust the workspace before running ASR.');
    if (document.uri.scheme !== 'file') throw new Error('ASR requires a local file.');
    if (document.isDirty) throw new Error('Save the file before looking up line evidence.');
    const version = document.version;
    const controller = new AbortController(); pending.add(controller);
    const subscription = token?.onCancellationRequested(() => controller.abort());
    if (token?.isCancellationRequested) controller.abort();
    try {
      const repo = await gitRoot(document.uri.fsPath);
      const result = await blame(settings(), repo, document.uri.fsPath, line + 1, controller.signal);
      if (document.isDirty || document.version !== version) throw new Error('The file changed during lookup. Save and retry.');
      return result;
    } finally { subscription?.dispose(); pending.delete(controller); }
  }
  context.subscriptions.push(vscode.languages.registerHoverProvider({ scheme: 'file' }, {
    async provideHover(document, position, token) {
      if (!vscode.workspace.isTrusted || !settings().sessions.length) return;
      const version = document.version;
      try {
        const report = await lookup(document, position.line, token);
        if (token.isCancellationRequested || document.version !== version) return;
        const text = new vscode.MarkdownString(); text.appendCodeblock(reportText(report), 'text');
        const sessions = new Set([...report.editedBy, ...report.committedBy].map(e => e.session).filter((s): s is string => typeof s === 'string'));
        for (const session of sessions) {
          const uri = sessionCommand(session);
          text.appendMarkdown(`\n\n[Open session in viewer](${uri})`);
        }
        text.isTrusted = { enabledCommands: ['asr.openSession'] };
        text.supportHtml = false;
        return new vscode.Hover(text, new vscode.Range(position.line, 0, position.line, document.lineAt(position.line).text.length));
      } catch (error) {
        if (token.isCancellationRequested) return;
        return new vscode.Hover(new vscode.MarkdownString().appendText((error as Error).message));
      }
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('asr.showLine', async () => {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return;
    try {
      const report = await lookup(editor.document, editor.selection.active.line);
      const panel = vscode.window.createWebviewPanel('asr.evidence', 'ASR Line Evidence', vscode.ViewColumn.Beside, { enableScripts: false, enableCommandUris: ['asr.openSession'], localResourceRoots: [] });
      const escape = (s: string) => s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
      const links = [...new Set([...report.editedBy, ...report.committedBy].map(e => e.session).filter((s): s is string => typeof s === 'string'))].map(session => `<p><a href="${escape(sessionCommand(session))}">Open session in viewer</a></p>`).join('');
      panel.webview.html = `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'"></head><body>${links}<pre>${escape(reportText(report))}</pre></body></html>`;
      return report;
    } catch (error) { void vscode.window.showErrorMessage((error as Error).message); }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('asr.openSession', async (reference?: unknown) => {
    try {
      if (!vscode.workspace.isTrusted) throw new Error('Trust the workspace before opening ASR.');
      if (reference === undefined) reference = await vscode.window.showInputBox({ prompt: 'Session reference from ASR line evidence' });
      if (typeof reference !== 'string' || !reference) return;
      const file = await findSession(settings().sessions, reference);
      const html = await viewerHtml(await readFile(path.join(context.extensionPath, 'dist/viewer.html'), 'utf8'), file);
      const panel = vscode.window.createWebviewPanel('asr.viewer', 'ASR Session', vscode.ViewColumn.Beside, { enableScripts: true, localResourceRoots: [] });
      panel.webview.html = html;
      return { opened: true };
    } catch (error) { void vscode.window.showErrorMessage((error as Error).message); }
  }));
}
