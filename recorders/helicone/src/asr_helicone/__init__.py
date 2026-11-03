"""Local receiver for the Helicone SDK manual logger contract."""
from asr_gateways.cli import entry


def capture(recorder, payload, headers=None, path=None):
    # Provider URLs from a log are never fetched. The configured route selects the API.
    request, response = payload['providerRequest'], payload['providerResponse']
    api = 'anthropic-messages' if path == '/anthropic/v1/log' else 'openai-responses' if path == '/custom/v1/log' else None
    body = response.get('textBody')
    if body is None:
        body = {k: v for k, v in response.get('json', {}).items() if k not in ('_type', 'toolName')}
    return recorder.capture(api, headers or {}, request['json'], body,
                            response_headers=response.get('headers', {}), status=response['status'])


def main():
    entry('helicone', capture, paths=('/anthropic/v1/log', '/custom/v1/log'))
