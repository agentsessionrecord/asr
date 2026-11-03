"""Keep native blocks outside the namespace of core content part names."""
CORE_PARTS = {"text", "image", "audio", "resource_link", "resource", "reasoning"}
NATIVE_PART = "org.agentsessionrecord.native/content"


def content_part(part):
    kind = part.get("type")
    if kind in {"thinking", "redacted_thinking", "reasoning"}:
        if kind == "thinking":
            mapped = reasoning_part(text=part.get("thinking"), visibility="summary")
        elif kind == "redacted_thinking":
            mapped = reasoning_part(visibility="encrypted")
        else:
            mapped = reasoning_part(text=part.get("text"), summary=part.get("summary"), visibility=part.get("visibility"))
        return {**mapped, **{key: part[key] for key in ("author", "origin") if key in part}}
    if kind in CORE_PARTS:
        return part
    return {"type": NATIVE_PART, "_meta": {"org.agentsessionrecord.native": {"native": part}}}


def reasoning_part(*, text=None, summary=None, visibility=None):
    """Label the representation supplied by the source and discard opaque state."""
    if visibility in {"encrypted", "omitted"}:
        return {"type": "reasoning", "visibility": visibility}
    if isinstance(summary, list):
        if any(isinstance(item, str) and item != "" for item in summary):
            return {"type": "reasoning", "visibility": "summary", "summary": summary}
        return {"type": "reasoning", "visibility": "omitted"}
    if not isinstance(text, str) or text == "":
        return {"type": "reasoning", "visibility": "omitted"}
    if visibility == "summary":
        return {"type": "reasoning", "visibility": "summary", "summary": [text]}
    return {"type": "reasoning", "text": text, **({"visibility": visibility} if visibility else {})}
