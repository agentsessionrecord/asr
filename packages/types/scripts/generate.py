#!/usr/bin/env python3
"""Generate language shapes and bundled Python schemas from the four v0 schemas."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import keyword
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SOURCES = sorted((ROOT / 'schema/v0').glob('*.schema.json'))
DOCS = {p.name: json.loads(p.read_text()) for p in SOURCES}
CORE = DOCS['agent-session.schema.json']
DIGEST = hashlib.sha256(b''.join(p.name.encode() + b'\0' + p.read_bytes() for p in SOURCES)).hexdigest()


def pascal(value):
    return ''.join(p[:1].upper() + p[1:] for p in re.split(r'[^a-zA-Z0-9]+', value))


def snake(value):
    name = re.sub(r'(?<!^)(?=[A-Z])', '_', value).lower().lstrip('$')
    name = name.lstrip('_')
    return name + '_' if keyword.iskeyword(name) or name == 'schema' else name


NAMES = {key: ('VcsRecord' if key == 'record.vcs' else pascal(key.removeprefix('record.'))) for key in CORE['$defs']}
NODES = {NAMES[key]: value for key, value in CORE['$defs'].items()}
ENVELOPE = CORE['$defs']['Envelope']
for key in CORE['$defs']:
    if key.startswith('record.'):
        NODES[NAMES[key]] = {'allOf': [ENVELOPE, CORE['$defs'][key], {
            'type': 'object', 'properties': {'type': {'const': key[7:]}}, 'required': ['type']} ]}
for filename, name in [('annotation.schema.json', 'Annotation'), ('discovery.schema.json', 'Discovery'), ('manifest.schema.json', 'Manifest')]:
    NODES[name] = DOCS[filename]


def refname(node):
    ref = node['$ref']
    base, fragment = ref.split('#', 1)
    if base and base != CORE['$id']:
        raise ValueError(f'Unsupported reference: {ref}')
    return NAMES[fragment.removeprefix('/$defs/')]


def shape(node):
    """Flatten positive object shapes. Runtime schemas retain all constraints."""
    if '$ref' in node:
        return shape(NODES[refname(node)])
    result = copy.deepcopy(node)
    props = dict(result.get('properties', {}))
    required = set(result.get('required', []))
    for child in node.get('allOf', []):
        if 'if' in child:
            for key, value in shape(child.get('then', {})).get('properties', {}).items():
                props.setdefault(key, value)
            continue
        flat = shape(child)
        props.update(flat.get('properties', {}))
        required.update(flat.get('required', []))
        if 'type' not in result and 'type' in flat:
            result['type'] = flat['type']
    if props or result.get('type') == 'object':
        result['properties'] = props
        result['required'] = sorted(required)
        result.setdefault('type', 'object')
    return result


# Concrete variants make conditional content and annotation payloads available.
for branch in CORE['$defs']['ContentPart']['allOf']:
    tag = branch['if']['properties']['type'].get('const')
    if tag is None:
        continue
    NODES[pascal(tag) + 'Part'] = {'allOf': [
        {k: v for k, v in CORE['$defs']['ContentPart'].items() if k != 'allOf'},
        branch['then'], {'type': 'object', 'properties': {'type': {'const': tag}}}]}
for branch in DOCS['annotation.schema.json']['allOf']:
    tag = branch['if']['properties']['kind']['const']
    NODES[pascal(tag) + 'Annotation'] = {'allOf': [
        {k: v for k, v in DOCS['annotation.schema.json'].items() if k != 'allOf'},
        branch['then'], {'type': 'object', 'properties': {'kind': {'const': tag}}}]}


def nullable(node):
    node = shape(node)
    return isinstance(node.get('type'), list) and 'null' in node['type']


def object_node(node):
    node = shape(node)
    types = node.get('type', [])
    return types == 'object' or isinstance(types, list) and 'object' in types


# Lift inline objects to named models for Python and Go.
def discover(node, name):
    if '$ref' in node:
        return
    flat = shape(node)
    if object_node(flat):
        for key, prop in flat.get('properties', {}).items():
            lift(prop, name + pascal(key))
    elif flat.get('type') == 'array':
        lift(flat['items'], name + 'Item')
    for index, option in enumerate(flat.get('anyOf', [])):
        if any(key in option for key in ('type', '$ref', 'properties', 'anyOf')):
            lift(option, name + 'Option' + str(index))


def lift(node, name):
    if '$ref' in node:
        return
    if object_node(node):
        NODES.setdefault(name, node)
    discover(node, name)


for name, node in list(NODES.items()):
    discover(node, name)


def type_expr(node, name, lang):
    if '$ref' in node:
        target = refname(node)
        if lang == 'py' and nullable(NODES[target]):
            return target + ' | None'
        return target
    if 'const' in node:
        value = node['const']
        if lang == 'go':
            return 'string'
        return json.dumps(value) if lang == 'ts' else f'Literal[{value!r}]'
    flat = shape(node)
    if 'anyOf' in flat and not object_node(flat):
        parts = [type_expr(v, name + 'Option' + str(i), lang) for i, v in enumerate(flat['anyOf'])]
        return ' | '.join(parts) if lang != 'go' else 'json.RawMessage'
    types = flat.get('type')
    if isinstance(types, list):
        if lang == 'go':
            nonnull = [v for v in types if v != 'null']
            return type_expr({**flat, 'type': nonnull[0]}, name, lang) if len(nonnull) == 1 else 'json.RawMessage'
        return ' | '.join(type_expr({**flat, 'type': t}, name, lang) for t in types)
    if types == 'object':
        if lang in ('py', 'go'):
            return name
        props = [f'  {json.dumps(k)}{"" if k in flat.get("required", []) else "?"}: {type_expr(v, name + pascal(k), lang)};' for k, v in flat.get('properties', {}).items()]
        return '{\n' + '\n'.join(props + ['  [key: string]: unknown;']) + '\n}'
    if types == 'array':
        item = type_expr(flat['items'], name + 'Item', lang)
        return {'ts': f'Array<{item}>', 'py': f'list[{item}]', 'go': f'[]{item}'}[lang]
    return {
        'ts': {'string': 'string', 'integer': 'number', 'number': 'number', 'boolean': 'boolean', 'null': 'null'},
        'py': {'string': 'str', 'integer': 'int', 'number': 'int | float', 'boolean': 'bool', 'null': 'None'},
        'go': {'string': 'string', 'integer': 'json.Number', 'number': 'json.Number', 'boolean': 'bool', 'null': 'json.RawMessage'},
    }[lang].get(types, {'ts': 'JsonValue', 'py': 'JsonValue', 'go': 'json.RawMessage'}[lang])


def typescript():
    out = [f'// Generated by packages/types/scripts/generate.py. Schema SHA-256: {DIGEST}',
           '// Structural types. Use the validator for schema and relationship constraints.',
           'export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };']
    for name, node in NODES.items():
        out.append(f'export type {name} = {type_expr(node, name, "ts")};')
    records = [NAMES[k] for k in CORE['$defs'] if k.startswith('record.')]
    out.extend(['export type KnownRecord = ' + ' | '.join(records) + ';',
                'export type ASRRecord = KnownRecord | Envelope;'])
    return '\n\n'.join(out) + '\n'


def python():
    out = [f'# Generated by packages/types/scripts/generate.py. Schema SHA-256: {DIGEST}',
           'from __future__ import annotations\n\nfrom typing import Literal\nfrom pydantic import BaseModel, ConfigDict, Field, JsonValue',
           'class ASRModel(BaseModel):\n    """Open, strict shapes. Omitted fields stay out of exclude_unset dumps."""\n\n    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)']
    aliases = []
    models = []
    for name, node in NODES.items():
        flat = shape(node)
        if not object_node(flat):
            aliases.append((name, type_expr(node, name, 'py')))
            continue
        models.append(name)
        lines = [f'class {name}(ASRModel):']
        for key, prop in flat.get('properties', {}).items():
            typ = type_expr(prop, name + pascal(key), 'py')
            args = [] if key in flat.get('required', []) else ['default=None']
            if snake(key) != key:
                args.append(f'alias={key!r}')
            field = f' = Field({", ".join(args)})' if args else ''
            lines.append(f'    {snake(key)}: {typ}{field}')
        if len(lines) == 1:
            lines.append('    pass')
        out.append('\n'.join(lines))
    # Forward references let aliases follow model declarations.
    out.extend(f'{name} = {expr}' for name, expr in aliases)
    out.append('ASRRecord = ' + ' | '.join(NAMES[k] for k in CORE['$defs'] if k.startswith('record.')) + ' | Envelope')
    out.append('for _model in (' + ', '.join(models) + ',):\n    _model.model_rebuild()')
    out.append('__all__ = ' + repr(['ASRModel', 'ASRRecord'] + list(NODES)))
    return '\n\n'.join(out) + '\n'


def go():
    out = [f'// Code generated by packages/types/scripts/generate.py. DO NOT EDIT.\n// Schema SHA-256: {DIGEST}',
           'package asr\n\nimport "encoding/json"']
    for name, node in NODES.items():
        flat = shape(node)
        if not object_node(flat):
            # Aliases keep JSON primitives and exact number storage interoperable.
            out.append(f'type {name} = {type_expr(node, name, "go")}')
            continue
        fields = []
        keys = []
        for key, prop in flat.get('properties', {}).items():
            typ = type_expr(prop, name + pascal(key), 'go')
            optional = key not in flat.get('required', [])
            if optional:
                typ = f'Optional[{typ}]'
            elif nullable(prop):
                typ = f'Optional[{typ}]'
            tag = key + (',omitzero' if optional else '')
            fields.append(f'\t{pascal(key)} {typ} `json:"{tag}"`')
            keys.append(json.dumps(key))
        fields.append('\tExtra map[string]json.RawMessage `json:"-"`')
        out.append(f'type {name} struct {{\n' + '\n'.join(fields) + '\n}')
        keyargs = ', ' + ', '.join(keys) if keys else ''
        out.append(f'func (v {name}) MarshalJSON() ([]byte, error) {{\n\ttype plain {name}\n\treturn marshalObject(plain(v), v.Extra{keyargs})\n}}')
        out.append(f'func (v *{name}) UnmarshalJSON(data []byte) error {{\n\ttype plain {name}\n\tvar decoded plain\n\textra, err := unmarshalObject(data, &decoded{keyargs})\n\tif err != nil {{ return err }}\n\t*v = {name}(decoded)\n\tv.Extra = extra\n\treturn nil\n}}')
    gofmt = shutil.which('gofmt') or str(Path.home() / '.local/go/bin/gofmt')
    return subprocess.run([gofmt], input='\n\n'.join(out) + '\n', text=True, check=True, capture_output=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    outputs = {
        'packages/types/src/index.ts': typescript(),
        'python/agent_session_record/src/agent_session_record/models.py': python(),
        'go/asr/types_generated.go': go(),
    }
    for p in SOURCES:
        outputs['python/agent_session_record/src/agent_session_record/_schemas/' + p.name] = p.read_text()
    stale = []
    for relative, content in outputs.items():
        path = ROOT / relative
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(relative)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if stale:
        parser.exit(1, 'Generated files are stale. Run python3 packages/types/scripts/generate.py\n' + '\n'.join(stale) + '\n')
    print(f'{"Checked" if args.check else "Generated"} {len(outputs)} files from {len(SOURCES)} schemas')


if __name__ == '__main__':
    main()
