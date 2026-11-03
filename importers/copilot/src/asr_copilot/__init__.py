"""Offline Copilot usage envelopes with a bounded Chat Completions body profile."""
from __future__ import annotations

from urllib.parse import urlsplit

from asr_importer_core import META, Stream, count, json_lines, loads, millis, text_parts


def convert(data: bytes, *, session_id: str, namespace=None) -> Stream:
    # GitHub does not document a session key in these usage records. The caller
    # must partition them using an independently recorded native session join.
    stream = Stream("org.agentsessionrecord.copilot-api", session_id, "github-copilot-usage", namespace=namespace)
    stream.header["_meta"] = {META: {"profile": "github-usage-docs-2026-11-01+chat-completions", "sessionJoin": "caller-supplied-native-id", "liveTested": False}}
    rows = list(json_lines(data))
    requests = {}
    seen = {}
    response_ids = {}
    for position, row in rows:
        if row is None:
            stream.gap(meta={"sourceLine": position + 1})
            continue
        eid = str(row["event_id"]) if row.get("event_id") is not None else None
        if eid is not None and eid in seen:
            if seen[eid] != row:
                stream.gap(detail="Conflicting usage records share an event ID.")
            continue
        if eid is not None:
            seen[eid] = row
        ts = millis(row.get("@timestamp"))
        meta = dict(row)
        endpoint = row.get("endpoint")
        try:
            supported_endpoint = isinstance(endpoint, str) and urlsplit(endpoint).path.rstrip("/") == "/chat/completions"
        except ValueError:
            supported_endpoint = False
        if not supported_endpoint:
            stream.gap(reason="unknown", detail="This endpoint is outside the supported Chat Completions body profile.", source_id=eid, ts=ts, meta=meta)
            continue
        if row.get("truncated") is True:
            # A truncated JSON string must never become partial calls or usage.
            stream.gap("not_retained", "GitHub truncated this request or response body.", source_id=eid, ts=ts, meta=meta, truncated=True)
            stream.missing("content")
            continue
        try:
            body = loads(row["body"])
            if not isinstance(body, dict):
                raise ValueError("object body required")
        except (KeyError, ValueError, TypeError):
            stream.gap(source_id=eid, ts=ts, meta=meta)
            continue
        request_id = row.get("github_request_id")
        if row.get("type") == "request":
            if isinstance(request_id, str) and request_id:
                if request_id in requests:
                    requests[request_id] = None
                    stream.missing("ambiguous_requests")
                else:
                    requests[request_id] = body
            messages = body.get("messages")
            if not isinstance(messages, list):
                stream.gap(reason="unknown", detail="The request body is outside the supported messages profile.", source_id=eid, ts=ts, meta=meta)
                continue
            for index, message in enumerate(messages):
                if not isinstance(message, dict) or message.get("role") not in ("user", "assistant", "system", "developer"):
                    # Historical tool results stay in metadata. They do not
                    # establish a new result in this session.
                    stream.add("session_info", ts=ts, missing=["request_context"], meta={"request": meta, "messageIndex": index})
                    continue
                content = text_parts(message.get("content"))
                fields = {"role": message["role"], "content": content}
                if isinstance(message.get("content"), list) and len(content) != len(message["content"]):
                    fields["truncated"] = True
                    stream.missing("content")
                if message["role"] in ("system", "developer"):
                    fields["origin"] = "instructions"
                stream.add("message", source_id=eid if index == 0 else None, ts=ts,
                           meta={"requestContext": True, "request": meta, "messageIndex": index}, **fields)
        elif row.get("type") == "response":
            provider_id = body.get("id")
            if provider_id is not None and str(provider_id) in response_ids:
                # Native response identity, rather than text equality, proves
                # this is another retained observation of the same inference.
                stream.missing("duplicate_response_observations")
                if response_ids[str(provider_id)] != body:
                    stream.gap(reason="unknown", ts=ts, detail="Conflicting observations share a provider response ID.", meta=meta)
                continue
            if provider_id is not None:
                response_ids[str(provider_id)] = body
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices:
                stream.gap(reason="unknown", detail="The response body is outside the supported completed choices profile.", source_id=eid, ts=ts, meta=meta)
                continue
            request = requests.get(request_id) if isinstance(request_id, str) else None
            fields = {}
            model = {}
            if isinstance(body.get("model"), str) and body["model"]:
                model["id"] = body["model"]
            if request and isinstance(request.get("model"), str) and request["model"]:
                model["requested"] = request["model"]
            if model:
                fields["model"] = model
            reported = body.get("usage")
            if isinstance(reported, dict):
                fields["usage"] = {target: reported[key] for key, target in (("prompt_tokens", "inputTokens"), ("completion_tokens", "outputTokens")) if count(reported.get(key))}
                for key, detail, target in (("prompt_tokens_details", "cached_tokens", "cacheReadTokens"), ("completion_tokens_details", "reasoning_tokens", "reasoningTokens")):
                    nested = reported.get(key)
                    if isinstance(nested, dict) and count(nested.get(detail)):
                        fields["usage"][target] = nested[detail]
            inference = stream.add("inference", source_id=provider_id or eid, ts=ts,
                                   meta={"response": meta, "request": request}, **fields)["id"]
            for choice in choices:
                if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                    stream.gap(ts=ts, meta={"choice": choice})
                    continue
                message = choice["message"]
                if message.get("role") != "assistant":
                    stream.gap(reason="unknown", ts=ts, meta={"choice": choice})
                    continue
                content = text_parts(message.get("content"))
                shortened = isinstance(message.get("content"), list) and len(content) != len(message["content"])
                if shortened:
                    stream.missing("content")
                stream.add("message", ts=ts, role="assistant", author="model", inferenceId=inference,
                           content=content, meta={"choice": choice}, **({"truncated": True} if shortened else {}))
                calls = message.get("tool_calls", [])
                if not isinstance(calls, list):
                    stream.gap(ts=ts, meta={"toolCalls": calls})
                    continue
                for call in calls:
                    if not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"] or not isinstance(call.get("function"), dict):
                        stream.gap(ts=ts, meta={"toolCall": call})
                        continue
                    function = call["function"]
                    arguments = function.get("arguments")
                    arguments_field = {"inputText": arguments} if isinstance(arguments, str) else {}
                    # The string was received verbatim. Do not guess an invalid
                    # argument string into structured JSON.
                    stream.add("tool_call", source_id=call["id"], ts=ts, callId=call["id"],
                               **({"name": function["name"]} if isinstance(function.get("name"), str) else {}),
                               requestedBy="model", inferenceId=inference, meta={"call": call}, **arguments_field)
        else:
            stream.gap(reason="unknown", source_id=eid, ts=ts, meta=meta)
    return stream
