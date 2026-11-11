#!/usr/bin/env bash
set -uo pipefail

export PATH="$PATH:$HOME/.local/go/bin"

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$root" || exit 1

names=()
states=()
details=()
failures=0

run() {
  local name=$1 code
  shift
  printf '\n== %s ==\n' "$name"
  names+=("$name")
  if "$@"; then
    states+=(PASS)
    details+=('')
  else
    code=$?
    states+=(FAIL)
    details+=("exit $code")
    failures=$((failures + 1))
  fi
}

skip() {
  names+=("$1")
  states+=(SKIP)
  details+=("$2")
}

has_file() {
  [[ -d $1 ]] || return 1
  [[ -n $(find "$1" -type d \( -name node_modules -o -name target -o -name .venv -o -name vendor -o -name __pycache__ \) -prune -o -type f -name "$2" -print -quit) ]]
}

# Optional sections always leave a result row, even when their entry point moves.
run_file() {
  local name=$1 file=$2
  shift 2
  if [[ -f $file ]]; then run "$name" "$@"; else skip "$name" "missing $file"; fi
}

run_file 'Validator CI' tools/validator/package.json pnpm --dir tools/validator run ci
run_file 'White paper build' whitepaper/build.mjs node whitepaper/build.mjs
run_file 'Strict site build' site/build.mjs node site/build.mjs --strict
run_file 'Registry' registry.json node scripts/check-registry.mjs
run_file 'E2E harness checks' tests/e2e/test_harness.py python3 -m unittest discover -s tests/e2e -p 'test_*.py'
if [[ ${ASR_TEST_E2E:-0} == 1 ]]; then
  run_file 'Container end-to-end' tests/e2e/run.py python3 tests/e2e/run.py
else
  skip 'Container end-to-end' 'set ASR_TEST_E2E=1 and ASR_PROXY_KEY_FILE'
