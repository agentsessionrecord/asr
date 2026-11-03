FROM node:22.22.2-bookworm-slim AS node
FROM rust:1.97.1-bookworm
COPY --from=node /usr/local/ /usr/local/
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv chromium ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN npm install --global pnpm@12.11.2 \
    @anthropic-ai/claude-code@2.1.305 @openai/codex@0.163.0 \
    @earendil-works/pi-coding-agent@1.3.0
WORKDIR /opt/asr
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml Cargo.toml Cargo.lock ./
COPY crates ./crates
COPY schema ./schema
COPY agents ./agents
COPY tools ./tools
COPY packages ./packages
COPY apps ./apps
COPY plugins ./plugins
COPY exporters ./exporters
COPY python ./python
COPY site ./site
COPY whitepaper ./whitepaper
RUN pnpm install --frozen-lockfile \
    && pnpm --filter @agent-session/types build \
    && pnpm --filter @agent-session/writer build \
    && pnpm --dir apps/viewer build \
    && node plugins/remaining-core/build.mjs pi /opt/asr-pi
RUN cargo install --locked --path crates/asr-cli --root /opt/asr-cli
RUN python3 -m venv /opt/asr-python \
    && /opt/asr-python/bin/pip install --no-cache-dir \
    ./python/agent_session_record ./plugins/python-core ./plugins/codex \
    ./exporters/otel ./exporters/tables ./exporters/search
COPY tests/e2e ./tests/e2e
ENV PATH="/opt/asr-cli/bin:/opt/asr-python/bin:${PATH}" \
    ASR_REPO_ROOT=/opt/asr ASR_VIEWER_CHROMIUM=/usr/bin/chromium
ENTRYPOINT ["python3", "/opt/asr/tests/e2e/session_test.py"]
