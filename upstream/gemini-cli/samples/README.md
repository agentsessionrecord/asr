# Synthetic export sample

`native.jsonl` contains only invented session data. `session.jsonl` is produced
by the patched native exporter. The sample includes a read call, an intervening
notice and a completed model-facing result. It supplies no real account or
credential data. The CI test rebuilds the exporter from the patch and compares
its output byte for byte before validating it.
