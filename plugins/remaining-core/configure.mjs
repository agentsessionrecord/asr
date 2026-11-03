import { fileURLToPath } from 'node:url';

export const events = {
  goose: ['SessionStart', 'SessionEnd', 'Stop', 'UserPromptSubmit', 'PreToolUse', 'PreToolUseResult', 'PostToolUse', 'PostToolUseFailure', 'BeforeReadFile', 'AfterFileEdit', 'BeforeShellExecution', 'AfterShellExecution'],
  'kimi-code': ['SessionStart', 'SessionEnd', 'UserPromptSubmit', 'Stop', 'StopFailure', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'SubagentStart', 'SubagentStop', 'PreCompact', 'PostCompact', 'Notification'],
  'grok-build': ['SessionStart', 'SessionEnd', 'UserPromptSubmit', 'Stop', 'StopFailure', 'StopCancelled', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'PermissionDenied', 'SubagentStart', 'SubagentStop', 'PreCompact', 'PostCompact', 'Notification'],
  'deepseek-harness': ['SessionStart', 'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'Stop', 'SubagentStart', 'SubagentStop'],
  crush: ['SessionStart', 'SessionEnd', 'TurnStart', 'TurnEnd', 'StopFailure', 'Interrupt', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure', 'PermissionRequest', 'PermissionResult', 'PreCompact', 'PostCompact'],
};
// The legacy list stays valid for the archived Python CLI.
export const kimiV2Events = ['SessionStart', 'SessionEnd', 'UserPromptSubmit', 'UserPromptQueued',
  'TurnStarted', 'Stop', 'StopFailure', 'Interrupt', 'PreToolUse', 'PostToolUse',
  'PostToolUseFailure', 'PermissionRequest', 'PermissionResult', 'SessionHeartbeat',
  'SubagentStart', 'SubagentStop', 'TaskStarted', 'PreCompact', 'PostCompact', 'Notification'];
const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
export function configuration(agent, { kimiVersion = 1 } = {}) {
  const command = `node ${quote(fileURLToPath(new URL('./command.mjs', import.meta.url)))} ${agent}`;
  if (agent === 'kimi-code') return (kimiVersion === 2 ? kimiV2Events : events[agent]).map(event =>
    `[[hooks]]\nevent = ${JSON.stringify(event)}\ncommand = ${JSON.stringify(command)}\ntimeout = 1\n`).join('\n');
  if (agent === 'crush') return JSON.stringify({ hooks: Object.fromEntries(events[agent].map(event =>
    [event, [{ name: 'asr-recorder', command, timeout: 1 }]])) }, null, 2) + '\n';
  return JSON.stringify({ hooks: Object.fromEntries(events[agent].map(event =>
    [event, [{ hooks: [{ type: 'command', command, timeout: 1 }] }]])) }, null, 2) + '\n';
}
