"""Reuse the native API, identity, privacy and accounting code from LiteLLM."""
from __future__ import annotations

from copy import deepcopy
import json

from agent_session_record import Writer
from asr_litellm.protocol import META
from asr_litellm.recorder import MISSING, Recorder, Session

GATEWAY_META = 'org.agentsessionrecord.gateways'


class Output:
    """Strip local playback times from offline native log conversions."""
    def __init__(self, path, header, historical):
        self.writer = Writer(path, header)
        self.historical = historical

    def append(self, record):
        value = deepcopy(record)
        if value.get('type') == 'inference' and value.get('_meta', {}).get(META, {}).get('upstreamStatus') == 0:
            value['_meta'][META].pop('upstreamStatus', None)
        if self.historical:
            value.pop('ts', None)
            value.pop('durationMs', None)
            value.get('_meta', {}).get(META, {}).pop('firstObservedAt', None)
        return self.writer.append(value)

    def close(self):
        self.writer.close()

    @property
    def _fd(self):
        return self.writer._fd

    @property
    def position(self):
        return self.writer.position


class GatewaySession(Session):
    """The core mapping with a gateway-specific storage header."""
    def __init__(self, directory, who, api, ts, gateway, historical):
        agent = {k: who[k] for k in ('name', 'version') if k in who}
        missing = MISSING.copy() + (['timestamps', 'model_call_duration'] if historical else [])
        header = {'id': 'header', 'agent': agent, 'sessionId': who['sessionId'], 'missing': missing,
                  'producer': {'name': 'asr-' + gateway, 'version': '0.1.0',
                               'method': 'converter' if historical else 'recorder',
                               'source': gateway + ':' + api},
                  '_meta': {GATEWAY_META: {'groupingKey': who['key'], 'groupingCandidates': who['candidates']}}}
        if 'parent' in who:
            header['parent'] = who['parent']
        super().__init__(directory, who, api, ts, header=header,
                         writer_factory=lambda path, value: Output(path, value, historical))


class GatewayCoreRecorder(Recorder):
    def __init__(self, directory, gateway, historical, **kwargs):
        super().__init__(directory, **kwargs)
        self.gateway, self.historical = gateway, historical

    def new_session(self, who, api):
        return GatewaySession(self.directory, who, api, self.clock(), self.gateway, self.historical)


class GatewayRecorder:
    def __init__(self, directory, *, gateway='envoy', historical=False, **kwargs):
        self.recorder = GatewayCoreRecorder(directory, gateway, historical, **kwargs)
        self.gateway, self.historical = gateway, historical
        self.accepted = self.skipped = 0

    def capture(self, api, headers, request, response, *, response_headers=None, status=None):
        if api not in ('anthropic-messages', 'openai-responses'):
            self.skipped += 1
            return False
        if not isinstance(request, dict):
            self.skipped += 1
            return False
        headers = {name.lower(): str(value) for name, value in headers.items()}
        response_headers = {name.lower(): str(value) for name, value in (response_headers or {}).items()}
        exchange = self.recorder.start(api, headers, request, response_headers=response_headers, status=status if status is not None else 0)
        if exchange is None:
            self.skipped += 1
            return False
        if isinstance(response, dict):
            exchange.json(response)
        elif isinstance(response, (str, bytes)):
            raw = response.encode() if isinstance(response, str) else response
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError):
                exchange.feed(raw)
                exchange.finish()
            else:
                if isinstance(value, dict):
                    exchange.json(value)
                else:
                    exchange.finish(stream=False, error=True)
        else:
            exchange.finish(stream=False, error=True)
        self.accepted += 1
        return True

    def close(self):
        self.recorder.close()
