"""Map native API objects without deriving execution facts from their text."""
from __future__ import annotations

import codecs
import json
from agent_session_record.content import content_part, reasoning_part

META = 'org.agentsessionrecord.litellm'


def parts(content):
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}]
    if content is None:
        return []
    if not isinstance(content, list):
        return [{'type': 'text', 'text': json.dumps(content, ensure_ascii=False, separators=(',', ':'))}]
    result = []
    for part in content:
        kind = part.get('type')
        if kind in ('text', 'input_text', 'output_text'):
            result.append({'type': 'text', 'text': part['text']})
        elif kind == 'thinking':
            result.append(reasoning_part(text=part.get('thinking'), visibility='summary'))
        elif kind == 'redacted_thinking':
            result.append({'type': 'reasoning', 'visibility': 'encrypted'})
        elif kind == 'refusal':
            result.append({'type': 'text', 'text': part['refusal']})
        elif kind == 'image' and part.get('source', {}).get('type') == 'base64':
            result.append({'type': 'image', 'mimeType': part['source']['media_type'], 'data': part['source']['data']})
        else:
            result.append(content_part({key: value for key, value in part.items() if key not in ('signature', 'encrypted_content')}))
    return result


def status(item):
    if item.get('is_error') is True:
        return 'failed'
    value = item.get('status')
    return value if value in ('completed', 'failed', 'denied', 'cancelled', 'interrupted') else 'unknown'


def call(item, anthropic=False):
    record = {'type': 'tool_call', 'callId': item.get('call_id', item.get('id'))}
    if item.get('id'):
        record['_nativeId'] = item['id']
    if 'name' in item:
        record['name'] = item['name']
    if anthropic and 'input' in item:
        record['input'] = item['input']
    elif item['type'] == 'custom_tool_call':
        if 'input' in item:
            record['inputText'] = item['input']
    elif 'arguments' in item:
        try:
            record['input'] = json.loads(item['arguments'])
        except ValueError:
            record['inputText'] = item['arguments']
    return record


def anthropic_atoms(messages):
    atoms = []
    for message in messages:
        content = message.get('content', [])
        if isinstance(content, str):
            content = [{'type': 'text', 'text': content}]
        pending = []

        def flush():
            if pending:
                atom = {'type': 'message', 'role': message['role'], 'content': parts(pending)}
                if message['role'] in ('system', 'developer'):
                    atom['origin'] = 'instructions'
                if any(part.get('interrupted') for part in pending):
                    atom.update(status='interrupted', truncated=True)
                atoms.append(atom)
                pending.clear()

        for item in content:
            if item['type'] == 'tool_use':
                flush()
                atoms.append(call(item, True))
            elif item['type'] == 'tool_result':
                flush()
                atom = {'type': 'tool_result', 'status': status(item)}
                if item.get('tool_use_id'):
                    atom['callId'] = item['tool_use_id']
                if 'content' in item:
                    atom['content'] = parts(item['content'])
                atoms.append(atom)
            elif item['type'] == 'compaction':
                flush()
                atoms.append({'type': 'message', 'role': message['role'], 'origin': 'compaction', 'content': parts(item.get('content'))})
            else:
                pending.append(item)
        flush()
    return atoms


