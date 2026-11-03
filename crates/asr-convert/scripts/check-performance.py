#!/usr/bin/env python3
"""Measure a saved private sample serially and compare every exported byte."""
import argparse
from pathlib import Path

from performance_corpus import run

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--catalog', required=True, type=Path)
parser.add_argument('--binary', required=True, type=Path)
parser.add_argument('--validator', required=True, type=Path)
parser.add_argument('--out', required=True, type=Path)
parser.add_argument('--reference', required=True, action='append', type=Path)
parser.add_argument('--timeout-seconds', type=float, default=120)
parser.add_argument('--validation-timeout-seconds', type=float, default=300)
parser.add_argument('--recheck', action='store_true', help='Compare saved outputs without converting again')
args = parser.parse_args()
if min(args.timeout_seconds, args.validation_timeout_seconds) <= 0:
    parser.error('timeouts must be positive')
raise SystemExit(run(args))
