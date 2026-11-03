#!/usr/bin/env python3
"""Select and check a bounded private history sample."""
import argparse
from pathlib import Path
from sample_corpus import run

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', required=True, type=Path)
parser.add_argument('--validator', required=True, type=Path)
parser.add_argument('--out', required=True, type=Path)
parser.add_argument('--root', required=True, action='append', help='agent=directory')
parser.add_argument('--limit', type=int, default=300, help='Maximum files per agent')
parser.add_argument('--jobs', type=int, default=1)
parser.add_argument('--timeout-seconds', type=float, default=300)
args = parser.parse_args()
if min(args.limit, args.jobs, args.timeout_seconds) <= 0:
    parser.error('limit, jobs and timeout must be positive')
raise SystemExit(run(args))
