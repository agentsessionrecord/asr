"""Portkey afterRequestHook context from the native default.log plugin."""
from asr_gateways.cli import entry


def capture(recorder, payload, headers=None, path=None):
    if payload.get('requestType') != 'messages':
        recorder.skipped += 1
        return False
    request, response = payload['request'], payload['response']
    if request.get('isStreamingRequest') or request.get('isTransformed') or response.get('isTransformed'):
        recorder.skipped += 1
        return False
    return recorder.capture('anthropic-messages', request.get('headers', {}), request['json'], response['json'],
                            status=response['statusCode'])


def main():
    entry('portkey', capture, paths=('/portkey',))
