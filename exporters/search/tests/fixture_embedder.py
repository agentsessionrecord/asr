"""Deterministic three-dimensional test vectors. These have no semantic quality."""

import json
import sys

request = json.load(sys.stdin)
vectors = [[float(text.count("quokka") + 1), float(text.count("parser") + 1), 1.0]
           for text in request["texts"]]
json.dump({"vectors": vectors}, sys.stdout)