fi
run_file 'Live runner configuration' scripts/test_live_provider.py python3 -m unittest discover -s scripts -p 'test_*.py'
run_file 'Tool documentation' scripts/check-tool-docs.mjs node scripts/check-tool-docs.mjs
if has_file scripts/test '*.test.mjs'; then
  run 'CI script tests' node --test scripts/test/*.test.mjs
else
  skip 'CI script tests' 'no script tests'
fi
run_file 'Generated package files' pnpm-workspace.yaml pnpm --recursive --if-present run check:generated
run_file 'Go format' scripts/check-go-format.sh bash scripts/check-go-format.sh

if has_file crates Cargo.toml; then
  run 'Rust generated types' python3 crates/asr-core/generate.py --check
  run 'Rust format' cargo fmt --all --check
  run 'Rust clippy' cargo clippy --workspace --all-targets -- -D warnings
  # Includes blame timing, native hunk context, session undos, and scoped mask-copy regressions.
  run 'Rust tests' cargo test --workspace
  run 'Rust session tool fixtures' node tools/validator/bin/asr-validate.js --summary crates/asr-cli/tests/fixtures
  run 'Rust corpus and performance harness tests' python3 -m unittest discover -s crates/asr-convert/scripts -p 'test_*.py'
  run 'Native JSONL converter goldens' node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/jsonl-b/golden
  run 'Rust converter goldens' node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/golden
  run 'Cursor, Gemini, Vibe, Mux and fx goldens' node tools/validator/bin/asr-validate.js --summary crates/asr-convert/tests/golden-w1-conv-a
  run 'Collector CLI build' cargo build -p asr-cli --locked
  run 'Generated blame histories' timeout --kill-after=10s 930s python3 crates/asr-cli/scripts/check-generated-blame.py --binary target/debug/asr --histories 2000 --seed 600601 --seconds 900
  run 'Blame end-to-end' python3 crates/asr-cli/scripts/check-blame.py --binary target/debug/asr
  if [[ -n ${ASR_TEST_CLAUDE_HISTORY:-} ]]; then
    run 'Private Claude blame replay' python3 crates/asr-cli/scripts/check-private-claude.py --binary target/debug/asr --source "$ASR_TEST_CLAUDE_HISTORY"
  else
    skip 'Private Claude blame replay' 'set ASR_TEST_CLAUDE_HISTORY to opt into a bounded local sample'
  fi
  run 'Collector watch checks' python3 crates/asr-collect/scripts/check-local.py --binary target/debug/asr
  if [[ -n ${ASR_TEST_MINIO_IMAGE:-} ]]; then
    minio_args=(--binary target/debug/asr --image "$ASR_TEST_MINIO_IMAGE")
    if [[ ${ASR_TEST_DOCKER_SUDO:-0} == 1 ]]; then
      minio_args+=(--sudo)
    fi
    run 'Collector MinIO' python3 crates/asr-collect/scripts/check-minio.py "${minio_args[@]}"
  else
    skip 'Collector MinIO' 'set ASR_TEST_MINIO_IMAGE to a local image'
  fi
else
  skip 'Collector CLI build' 'no Rust crates'
  skip 'Generated blame histories' 'no Rust crates'
  skip 'Blame end-to-end' 'no Rust crates'
  skip 'Private Claude blame replay' 'no Rust crates'
  skip 'Collector watch checks' 'no Rust crates'
  skip 'Collector MinIO' 'no Rust crates'
  skip 'Rust generated types' 'no Rust crates'
  skip 'Rust format' 'no Rust crates'
  skip 'Rust clippy' 'no Rust crates'
  skip 'Rust tests' 'no Rust crates'
  skip 'Rust session tool fixtures' 'no Rust crates'
  skip 'Rust corpus and performance harness tests' 'no Rust crates'
  skip 'Native JSONL converter goldens' 'no Rust crates'
  skip 'Rust converter goldens' 'no Rust crates'
  skip 'Cursor, Gemini, Vibe, Mux and fx goldens' 'no Rust crates'
fi
if has_file packages package.json; then
  run 'pnpm package tests' pnpm --recursive --filter './packages/**' --if-present run test
else
  skip 'pnpm package tests' 'no JavaScript or TypeScript packages'
fi
run_file 'Gemini and Qwen hook tests' plugins/gemini-qwen-core/package.json pnpm --dir plugins/gemini-qwen-core test
run_file 'OpenCode family recorder' plugins/opencode/check.sh bash plugins/opencode/check.sh
run_file 'GitHub app checks' apps/github/package.json pnpm --dir apps/github run ci
run_file 'Viewer checks' apps/viewer/package.json pnpm --dir apps/viewer run ci
run_file 'VS Code editor checks' apps/vscode/check.sh bash apps/vscode/check.sh
run_file 'JetBrains editor checks' apps/jetbrains/check.sh bash apps/jetbrains/check.sh
run_file 'Git notes, Git AI and GitLab' exporters/git-notes/check.sh bash exporters/git-notes/check.sh
run_file 'Remaining agent plugins' plugins/remaining-core/check.sh bash plugins/remaining-core/check.sh
run_file 'Python tests' python/agent_session_record/pyproject.toml uv run --all-packages pytest python
run_file 'Security boundary checks' scripts/check-security.py uv run --all-packages python scripts/check-security.py
run_file 'LiteLLM recorder tests' recorders/litellm/pyproject.toml uv run --all-packages pytest recorders/litellm/tests
run_file 'OpenTelemetry exporter' exporters/otel/check.sh bash exporters/otel/check.sh
run_file 'Parquet table exporter' exporters/tables/pyproject.toml uv run --package asr-tables pytest exporters/tables/tests
run_file 'Search exporter tests' exporters/search/check.sh bash exporters/search/check.sh
# Keep Phoenix isolated from the older OpenTelemetry modules bundled by xds-protos.
run_file 'Observability exporters and evals' exporters/evals/pyproject.toml uv run --isolated --package asr-phoenix --with 'pytest>=8.3,<10' --with-editable exporters/langfuse --with-editable exporters/braintrust pytest exporters/evals/tests exporters/phoenix/tests
run_file 'ACP and gateway recorder tests' recorders/acp/pyproject.toml uv run --all-packages pytest recorders/acp/tests recorders/envoy/tests
run_file 'Vendor and Entire importers' importers/vendor-core/pyproject.toml uv run --all-packages pytest importers/vendor-core/tests importers/anthropic-compliance/tests importers/openai-codex-logs/tests importers/copilot/tests importers/entire/tests
run_file 'Entire external command' plugins/entire/pyproject.toml uv run --all-packages pytest plugins/entire/tests
run_file 'Codex hook recorder tests' plugins/codex/pyproject.toml uv run --all-packages pytest plugins/codex/tests
run_file 'Python hook recorders' plugins/python-core/pyproject.toml uv run --all-packages pytest plugins/python-core/tests
run_file 'SIEM exporter' exporters/siem/check.sh bash exporters/siem/check.sh
run_file 'Claude sample and hook blame' crates/asr-cli/scripts/check-hook-blame.py python3 -I -S crates/asr-cli/scripts/check-hook-blame.py --binary target/debug/asr
run_file 'JSON hook recorders' plugins/hooks-core/check.sh bash plugins/hooks-core/check.sh
run_file 'Telemetry approval tests' importers/telemetry-approvals/pyproject.toml uv run --all-packages pytest importers/telemetry-approvals/tests

go_tests() (cd go && go test ./...)
if has_file go '*.go'; then run 'Go tests' go_tests; else skip 'Go tests' 'no Go source'; fi


for agent in astrbot cline codex crush deepagents deepseek-harness forgecode fx gemini-cli goose grok-build hermes kilo kimi-code mistral-vibe xum nanoclaw openclaw opencode openhands pi qwen-code shelley warp zed; do
  run_file "$agent native export patch" "upstream/$agent/check.mjs" node "upstream/$agent/check.mjs"
done

run_file 'DeepSeek standalone plugin' upstream/deepseek-harness/check-plugin.sh bash upstream/deepseek-harness/check-plugin.sh

run 'Writing rules' node scripts/check-writing.mjs
run 'Fixture privacy' node scripts/check-privacy.mjs
# Check committed files as well as work in progress.
run 'Committed whitespace' git -c core.whitespace=blank-at-eol,blank-at-eof diff --check 4b825dc642cb6eb9a060e54bf8d69288fbee4904 HEAD
run 'Diff whitespace' git diff --check
run 'Staged whitespace' git diff --cached --check

printf '\n%-25s | %-6s | %s\n' 'Check' 'Result' 'Details'
printf '%-25s-+-%-6s-+-%s\n' '-------------------------' '------' '-------'
for index in "${!names[@]}"; do
  printf '%-25s | %-6s | %s\n' "${names[$index]}" "${states[$index]}" "${details[$index]}"
done
printf '\n%s failed check(s).\n' "$failures"
((failures == 0))