def response_atoms(items):
    if isinstance(items, str):
        return [{'type': 'message', 'role': 'user', 'content': parts(items)}]
    atoms = []
    for item in items or []:
        kind = item.get('type')
        if kind == 'additional_tools':
            continue
        if kind in ('function_call', 'custom_tool_call'):
            atom = call(item)
        elif kind in ('function_call_output', 'custom_tool_call_output'):
            atom = {'type': 'tool_result', 'status': status(item)}
            if item.get('call_id'):
                atom['callId'] = item['call_id']
            if 'output' in item:
                atom['content'] = parts(item['output'])
        elif kind == 'reasoning':
            summaries = [part['text'] for part in item.get('summary', []) if isinstance(part.get('text'), str)]
            reasoning = reasoning_part(summary=summaries) if summaries else reasoning_part(
                visibility='encrypted' if item.get('encrypted_content') else 'omitted')
            atom = {'type': 'message', 'role': 'assistant', 'content': [reasoning]}
        elif kind == 'agent_message':
            atom = {'type': 'message', 'role': 'user', 'author': 'agent', 'content': parts(item.get('content')),
                    '_meta': {META: {'itemType': kind, 'agentAuthor': item.get('author'), 'agentRecipient': item.get('recipient')}}}
        elif kind == 'compaction':
            atom = {'type': 'message', 'role': 'system', 'origin': 'compaction', 'content': [{'type': 'reasoning', 'visibility': 'encrypted'}]}
        elif 'role' in item:
            atom = {'type': 'message', 'role': item['role'], 'content': parts(item.get('content'))}
            if item['role'] in ('system', 'developer'):
                atom['origin'] = 'instructions'
            if item.get('phase') in ('commentary', 'final_answer'):
                atom['phase'] = 'final' if item['phase'] == 'final_answer' else item['phase']
        else:
            atom = {'type': 'gap', 'reason': 'not_recorded', 'detail': 'Unsupported Responses item: ' + str(kind)}
        if item.get('id'):
            atom['_nativeId'] = item['id']
        atoms.append(atom)
    return atoms


def usage_for(api, usage):
    if not isinstance(usage, dict):
        return None
    result = {}
    if api == 'anthropic-messages':
        if 'input_tokens' in usage:
            result['inputTokens'] = usage['input_tokens'] + usage.get('cache_read_input_tokens', 0) + usage.get('cache_creation_input_tokens', 0)
        mapping = {'cacheReadTokens': usage.get('cache_read_input_tokens'), 'cacheWriteTokens': usage.get('cache_creation_input_tokens')}
    else:
        mapping = {'inputTokens': usage.get('input_tokens'), 'cacheReadTokens': usage.get('input_tokens_details', {}).get('cached_tokens'),
                   'reasoningTokens': usage.get('output_tokens_details', {}).get('reasoning_tokens')}
    mapping['outputTokens'] = usage.get('output_tokens')
    result.update({key: value for key, value in mapping.items() if value is not None})
    return result


def tool_definitions(body):
    supplied = 'tools' in body
    definitions = list(body.get('tools') or [])
    for item in body.get('input', []) if isinstance(body.get('input'), list) else []:
        if item.get('type') == 'additional_tools':
            supplied = True
            definitions.extend(item.get('tools', []))
    tools, partial = [], False

    def visit(definition, namespace=''):
        nonlocal partial
        kind = definition.get('type')
        if kind == 'namespace':
            for child in definition.get('tools', []):
                visit(child, namespace + definition.get('name', '') + '.')
            return
        value = definition.get('function', definition)
        name = value.get('name')
        if not name:
            partial = True
            return
        tool = {'name': namespace + name}
        if 'description' in value:
            tool['description'] = value['description']
        for key in ('input_schema', 'parameters', 'inputSchema'):
            if key in value:
                tool['inputSchema'] = value[key]
                break
        # Provider tools with implicit schemas do not establish a complete definition.
        if kind not in (None, 'function', 'custom'):
            partial = True
        tools.append(tool)

    for definition in definitions:
        visit(definition)
    return tools if supplied else None, partial


class SSE:
    """Incremental UTF-8 and SSE framing, independent of transport chunk boundaries."""
    def __init__(self, event):
        self.decoder = codecs.getincrementaldecoder('utf-8')()
        self.buffer = ''
        self.event = event

    def feed(self, chunk):
        self.buffer += self.decoder.decode(chunk)
        if len(self.buffer) > 2 * 1024 * 1024:
            raise ValueError('SSE frame exceeds recorder bounds')
        # Keep a trailing CR until its possible LF arrives.
        normalized = self.buffer.replace('\r\n', '\n')
        while '\n\n' in normalized:
            frame, normalized = normalized.split('\n\n', 1)
            data = '\n'.join(line[5:].removeprefix(' ') for line in frame.split('\n') if line.startswith('data:'))
            if data and data != '[DONE]':
                try:
                    value = json.loads(data)
                except ValueError:
                    self.event(None)
                else:
                    self.event(value)
        self.buffer = normalized

    def finish(self):
        self.buffer += self.decoder.decode(b'', final=True)
        return bool(self.buffer.strip())
