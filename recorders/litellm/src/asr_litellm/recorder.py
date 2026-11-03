"""Append observations in receipt order, grouped by native agent session identity."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from collections import OrderedDict
from functools import wraps
import logging

from agent_session_record import session_reference

from agent_session_record import Writer
from agent_session_record.safety import private_directory

from .privacy import Scrubber
from .protocol import META, SSE, anthropic_atoms, parts, response_atoms, tool_definitions, usage_for

MISSING = ['approvals', 'agent_settings', 'file_changes', 'exit_codes', 'commits', 'subagents', 'copies', 'cost',
           'session_lifecycle', 'tool_execution_times', 'prompt_authorship', 'user_identity', 'hooks', 'cwd',
           'tool_status', 'exact_model_context', 'content_metadata', 'pre_response_failures']


LOG = logging.getLogger(__name__)
LOG.addHandler(logging.NullHandler())
MAX_SESSIONS = 128
MAX_RESPONSES = 1024
MAX_HISTORY = 512
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 2048
REQUEST_SETTINGS = {"max_tokens", "max_output_tokens", "reasoning", "output_config", "temperature",
                    "service_tier", "stream", "top_p", "parallel_tool_calls"}


def guarded(method):
    @wraps(method)
    def capture(self, *args, **kwargs):
        if self.disabled:
            return None
        try:
            return method(self, *args, **kwargs)
        except Exception:
            self.disable()
            return None
    return capture


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def parse_object(value):
    if isinstance(value, dict):
        return value
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def identity(headers, body):
    ua = headers.get('user-agent', '')
    if re.search(r'claude[-_ ]?(code|cli)', ua, re.I):
        name, version = 'claude-code', re.search(r'(?:claude-cli|claude-code)/([\d.]+)', ua, re.I)
    elif 'codex' in (ua + ' ' + headers.get('originator', '')).lower():
        name, version = 'codex', re.search(r'codex[^/ ]*/([\d.]+)', ua, re.I)
    else:
        return None
    metadata_value = body.get('metadata') if isinstance(body.get('metadata'), dict) else {}
    metadata = parse_object(metadata_value.get('user_id'))
    turn = parse_object(headers.get('x-codex-turn-metadata'))
    candidates = []

    def add(key, value):
        if isinstance(value, str) and 0 < len(value) <= 4096:
            candidates.append({'key': key, 'value': value})

    if name == 'claude-code':
        add('metadata.user_id.agent_id', metadata.get('agent_id'))
        add('x-claude-code-agent-id', headers.get('x-claude-code-agent-id'))
        add('metadata.user_id.session_id', metadata.get('session_id'))
        suffix = re.search(r'_session_([a-zA-Z0-9-]+)$', str(metadata_value.get('user_id', '')))
        add('metadata.user_id suffix', suffix[1] if suffix else None)
        add('x-claude-code-session-id', headers.get('x-claude-code-session-id'))
    for key in ('thread-id', 'thread_id'):
        add(key, headers.get(key))
    add('x-codex-turn-metadata.thread_id', turn.get('thread_id'))
    add('conversation_id', headers.get('conversation_id'))
    add('prompt_cache_key', body.get('prompt_cache_key'))
    for key in ('session-id', 'session_id'):
        add(key, headers.get(key))
    if not candidates:
        return None
    who = {'name': name, 'sessionId': candidates[0]['value'], 'key': candidates[0]['key'], 'candidates': candidates}
    if version:
        who['version'] = version[1]
    parent = metadata.get('parent_session_id') or turn.get('parent_thread_id')
    if not parent and headers.get('x-claude-code-agent-id'):
        parent = metadata.get('session_id') or headers.get('x-claude-code-session-id')
    if parent:
        who['parent'] = {'session': session_reference(name, parent), 'kind': 'subagent'}
    return who


def atom_key(atom):
    if atom['type'] in ('tool_call', 'tool_result') and atom.get('callId'):
        return atom['type'] + ':' + atom['callId']
    return digest({key: value for key, value in atom.items() if key not in ('phase', '_nativeId')})


class Session:
    def __init__(self, directory, who, api, ts, *, header=None, writer_factory=Writer):
        self.who = who
        self.path = directory / (who['name'] + '-' + digest([who['name'], who['sessionId']]) + '.jsonl')
        agent = {'name': who['name']}
        if 'version' in who:
            agent['version'] = who['version']
        header = header if header is not None else {'type': 'session', 'id': 'header', 'formatVersion': '0.1', 'agent': agent, 'sessionId': who['sessionId'],
                  'producer': {'name': 'asr-litellm', 'version': '0.1.0', 'method': 'recorder', 'source': api},
                  'missing': MISSING.copy(), '_meta': {META: {'groupingKey': who['key'], 'groupingCandidates': who['candidates']}}}
        if 'parent' in who:
            header['parent'] = who['parent']
        original = self.path
        restart = 0
        while True:
            try:
                self.writer = writer_factory(self.path, header)
                break
            except FileExistsError:
                restart += 1
                self.path = original.with_name(original.stem + f"-restart-{restart}.jsonl")
                if "capture_restart" not in header["missing"]:
                    header["missing"].append("capture_restart")
        self.restarted = restart > 0
        self.ids = {'header'}
        self.position = 0
        self.calls = 0
        self.expected = []
        self.seen = {}
        self.conflicts = set()
        self.effective_inputs = {}
        self.instructions = None
        self.tools = None
        self.missing = set(header["missing"])
        if self.restarted:
            self.gap("Capture restarted. Earlier observations are in a previous capture file.", ts, "not_recorded")

    def unique(self, native=None):
        self.position += 1
        value = native or f'observation:{self.position}'
        if len(value) > 256 or re.search(r'[\x00-\x1f\x7f]', value):
            value = 'derived:' + digest(value)
        if value in self.ids:
            value = value[:180] + f':observation:{self.position}'
        self.ids.add(value)
        return value

    def emit(self, record, ts):
        value = deepcopy(record)
        native_id = value.pop('_nativeId', None)
        if 'id' not in value:
            value['id'] = self.unique(native_id)
        value['ts'] = ts
        self.writer.append(value)
        return value

    def loss(self, value, ts):
        if value not in self.missing:
            self.emit({'type': 'session_info', 'missing': [value]}, ts)
            self.missing.add(value)

    def gap(self, detail, ts, reason='unknown', **metadata):
        self.loss('context_history', ts)
        record = {'type': 'gap', 'reason': reason, 'detail': detail}
        if metadata:
            record['_meta'] = {META: metadata}
        self.emit(record, ts)

    def conflict(self, atom, ts):
        key = atom_key(atom)
        old = self.seen.get(key)
        semantic = lambda value: {k: v for k, v in value.items() if k != '_nativeId'}
        if old and semantic(old) != semantic(atom) and atom['type'] == 'tool_call':
            self.effective_inputs[atom['callId']] = {k: deepcopy(atom[k]) for k in ('input', 'inputText') if k in atom}
        if old and semantic(old) != semantic(atom) and key not in self.conflicts:
            self.gap('Rewritten tool item. The first observation is retained.', ts,
                     rewrittenCallId=atom.get('callId'), rewrittenType=atom['type'], rewrittenSha256=digest(semantic(atom)))
            self.conflicts.add(key)

    def atom(self, atom, exchange, ts, output=False):
        if atom['type'] in ('tool_call', 'tool_result') and atom.get('callId'):
            key = atom_key(atom)
            if key in self.seen:
                if not (output and atom['type'] == 'tool_call'):
                    self.conflict(atom, ts)
                    return
                self.loss('ambiguous_call_ids', ts)
            else:
                self.seen[key] = deepcopy(atom)
        value = deepcopy(atom)
        if value['type'] == 'tool_result':
            value.update(self.effective_inputs.get(value.get('callId'), {}))
        if output:
            value['inferenceId'] = exchange.inference_id
            if value['type'] == 'tool_call':
                value['requestedBy'] = 'model'
            if value['type'] == 'message':
                value['author'] = 'model'
        if exchange.scrubber.redacted:
            self.loss('redacted_content', ts)
            value['truncated'] = True
        self.emit(value, ts)
        if value['type'] == 'gap':
            self.loss('unsupported_items', ts)
        if value['type'] == 'tool_result' and 'content' not in value:
            self.loss('tool_output', ts)
        if value.get('origin') == 'compaction':
            self.gap('Compacted context observed. Original history may be unavailable.', ts, 'not_retained')
        if any(p['type'] == 'reasoning' and p.get('visibility') != 'full' for p in value.get('content', [])):
            self.loss('reasoning', ts)


class Recorder:
    """Single-process recorder. Use one proxy worker and a new private output directory."""
    def __init__(self, directory, *, clock=now):
        self.directory = private_directory(directory)
        self.clock = clock
        self.lock = RLock()
        self.sessions = OrderedDict()
        self.response_sessions = OrderedDict()
        self.failures = 0
        self.ungrouped = 0

    def failure(self):
        self.failures += 1
        LOG.warning("ASR observation failed")

    def new_session(self, who, api):
        return Session(self.directory, who, api, self.clock())

    def retire(self, key):
        session = self.sessions.pop(key)
        try:
            session.loss("capture_restart", self.clock())
            session.gap("Recorder state limit reached. This capture stopped.", self.clock(), "not_recorded")
        except Exception:
            self.failure()
        finally:
            session.writer.close()

    def start(self, *args, **kwargs):
        try:
            return self._start(*args, **kwargs)
        except Exception:
            self.failure()
            self.note_loss(args[0] if args else kwargs.get('api', 'unknown'),
                           args[1] if len(args) > 1 else kwargs.get('headers', {}),
                           args[2] if len(args) > 2 else kwargs.get('body', {}))
            return None

    def note_loss(self, api, headers, body=None):
        """Declare a rejected observation when native grouping is still known."""
        try:
            headers = {key.lower(): str(value) for key, value in headers.items()}
            scrubber = Scrubber(headers)
            grouping = {key: body[key] for key in ('metadata', 'prompt_cache_key', 'previous_response_id')
                        if isinstance(body, dict) and key in body}
            if len(canonical(grouping).encode()) > 16384:
                grouping = {}
            clean = scrubber.clean(grouping)
            who = identity(scrubber.headers(headers), clean)
            if who is None:
                who = self.response_sessions.get(clean.get('previous_response_id'))
            if who is None or '[REDACTED]' in who['sessionId']:
                return
            key = (who['name'], who['sessionId'])
            with self.lock:
                if key not in self.sessions:
                    while len(self.sessions) >= MAX_SESSIONS:
                        self.retire(next(iter(self.sessions)))
                    self.sessions[key] = self.new_session(who, api)
                self.sessions[key].gap("A request observation could not be recorded.", self.clock(), 'not_recorded')
        except Exception:
            self.failure()

    def _start(self, api, headers, body, *, response_headers=None, status=200, secrets=(), started_at=None):
        if not isinstance(body, dict) or len(canonical(body).encode()) > MAX_BYTES:
            raise ValueError("Request observation exceeds recorder bounds")
        with self.lock:
            headers = {key.lower(): str(value) for key, value in headers.items()}
            response_headers = {key.lower(): str(value) for key, value in (response_headers or {}).items()}
            scrubber = Scrubber(headers, response_headers, secrets=secrets)
            # Group using the scrubbed representation. Credentials never become an identity or filename.
            clean_body = scrubber.clean(deepcopy(body))
            who = identity(scrubber.headers(headers), clean_body)
            if who is None:
                who = self.response_sessions.get(clean_body.get('previous_response_id'))
            if who is not None and '[REDACTED]' in who['sessionId']:
                who = None
            if who is None:
                self.ungrouped += 1
                return None
            key = (who['name'], who['sessionId'])
            if key in self.sessions:
                current = self.sessions[key]
                if current.writer._fd is None or current.writer.position > MAX_RECORDS or current.path.stat().st_size > 16 * 1024 * 1024:
                    self.retire(key)
            if key not in self.sessions:
                while len(self.sessions) >= MAX_SESSIONS:
                    self.retire(next(iter(self.sessions)))
                self.sessions[key] = self.new_session(who, api)
            session = self.sessions[key]
            self.sessions.move_to_end(key)
            session.calls += 1
            return Exchange(self, session, api, clean_body, scrubber, scrubber.headers(headers),
                            scrubber.headers(response_headers), status, started_at)

    def close(self):
        with self.lock:
            for session in self.sessions.values():
                try:
                    session.writer.close()
                except Exception:
                    self.failure()


class Exchange:
    def __init__(self, recorder, session, api, body, scrubber, headers, response_headers, status, started_at):
        self.recorder, self.session, self.api = recorder, session, api
        self.disabled = False
        self.body, self.scrubber = body, scrubber
        self.headers, self.response_headers, self.http_status = headers, response_headers, status
        self.started = recorder.clock()
        self.call_started = started_at or self.started
        self.response = {}
        self.inference_id = None
        self.output = []
        self.blocks = {}
        self.done_items = set()
        self.events = 0
        self.terminal = False
        self.finished = False
        self.sse = SSE(self.event)
        self.incremental = bool(body.get('previous_response_id'))
        instructions = body.get('system' if api == 'anthropic-messages' else 'instructions')
        if instructions is not None and canonical(instructions) != session.instructions:
            session.atom({'type': 'message', 'role': 'system', 'origin': 'instructions', 'content': parts(instructions)}, self, self.started)
            session.instructions = canonical(instructions)
        tools, partial = tool_definitions(body)
        if tools is None or partial:
            session.loss('tools', self.started)
        if tools is not None and canonical(tools) != session.tools:
            value = {'type': 'session_info', 'tools': tools}
            if scrubber.redacted:
                value['truncated'] = True
                session.loss('redacted_content', self.started)
            session.emit(value, self.started)
            session.tools = canonical(tools)
        self.input = anthropic_atoms(body.get('messages', [])) if api == 'anthropic-messages' else response_atoms(body.get('input'))
        if len(self.input) > MAX_HISTORY:
            raise ValueError('Request history exceeds recorder bounds')
        for atom in self.input:
            if atom['type'] in ('tool_call', 'tool_result'):
                session.conflict(atom, self.started)
        keys, expected = [atom_key(a) for a in self.input], [atom_key(a) for a in session.expected]
        prefix = 0
        while prefix < min(len(keys), len(expected)) and keys[prefix] == expected[prefix]:
            prefix += 1
        if self.incremental:
            new_atoms = self.input
        elif prefix == len(expected):
            new_atoms = self.input[prefix:]
        else:
            session.gap('Request history was rewritten, shortened, retried, or branched. Earlier observations are retained.', self.started)
            new_atoms, cursor = [], 0
            for atom, key in zip(self.input, keys):
                try:
                    cursor = expected.index(key, cursor) + 1
                except ValueError:
                    new_atoms.append(atom)
        for atom in new_atoms:
            session.atom(atom, self, self.started)
        if scrubber.redacted:
            session.loss('redacted_content', self.started)
            session.gap('Credentials excluded from the observed request.', self.started, 'redacted')

    def disable(self):
        self.disabled = True
        self.recorder.failure()
        try:
            self.session.gap("A response observation could not be recorded.", self.recorder.clock(), "not_recorded")
        except Exception:
            pass
        self.blocks.clear()
        self.output.clear()
        self.input = []
        self.done_items.clear()
        self.body = {}
        self.response = {}
        self.sse.buffer = ""

    def identify(self, response):
        if response.get('id'):
            self.recorder.response_sessions[response['id']] = self.session.who
            self.recorder.response_sessions.move_to_end(response['id'])
            while len(self.recorder.response_sessions) > MAX_RESPONSES:
                self.recorder.response_sessions.popitem(last=False)
        if self.inference_id is None:
            native = self.response_headers.get('request-id') or self.response_headers.get('x-request-id') or response.get('id')
            self.inference_id = self.session.unique(native or f'call:{self.session.calls}:inference')

    def emit_output(self, items):
        self.identify(self.response)
        ts = self.recorder.clock()
        atoms = anthropic_atoms([{'role': 'assistant', 'content': items}]) if self.api == 'anthropic-messages' else response_atoms(items)
        for atom in atoms:
            # Normalize reasoning before scrubbing drops opaque state.
            atom = self.scrubber.clean(atom)
            self.session.atom(atom, self, ts, True)
            self.output.append(atom)
            if len(self.output) > MAX_HISTORY or len(canonical(self.output).encode()) > MAX_BYTES:
                raise ValueError("Response history exceeds recorder bounds")

    @guarded
    def event(self, event):
        with self.recorder.lock:
            self.events += 1
            if self.events > MAX_RECORDS * 16:
                raise ValueError("Too many response events")
            ts = self.recorder.clock()
            if event is None:
                self.session.gap('Unparseable SSE event.', ts, 'unparseable')
                return
            kind = event.get('type')
            if self.api == 'anthropic-messages':
                if kind == 'message_start':
                    self.response = self.scrubber.clean(event['message'])
                    self.identify(self.response)
                elif kind == 'content_block_start':
                    if len(self.blocks) >= MAX_HISTORY:
                        raise ValueError('Too many response blocks')
                    self.blocks[event['index']] = deepcopy(event['content_block'])
                    if len(canonical(self.blocks).encode()) > MAX_BYTES:
                        raise ValueError('Response blocks exceed recorder bounds')
                elif kind == 'content_block_delta':
                    block = self.blocks.get(event['index'])
                    if block is None:
                        self.session.gap('Content delta without its start.', ts, 'unparseable')
                        return
                    delta = event['delta']
                    field = {'text_delta': 'text', 'thinking_delta': 'thinking', 'input_json_delta': 'partial_json'}.get(delta['type'])
                    if field:
                        block[field] = block.get(field, '') + delta[field]
                        if len(canonical(self.blocks).encode()) > MAX_BYTES:
                            raise ValueError('Response blocks exceed recorder bounds')
                elif kind == 'content_block_stop':
                    block = self.blocks.pop(event['index'], None)
                    if block is None:
                        self.session.gap('Content stop without its start.', ts, 'unparseable')
                        return
                    if 'partial_json' in block:
                        try:
                            block['input'] = json.loads(block.pop('partial_json'))
                        except ValueError:
                            self.session.gap('Incomplete tool arguments.', ts, 'unparseable')
                            return
                    self.emit_output([block])
                elif kind == 'message_delta':
                    self.response.update(self.scrubber.clean(event.get('delta', {})))
                    self.response.setdefault('usage', {}).update(event.get('usage', {}))
                elif kind == 'message_stop':
                    self.terminal = True
            else:
                if kind == 'response.created':
                    self.response = self.scrubber.clean(event['response'])
                    self.identify(self.response)
                elif kind == 'response.output_item.done':
                    item = event['item']
                    self.done_items.add(item.get('id') or digest(item))
                    self.emit_output([item])
                elif kind in ('response.completed', 'response.incomplete', 'response.failed'):
                    response = event['response']
                    self.response = self.scrubber.clean({k: v for k, v in response.items() if k != 'output'})
                    self.identify(self.response)
                    for item in response.get('output', []):
                        key = item.get('id') or digest(item)
                        if key not in self.done_items:
                            self.done_items.add(key)
                            self.emit_output([item])
                    self.terminal = True
            if kind == 'error':
                self.response['error'] = self.scrubber.clean(event.get('error', ({'message': event['message']} if isinstance(event.get('message'), str) else {})))
                self.session.gap('Provider SSE error.', ts, 'unparseable')

    @guarded
    def feed(self, chunk):
        with self.recorder.lock:
            try:
                self.sse.feed(chunk)
            except (UnicodeError, KeyError, TypeError, ValueError):
                if len(self.sse.buffer) > MAX_BYTES:
                    self.disable()
                    return
                self.session.gap('Invalid API stream item.', self.recorder.clock(), 'unparseable')
                self.session.loss('content_metadata', self.recorder.clock())

    @guarded
    def json(self, response):
        with self.recorder.lock:
            self.scrubber.learn(response)
            self.response = self.scrubber.clean({k: v for k, v in response.items() if k not in ('content', 'output')})
            self.identify(self.response)
            self.emit_output(response.get('content' if self.api == 'anthropic-messages' else 'output', []))
            self.terminal = True
            self.finish(stream=False)

    @guarded
    def finish(self, *, stream=True, error=False):
        with self.recorder.lock:
            if self.finished:
                return
            self.finished = True
            ts, session = self.recorder.clock(), self.session
            if stream:
                try:
                    tail = self.sse.finish()
                except UnicodeError:
                    tail = True
                if tail:
                    session.gap('Incomplete SSE frame.', ts, 'unparseable')
                for block in self.blocks.values():
                    if block.get('type') != 'tool_use':
                        self.emit_output([{**block, 'interrupted': True}])
                self.blocks.clear()
            if not self.terminal:
                session.gap('Response stream ended without complete terminal evidence.', ts, 'not_recorded')
                session.loss('tool_output', ts)
            self.identify(self.response)
            model = {}
            if self.body.get('model'):
                model['requested'] = self.body['model']
            if self.response.get('model'):
                model['id'] = self.response['model']
            if not model.get('id'):
                session.loss('model', ts)
            usage = usage_for(self.api, self.response.get('usage'))
            if usage is None:
                session.loss('usage', ts)
            settings = {key: value for key, value in {
                'reasoningEffort': (self.body.get('reasoning') or {}).get('effort', (self.body.get('output_config') or {}).get('effort')),
                'maxOutputTokens': self.body.get('max_output_tokens', self.body.get('max_tokens')),
                'temperature': self.body.get('temperature'), 'serviceTier': self.body.get('service_tier')}.items() if value is not None}
            if any(type(v) in (int, float) and abs(v) > 2**53 - 1 for v in settings.values()):
                session.loss('model_settings', ts)
                settings = {k: v for k, v in settings.items() if not (type(v) in (int, float) and abs(v) > 2**53 - 1)}
            metadata = {'api': self.api, 'requestHeaders': self.headers, 'responseHeaders': self.response_headers, 'upstreamStatus': self.http_status,
                        'settingsSource': 'request_body', 'responseId': self.response.get('id'), 'firstObservedAt': self.call_started,
                        'requestSettings': {k: v for k, v in self.body.items() if k in REQUEST_SETTINGS},
                        'providerUsage': self.response.get('usage'), 'responseStatus': self.response.get('status')}
            inference = {'type': 'inference', 'id': self.inference_id, 'settings': settings, '_meta': {META: metadata},
                         'durationMs': max(0, (datetime.fromisoformat(ts.replace('Z', '+00:00')) - datetime.fromisoformat(self.call_started.replace('Z', '+00:00'))).total_seconds() * 1000)}
            if model:
                inference['model'] = model
            if usage is not None:
                # Core counts cannot be stringified. Preserve oversized counts only as metadata.
                safe = {k: v for k, v in usage.items() if type(v) is int and 0 <= v <= 2**53 - 1}
                if safe != usage:
                    session.loss('usage', ts)
                inference['usage'] = safe
            if 'stop_reason' in self.response and self.response['stop_reason'] is not None:
                inference['stopReason'] = self.response['stop_reason']
            if self.response.get('error') or (error and not self.terminal) or self.http_status >= 400:
                native_error = self.response.get('error') or {}
                inference['error'] = {k: v for k, v in native_error.items() if k in ('message', 'code')}
                if not inference['error']:
                    inference['error'] = {'code': self.http_status} if self.http_status >= 400 else {}
            if self.scrubber.redacted:
                session.loss('redacted_content', ts)
                inference['truncated'] = True
            session.emit(self.scrubber.clean(inference), ts)
            if len(session.seen) > MAX_RECORDS or len(canonical(session.seen).encode()) > MAX_BYTES:
                session.gap("Recorder tool history limit reached. This capture stopped.", ts, "not_recorded")
                session.seen.clear()
                session.effective_inputs.clear()
                session.conflicts.clear()
                session.writer.close()
            history_output = []
            for atom in self.output:
                if self.api == 'anthropic-messages' and history_output and atom['type'] == 'message' and history_output[-1]['type'] == 'message':
                    history_output[-1]['content'].extend(deepcopy(atom['content']))
                else:
                    history_output.append(deepcopy(atom))
            session.expected = session.expected + self.input + history_output if self.incremental else self.input + history_output
            trimmed = False
            while len(session.expected) > MAX_HISTORY or len(canonical(session.expected).encode()) > MAX_BYTES:
                session.expected.pop(0)
                trimmed = True
            if trimmed:
                session.gap("Recorder history window was trimmed.", ts, "not_recorded")
                session.loss("history_window", ts)
