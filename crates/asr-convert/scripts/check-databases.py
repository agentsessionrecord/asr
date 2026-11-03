#!/usr/bin/env python3
"""Check at most 100 native history files per database agent, privately."""
import argparse
from pathlib import Path
from database_corpus import run

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', required=True, type=Path)
parser.add_argument('--validator', required=True, type=Path)
parser.add_argument('--out', required=True, type=Path)
parser.add_argument('--root', required=True, action='append', help='agent=file-or-directory')
parser.add_argument('--namespace', action='append', default=[], help='agent=stable-profile-id')
parser.add_argument('--limit', type=int, default=100)
parser.add_argument('--timeout-seconds', type=float, default=300)
args = parser.parse_args()
if not 1 <= args.limit <= 100 or not 0 < args.timeout_seconds <= 300:
    parser.error('limit must be 1..100 and timeout must be greater than zero and at most 300')
raise SystemExit(run(args))
