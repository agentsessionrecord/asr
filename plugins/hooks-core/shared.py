"""Load the lightweight producer helpers in isolated command hooks."""
from pathlib import Path
import sys

root = Path(__file__).resolve()
for source in (root.parents[2] / "python/agent_session_record/src", root.parent / "_shared"):
    if (source / "agent_session_record").is_dir():
        sys.path.insert(0, str(source))
        break
from agent_session_record.hooks import VENDOR, EXTENSION, HOOK
from agent_session_record.privacy import credential_key, credential_values, environment_secrets, redact_text, OPAQUE
from agent_session_record.references import session_reference

from agent_session_record.content import content_part
from agent_session_record.repository import repository_snapshot
