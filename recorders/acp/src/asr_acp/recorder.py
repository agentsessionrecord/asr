"""ACP v2 alpha.9 upserts and v1 compatibility, folded at receipt completion."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from agent_session_record import Writer, session_reference
from agent_session_record.repository import repository_snapshot
from agent_session_record.content import reasoning_part
from agent_session_record.content import content_part
from agent_session_record.safety import private_directory, read_bounded
from asr_litellm.privacy import Scrubber

META = 'org.agentsessionrecord.acp'
MISSING = ['usage', 'model', 'timestamps', 'tool_output', 'approvals', 'agent_settings',
           'tools', 'exit_codes', 'commits', 'subagents', 'copies', 'prompt_authorship',
           'session_lifecycle', 'file_changes']
MAX_FRAME = 16 * 1024 * 1024
MAX_CAPTURE_BYTES = 64 * 1024 * 1024
MAX_OBSERVATIONS = 100_000
MAX_SESSIONS = 128


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def key(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def patch(target, update):
    for name, value in update.items():
        if name == '_meta' and isinstance(value, dict):
            metadata = target.setdefault(name, {})
            for label, item in value.items():
                if item is None:
                    metadata.pop(label, None)
                else:
                    metadata[label] = deepcopy(item)
        elif value is None and name != 'rawInput':
            target.pop(name, None)
        else:
            target[name] = deepcopy(value)


def append_parts(parts, block):
    block = deepcopy(block)
    if parts and block.get('type') == 'text' and parts[-1].get('type') == 'text':
        parts[-1]['text'] += block['text']
    else:
        parts.append(block)


class Session:
    def __init__(self, recorder, sid, cwd=None, parent=None, start=False):
        self.recorder, self.sid = recorder, sid
        self.path = recorder.directory / (key([recorder.agent, sid]) + '.jsonl')
        header = {'agent': {'name': recorder.agent}, 'sessionId': sid,
                  'producer': {'name': 'asr-acp', 'version': '0.1.0', 'method': 'recorder',
                               'source': 'acp-schema-v2.0.0-alpha.9-and-v1'}, 'missing': MISSING.copy()}
        if recorder.version:
            header['agent']['version'] = recorder.version
        if start:
            header.update(repository_snapshot(cwd))
        if parent:
            header['parent'] = parent
        if recorder.scrubber.text(sid) != sid:
            raise ValueError('Secret session identity cannot be recorded')
        header = recorder.scrubber.clean(header)
        if recorder.scrubber.redacted:
            header['missing'].append('redacted_content')
            header['truncated'] = True
        existing = read_bounded(self.path, MAX_FRAME) if self.path.exists() else None
        self.writer = Writer.resume(self.path) if existing is not None else Writer(self.path, header)
        self.messages, self.calls, self.compactions = {}, {}, {}
        self.seen = {}
        self.missing = set(MISSING)
        # Stable entities already written are deduplicated across a process restart.
        if existing is not None:
            for line in existing.decode('utf-8').splitlines():
                record = json.loads(line)
                native = record.get('_meta', {}).get(META, {}).get('entity')
                if native:
                    self.seen[native] = record.get('_meta', {}).get(META, {}).get('entityHash')
                self.missing.update(record.get('missing', []))
                recorder.record_ids.setdefault(self.sid, set()).add(record['id'])

    def emit(self, value, ts):
        self.recorder.scrubber.redacted = False
        value = deepcopy(value)
        if value['type'] in ('message', 'tool_result') and 'content' in value:
            value['content'] = [content_part(part) for part in value['content']]
        clean = self.recorder.scrubber.clean(value)
        if self.recorder.scrubber.redacted or '[REDACTED]' in json.dumps(clean):
            clean['truncated'] = True
            if 'redacted_content' not in self.missing:
                self.missing.add('redacted_content')
                self.writer.update({'missing': ['redacted_content']})
        if ts:
            clean['ts'] = ts
        elif self.recorder.parents.get(self.sid, {}).get('kind') == 'fork' and clean['type'] in ('message', 'tool_call', 'tool_result', 'file_change', 'inference'):
            clean['copiedFrom'] = {'session': self.recorder.parents[self.sid]['session']}
        return self.writer.append(clean)

    def loss(self, loss, ts):
        if loss not in self.missing:
            self.missing.add(loss)
            self.emit({'type': 'session_info', 'missing': [loss]}, ts)

    def gap(self, reason, ts, detail):
        self.emit({'type': 'gap', 'reason': reason, 'detail': detail}, ts)

    def entity(self, name, state, record, ts):
        state = {k: v for k, v in state.items() if k not in ('_callInput', '_hadInput', '_filesEmitted')}
        fingerprint = key(state)
        if name in self.seen:
            if self.seen[name] != fingerprint:
                self.loss('post_completion_updates', ts)
                self.emit({'type': 'session_info', 'missing': ['post_completion_updates'],
                           '_meta': {META: {'entity': name, 'lateUpdate': state}}}, ts)
            return
        self.seen[name] = fingerprint
        if ts is None and self.recorder.parents.get(self.sid, {}).get('kind') == 'fork':
            parent_ref = self.recorder.parents[self.sid]['session']
            record['copiedFrom'] = {'session': parent_ref}
        record.setdefault('_meta', {})[META] = {'entity': name, 'entityHash': fingerprint, 'source': state}
        # Native message IDs are used when valid and collision-free. Other records use writer IDs.
        native = state.get('messageId') if record['type'] == 'message' else None
        if isinstance(native, str) and native and len(native) <= 256 and not any(ord(c) < 32 or ord(c) == 127 for c in native):
            # A native ID can be shared by message and thought entities.
            if native not in self.recorder.record_ids.setdefault(self.sid, set()):
                record['id'] = native
                self.recorder.record_ids[self.sid].add(native)
        self.emit(record, ts)

    def flush_message(self, mid, ts, interrupted=False):
        state = self.messages.pop(mid)
        role = state['_role']
        content = deepcopy(state.get('content', []))
        if role == 'thought':
            content = [reasoning_part(text=p['text']) if p.get('type') == 'text' else p for p in content]
        record = {'type': 'message', 'role': 'assistant' if role in ('assistant', 'thought') else 'user', 'content': content}
        if role == 'injected':
            record.update(author='agent', origin='injected')
            if state.get('senderSessionId'):
                record['from'] = self.recorder.reference(state['senderSessionId'])
        elif role == 'user':
            record['origin'] = 'prompt'
        if interrupted:
            record['status'] = 'interrupted'
        self.entity('message:' + mid, state, record, ts)

    def flush(self, ts, interrupted=False):
        for mid in list(self.messages):
            self.flush_message(mid, ts, interrupted)

    def tool(self, update, ts):
        cid = str(update['toolCallId'])
        state = self.calls.setdefault(cid, {})
        patch(state, update)
        if 'result:' + cid in self.seen:
            self.entity('result:' + cid, state, {}, ts)
            return
        final = state.get('status') in ('completed', 'failed', 'cancelled')
        # Pending input may still be streaming. A running or final status closes the request.
        if state.get('status') == 'in_progress' or final:
            call = {'type': 'tool_call', 'callId': cid}
            for native, core in [('name', 'name'), ('kind', 'kind'), ('locations', 'locations'), ('rawInput', 'input')]:
                if native in state:
                    call[core] = state[native]
            request = {k: state[k] for k in ('toolCallId', 'name', 'kind', 'locations', 'rawInput') if k in state}
            # Input learned at completion belongs on the result, never a second call.
            if 'call:' + cid not in self.seen:
                self.entity('call:' + cid, request, call, ts)
                state['_callInput'] = deepcopy(call.get('input'))
                state['_hadInput'] = 'input' in call
        if final:
            result = {'type': 'tool_result', 'callId': cid, 'status': state['status']}
            if 'rawInput' in state and (not state.get('_hadInput') or state.get('_callInput') != state['rawInput']):
                result['input'] = state['rawInput']
            content = state.get('content')
            if content is not None:
                result['content'] = [part['content'] for part in content if part.get('type') == 'content']
            elif isinstance(state.get('rawOutput'), str):
                result['content'] = [{'type': 'text', 'text': state['rawOutput']}]
            self.entity('result:' + cid, state, result, ts)
            if not state.get('_filesEmitted'):
                for part in content or []:
                    if part.get('type') != 'diff':
                        continue
                    changes = part.get('changes', [])
                    for change in changes:
                        op = change['operation']
                        record = {'type': 'file_change', 'callId': cid, 'path': change['path'],
                                  'op': op if op in ('add', 'delete', 'modify', 'move', 'copy') else 'unknown',
                                  'status': {'completed': 'applied', 'failed': 'failed'}.get(state['status'], 'unknown')}
                        if 'oldPath' in change:
                            record['oldPath'] = change['oldPath']
                        # A multi-file patch is never attached to one file as if it were per-file.
                        if len(changes) == 1 and part.get('patch', {}).get('format') == 'git_patch':
                            record['patch'] = part['patch']['text']
                        self.emit(record, ts)
                state['_filesEmitted'] = True


class Recorder:
    def __init__(self, directory, agent, *, clock=now, secrets=(), selectors=None):
        self.directory = private_directory(directory)
        self.agent, self.clock, self.version = agent, clock, None
        self.scrubber = Scrubber(secrets=secrets)
        self.sessions, self.requests, self.parents, self.record_ids = {}, {}, {}, {}
        self.selectors = selectors or {}
        self.replaying = set()
        self.pending_fork_updates = {}
        self.legacy_counter = 0
        self.closed = False
        self.disabled = False
        self.observed_bytes = self.observations = 0
        self.failures = 0

    def disable(self):
        if self.disabled:
            return
        self.disabled = True
        self.failures += 1
        for session in self.sessions.values():
            try:
                session.loss('capture_stopped', self.clock())
                session.gap('not_recorded', self.clock(), 'Capture stopped after an input, storage or state limit failure.')
            except Exception:
                pass
            finally:
                try:
                    session.writer.close()
                except Exception:
                    pass
            session.messages.clear()
            session.calls.clear()
            session.compactions.clear()
        self.requests.clear()
        self.pending_fork_updates.clear()

    def reference(self, sid):
        return session_reference(self.agent, str(sid))

    def session(self, sid, cwd=None, *, start=False):
        sid = str(sid)
        if sid not in self.sessions:
            if len(self.sessions) >= MAX_SESSIONS:
                raise ValueError('session_capacity')
            self.sessions[sid] = Session(self, sid, cwd, self.parents.get(sid), start=start)
        return self.sessions[sid]

    def settings(self, session, options, ts):
        settings = {}
        for option in options or []:
            field = self.selectors.get(option.get('id'))
            if field in ('mode', 'approval') and 'currentValue' in option:
                settings[field] = option['currentValue']
        if settings:
            session.emit({'type': 'session_info', 'agentSettings': settings}, ts)

    def observe(self, direction, message):
        if self.disabled or self.closed:
            return
        try:
            size = len(json.dumps(message, ensure_ascii=False, allow_nan=False).encode('utf-8'))
            self.observed_bytes += size
            self.observations += 1
            if size > MAX_FRAME or self.observed_bytes > MAX_CAPTURE_BYTES or self.observations > MAX_OBSERVATIONS:
                raise ValueError('capture_capacity')
            self._observe(direction, message)
        except Exception:
            self.disable()

    def _observe(self, direction, message):
        """direction is client or agent. JSON-RPC IDs are scoped by request direction."""
        ts = self.clock()
        method = message.get('method')
        params = message.get('params', {})
        if method:
            if 'id' in message:
                self.requests[(direction, key(message['id']))] = (method, deepcopy(params))
                if method in ('session/load', 'session/resume'):
                    self.replaying.add(str(params['sessionId']))
            if direction == 'client' and method == 'session/prompt':
                sid = str(params['sessionId'])
                if sid in self.replaying:
                    self.session(sid).flush(None)
                    self.replaying.discard(sid)
            if direction == 'agent' and method == 'session/update':
                sid = str(params['sessionId'])
                update = self.scrubber.clean(params['update'])
                if sid not in self.sessions and any(request[0] == 'session/fork' for request in self.requests.values()):
                    self.pending_fork_updates.setdefault(sid, []).append((update, ts))
                    return
                session = self.session(sid)
                self.update(session, update, None if sid in self.replaying else ts)
                if update.get('sessionUpdate') == 'state_update' and update.get('state') == 'idle' and self.parents.get(sid, {}).get('kind') == 'fork':
                    self.replaying.discard(sid)
            return
        other = 'agent' if direction == 'client' else 'client'
        request = self.requests.pop((other, key(message.get('id'))), None)
        if not request:
            return
        method, params = request
        result = self.scrubber.clean(message.get('result', {}))
        if method == 'initialize' and 'error' not in message:
            info = result.get('info', result.get('agentInfo', {}))
            self.version = info.get('version')
        elif method in ('session/new', 'session/fork') and 'error' not in message:
            sid = str(result['sessionId'])
            if method == 'session/fork':
                self.parents[sid] = {'session': self.reference(params['sessionId']), 'kind': 'fork'}
            session = self.session(sid, params.get('cwd'), start=True)
            if method == 'session/fork':
                self.replaying.add(sid)
                for update, _ in self.pending_fork_updates.pop(sid, []):
                    self.update(session, update, None)
                session.flush(None)
            if method == 'session/new':
                # Only explicit session creation supplies a start receipt time.
                session.emit({'type': 'session_info', '_meta': {META: {'createdAt': ts}}, 'missing': []}, ts)
            self.settings(session, result.get('configOptions'), ts)
        elif method in ('session/load', 'session/resume'):
            sid = str(params['sessionId'])
            session = self.session(sid, params.get('cwd'))
            session.flush(None)
            self.replaying.discard(sid)
            if 'error' not in message:
                self.settings(session, result.get('configOptions'), ts)
        elif method == 'session/prompt' and 'error' not in message:
            session = self.session(params['sessionId'])
            mid = str(result.get('messageId') or 'prompt:' + key(params))
            state = {'messageId': mid, 'content': self.scrubber.clean(params.get('prompt', [])), '_role': 'user'}
            # An echoed user message and the accepted prompt share one stable identity.
            if 'message:' + mid not in session.seen and mid not in session.messages:
                session.messages[mid] = state
                session.flush_message(mid, ts)
            if 'stopReason' in result:  # v1 prompt responses complete a whole turn.
                session.flush(ts, result['stopReason'] == 'cancelled')
        elif method == 'session/request_permission' and 'error' not in message:
            session = self.session(params['sessionId'])
            self.permission(session, self.scrubber.clean(params), result, ts)
        elif method == 'session/close' and 'error' not in message:
            session = self.session(params['sessionId'])
            session.flush(ts)
            session.emit({'type': 'session_info', 'endedAt': ts}, ts)
        elif method == 'session/set_config_option' and 'error' not in message:
            self.settings(self.session(params['sessionId']), result.get('configOptions'), ts)

    def permission(self, session, params, result, ts):
        outcome = result.get('outcome', {})
        selected = [o for o in params.get('options', []) if o.get('optionId') == outcome.get('optionId')]
        kind = selected[0].get('kind') if len(selected) == 1 else None
        decision = {'allow_once': 'approved', 'allow_always': 'approved', 'reject_once': 'denied', 'reject_always': 'denied'}.get(kind)
        if outcome.get('outcome') == 'cancelled':
            decision = 'cancelled'
        elif outcome.get('outcome') != 'selected':
            decision = None
        if not decision:
            session.loss('unknown_permission_options', ts)
            session.emit({'type': 'session_info', 'missing': ['approvals'], '_meta': {META: {'permissionRequest': params, 'permissionResponse': result}}}, ts)
            return
        subject = params.get('subject') or {}
        tool = subject.get('toolCall') or params.get('toolCall') or {}
        cid = tool.get('toolCallId') or subject.get('toolCallId')
        record = {'type': 'approval', 'decision': decision, 'native': {'request': params, 'outcome': outcome}}
        if cid:
            record['callId'] = str(cid)
        if params.get('title'):
            record['subject'] = params['title']
        elif not cid:
            session.loss('approval_subject', ts)
        if decision != 'cancelled' and kind in ('allow_once', 'reject_once'):
            record['scope'] = 'once'
        # Always labels do not establish persistence. ACP does not establish a decider.
        session.emit(record, ts)

    def update(self, session, update, ts):
        kind = update['sessionUpdate']
        roles = {'user_message': 'user', 'agent_message': 'assistant', 'agent_thought': 'thought', 'session_message': 'injected'}
        base = kind.removesuffix('_chunk')
        if base in roles:
            mid = update.get('messageId')
            if mid is None:  # v1 has no stable message identity.
                if session.messages and next(reversed(session.messages.values()))['_role'] != roles[base]:
                    session.flush(ts)
                mid = 'legacy:' + str(self.legacy_counter)
                if not session.messages:
                    self.legacy_counter += 1
                    mid = 'legacy:' + str(self.legacy_counter)
                else:
                    mid = next(reversed(session.messages))
                session.loss('message_ids', ts)
            mid = str(mid)
            state = session.messages.setdefault(mid, {'messageId': mid, '_role': roles[base], 'content': []})
            if kind.endswith('_chunk'):
                append_parts(state.setdefault('content', []), update['content'])
            else:
                clean = {k: v for k, v in update.items() if k != 'sessionUpdate' and not (k in ('senderSessionId', 'recipientSessionId') and v is None)}
                patch(state, clean)
                state.setdefault('content', [])
        elif kind in ('tool_call', 'tool_call_update'):
            session.tool(update, ts)
        elif kind == 'tool_call_content_chunk':
            if 'result:' + str(update['toolCallId']) in session.seen:
                session.loss('post_completion_updates', ts)
                session.emit({'type': 'session_info', 'missing': ['post_completion_updates'], '_meta': {META: {'lateUpdate': update}}}, ts)
                return
            state = session.calls.setdefault(str(update['toolCallId']), {})
            blocks = state.setdefault('content', [])
            block = update['content']
            if blocks and block.get('type') == 'content' and blocks[-1].get('type') == 'content':
                inner = [blocks[-1]['content']]
                append_parts(inner, block['content'])
                blocks[-1:] = [{'type': 'content', 'content': p} for p in inner]
            else:
                blocks.append(deepcopy(block))
        elif kind == 'state_update' and update.get('state') in ('idle', 'requires_action'):
            session.flush(ts, update.get('stopReason') == 'cancelled')
        elif kind == 'session_info_update' and isinstance(update.get('title'), str):
            session.emit({'type': 'session_info', 'title': update['title']}, ts)
        elif kind in ('config_option_update', 'config_options_update'):
            self.settings(session, update.get('configOptions', []), ts)
        elif kind == 'usage_update':
            record = {'type': 'session_info', 'missing': ['usage'], '_meta': {META: {'usage': update}}}
            cost = update.get('cost')
            if cost and isinstance(cost.get('amount'), (int, float)) and cost.get('currency'):
                record['cost'] = {'amount': cost['amount'], 'currency': cost['currency']}
            session.emit(record, ts)
        elif kind == 'subagent_update':
            child = str(update['sessionId'])
            self.parents[child] = {'session': self.reference(session.sid), 'kind': 'subagent'}
            if child in self.sessions:
                self.sessions[child].loss('late_parent_association', ts)
            session.emit({'type': 'session_info', 'missing': ['subagents'], '_meta': {META: {'subagent': update}}}, ts)
        elif kind in ('compaction_update', 'compaction_summary_chunk'):
            cid = str(update['compactionId'])
            if 'compaction:' + cid in session.seen:
                session.loss('post_completion_updates', ts)
                session.emit({'type': 'session_info', 'missing': ['post_completion_updates'], '_meta': {META: {'lateUpdate': update}}}, ts)
                return
            state = session.compactions.setdefault(cid, {'summary': []})
            if kind.endswith('_chunk'):
                append_parts(state.setdefault('summary', []), update['content'])
            else:
                patch(state, update)
            if state.get('status') == 'completed' and 'compaction:' + cid not in session.seen:
                session.entity('compaction:' + cid, state, {'type': 'message', 'role': 'user', 'author': 'harness', 'origin': 'compaction', 'content': state.get('summary', [])}, ts)
                session.gap('not_retained', ts, 'Compaction replaced earlier model context. Captured observations remain in this stream.')
        elif kind == 'notice':
            session.emit({'type': 'message', 'role': 'user', 'author': 'harness', 'origin': 'notice', 'content': update.get('content', [{'type': 'text', 'text': update.get('title', '')}] + ([{'type': 'text', 'text': update['description']}] if isinstance(update.get('description'), str) else [])), '_meta': {META: {'notice': update}}}, ts)
        else:
            session.loss('unsupported_updates', ts)
            session.emit({'type': 'session_info', 'missing': ['unsupported_updates'], '_meta': {META: {'update': update}}}, ts)

    def malformed(self):
        if self.disabled:
            return
        self.observations += 1
        if self.observations > MAX_OBSERVATIONS:
            self.disable()
            return
        for session in self.sessions.values():
            try:
                session.gap('unparseable', self.clock(), 'An ACP frame could not be parsed.')
            except Exception:
                self.disable()
                return

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.disabled:
            return
        ts = self.clock()
        for sid, updates in self.pending_fork_updates.items():
            session = self.session(sid)
            session.loss('unresolved_fork', ts)
            session.gap('not_recorded', ts, 'Fork identity was not returned. Queued updates remain vendor data.')
            session.emit({'type': 'session_info', 'missing': ['unresolved_fork'], '_meta': {META: {'updates': [update for update, _ in updates]}}}, ts)
        for session in self.sessions.values():
            session.flush(None if session.sid in self.replaying else ts, interrupted=True)
            # An unfinished request has no invented result or permission answer.
            for cid, state in session.calls.items():
                if 'call:' + cid not in session.seen:
                    session.loss('incomplete_tool_requests', ts)
                    session.gap('not_recorded', ts, 'A tool request did not reach a complete input boundary.')
            session.writer.close()
