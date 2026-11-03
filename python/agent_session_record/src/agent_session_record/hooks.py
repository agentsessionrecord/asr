"""Names shared by Python and JavaScript hook recorders."""
import json
from pathlib import Path

CONVENTIONS = json.loads(Path(__file__).with_name("hook-conventions.json").read_text())
VENDOR = CONVENTIONS["metadata"]
EXTENSION = CONVENTIONS["extension"]
HOOK = CONVENTIONS["record"]
OUTPUT_ENV = CONVENTIONS["output"]
CONTENT_ENV = CONVENTIONS["content"]
