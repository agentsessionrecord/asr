//! Bounded native-log conversion. The public entry point never executes log content.
mod astrbot;
mod auggie;
mod batch_a;
mod claude;
mod cline;
mod codebuddy;
mod codex;
mod common;
mod continue_cli;
mod crush;
mod cursor;
mod deepagents;
mod devin;
mod documents;
mod firebender;
mod forgecode;
mod fx;
mod gemini;
mod goose;
mod hermes;
mod jsonl;
mod kilo;
mod kiro;
mod lingma;
mod mimocode;
mod mistral_vibe;
mod mux;
mod nanoclaw;
mod openclaw;
mod opencode;
mod openhands;
mod privacy;
mod profile;
mod repository;
mod roo_code;
mod rovodev;
mod shelley;
mod source;
mod spool;
mod sqlite;
mod warp;
mod zed;

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("ASR core: {0}")]
    Core(#[from] asr_core::Error),
    #[error("I/O: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("staging index: {0}")]
    Sql(#[from] rusqlite::Error),
    #[error("{0}")]
    Invalid(String),
    #[error("session {session}: {code}")]
    Session { session: String, code: &'static str },
}
pub type Result<T> = std::result::Result<T, Error>;
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Agent {
    ClaudeCode,
    Codex,
    AstrBot,
    Crush,
    Lingma,
    Shelley,
    DeepAgents,
    ForgeCode,
    OpenCode,
    Kilo,
    MimoCode,
    Zed,
    Devin,
    Firebender,
    Goose,
    Kiro,
    Warp,
    Cursor,
    GeminiCli,
    MistralVibe,
    Mux,
    Fx,
    Antigravity,
    Tabnine,
    Qoder,
    Droid,
    CopilotCli,
    QwenCode,
    GrokBuild,
    Pi,
    KimiCode,
    DeepSeekHarness,
    Junie,
    OpenClaw,
    Auggie,
    Cline,
    CodeBuddy,
    Continue,
    Hermes,
    NanoClaw,
    OpenHands,
    RooCode,
    RovoDev,
}
impl Agent {
    pub const ALL: [Self; 43] = [
        Self::ClaudeCode,
        Self::Codex,
        Self::AstrBot,
        Self::Crush,
        Self::Lingma,
        Self::Shelley,
        Self::DeepAgents,
        Self::ForgeCode,
        Self::OpenCode,
        Self::Kilo,
        Self::MimoCode,
        Self::Zed,
        Self::Devin,
        Self::Firebender,
        Self::Goose,
        Self::Kiro,
        Self::Warp,
        Self::Cursor,
        Self::GeminiCli,
        Self::MistralVibe,
        Self::Mux,
        Self::Fx,
        Self::Antigravity,
        Self::Tabnine,
        Self::Qoder,
        Self::Droid,
        Self::CopilotCli,
        Self::QwenCode,
        Self::GrokBuild,
        Self::Pi,
        Self::KimiCode,
        Self::DeepSeekHarness,
        Self::Junie,
        Self::OpenClaw,
        Self::Auggie,
        Self::Cline,
        Self::CodeBuddy,
        Self::Continue,
        Self::Hermes,
        Self::NanoClaw,
        Self::OpenHands,
        Self::RooCode,
        Self::RovoDev,
    ];
    pub(crate) fn jsonl(self) -> bool {
        matches!(
            self,
            Self::Antigravity
                | Self::Tabnine
                | Self::Qoder
                | Self::Droid
                | Self::CopilotCli
                | Self::QwenCode
                | Self::GrokBuild
                | Self::Pi
                | Self::KimiCode
                | Self::DeepSeekHarness
                | Self::Junie
                | Self::OpenClaw
        )
    }
    pub fn name(self) -> &'static str {
        match self {
            Self::AstrBot => "astrbot",
            Self::Crush => "crush",
            Self::Lingma => "lingma",
            Self::Shelley => "shelley",
            Self::DeepAgents => "deepagents",
            Self::ForgeCode => "forgecode",
            Self::OpenCode => "opencode",
            Self::Kilo => "kilo",
            Self::MimoCode => "mimocode",
            Self::Zed => "zed",
            Self::Devin => "devin",
            Self::Firebender => "firebender",
            Self::Goose => "goose",
            Self::Kiro => "kiro",
            Self::Warp => "warp",
            Self::ClaudeCode => "claude-code",
            Self::Codex => "codex",
            Self::Cursor => "cursor",
            Self::GeminiCli => "gemini-cli",
            Self::MistralVibe => "mistral-vibe",
            Self::Mux => "mux",
            Self::Fx => "fx",
            Self::Antigravity => "antigravity",
            Self::Tabnine => "tabnine",
            Self::Qoder => "qoder",
            Self::Droid => "droid",
            Self::CopilotCli => "copilot-cli",
            Self::QwenCode => "qwen-code",
            Self::GrokBuild => "grok-build",
            Self::Pi => "pi",
            Self::KimiCode => "kimi-code",
            Self::DeepSeekHarness => "deepseek-harness",
            Self::Junie => "junie",
            Self::OpenClaw => "openclaw",
            Self::Auggie => "auggie",
            Self::Cline => "cline",
            Self::CodeBuddy => "codebuddy",
            Self::Continue => "continue",
            Self::Hermes => "hermes",
            Self::NanoClaw => "nanoclaw",
            Self::OpenHands => "openhands",
            Self::RooCode => "roo-code",
            Self::RovoDev => "rovodev",
        }
    }
    pub fn domain(self) -> &'static str {
        match self {
            Self::AstrBot => "app.astrbot",
            Self::Crush => "sh.charm.crush",
            Self::Lingma => "com.aliyun.lingma",
            Self::Shelley => "dev.exe.shelley",
            Self::DeepAgents => "com.langchain.deepagents",
            Self::ForgeCode => "dev.forgecode",
            Self::OpenCode => "ai.opencode",
            Self::Kilo => "ai.kilo",
            Self::MimoCode => "com.xiaomi.mimocode",
            Self::Zed => "dev.zed",
            Self::Devin => "ai.cognition.devin",
            Self::Firebender => "com.firebender",
            Self::Goose => "xyz.block.goose",
            Self::Kiro => "dev.kiro.cli",
            Self::Warp => "dev.warp.agent",
            Self::ClaudeCode => "com.anthropic.claude-code",
            Self::Codex => "com.openai.codex",
            Self::Cursor => "com.cursor.agent",
            Self::GeminiCli => "com.google.gemini-cli",
            Self::MistralVibe => "ai.mistral.vibe",
            Self::Mux => "com.coder.mux",
            Self::Fx => "com.vercel.fx",
            Self::Antigravity => "com.google.antigravity",
            Self::Tabnine => "com.tabnine.cli",
            Self::Qoder => "com.qoder.cli",
            Self::Droid => "ai.factory.droid",
            Self::CopilotCli => "com.github.copilot-cli",
            Self::QwenCode => "io.github.qwenlm.qwen-code",
            Self::GrokBuild => "ai.x.grok-build",
            Self::Pi => "io.github.badlogic.pi",
            Self::KimiCode => "com.moonshot.kimi-code",
            Self::DeepSeekHarness => "com.deepseek.harness",
            Self::Junie => "com.jetbrains.junie",
            Self::OpenClaw => "ai.openclaw",
            Self::Auggie => "com.augmentcode.auggie",
            Self::Cline => "bot.cline",
            Self::CodeBuddy => "cn.codebuddy",
            Self::Continue => "dev.continue",
            Self::Hermes => "com.nousresearch.hermes",
            Self::NanoClaw => "dev.nanoclaw",
            Self::OpenHands => "dev.openhands",
            Self::RooCode => "com.roocode",
            Self::RovoDev => "com.atlassian.rovodev",
        }
    }
    pub fn source(self) -> &'static str {
        match self {
            Self::AstrBot => "astrbot-sqlite",
            Self::Crush => "crush-sqlite",
            Self::Lingma => "lingma-sqlite",
            Self::Shelley => "shelley-sqlite",
            Self::DeepAgents => "deepagents-sqlite",
            Self::ForgeCode => "forgecode-sqlite",
            Self::OpenCode => "opencode-sqlite",
            Self::Kilo => "kilo-sqlite",
            Self::MimoCode => "mimocode-sqlite",
            Self::Zed => "zed-sqlite",
            Self::Devin => "devin-sqlite",
            Self::Firebender => "firebender-sqlite",
            Self::Goose => "goose-sqlite",
            Self::Kiro => "kiro-sqlite",
            Self::Warp => "warp-sqlite",
            Self::ClaudeCode => "claude-code-jsonl",
            Self::Codex => "codex-rollout",
            Self::Cursor => "cursor-agent-transcript",
            Self::GeminiCli => "gemini-cli-jsonl",
            Self::MistralVibe => "mistral-vibe-session",
            Self::Mux => "mux-chat-jsonl",
            Self::Fx => "fx-event-log-v1",
            Self::Antigravity => "antigravity-transcript-jsonl",
            Self::Tabnine => "tabnine-chat-jsonl",
            Self::Qoder => "qoder-transcript-jsonl",
            Self::Droid => "factory-droid-jsonl",
            Self::CopilotCli => "copilot-session-events-jsonl",
            Self::QwenCode => "qwen-code-chat-jsonl",
            Self::GrokBuild => "grok-build-acp-jsonl",
            Self::Pi => "pi-jsonl",
            Self::KimiCode => "kimi-code-wire-jsonl",
            Self::DeepSeekHarness => "deepseek-harness-session-jsonl",
            Self::Junie => "junie-events-jsonl",
            Self::OpenClaw => "openclaw-jsonl",
            Self::Auggie => "auggie-session-json",
            Self::Cline => "cline-task-json",
            Self::CodeBuddy => "codebuddy-history",
            Self::Continue => "continue-session-json",
            Self::Hermes => "hermes-state-sqlite",
            Self::NanoClaw => "nanoclaw-project-sqlite",
            Self::OpenHands => "openhands-events-json",
            Self::RooCode => "roo-task-json",
            Self::RovoDev => "rovodev-session-json",
        }
    }
}
impl std::str::FromStr for Agent {
    type Err = String;
    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        Self::ALL
            .into_iter()
            .find(|a| a.name() == s)
            .ok_or_else(|| format!("unsupported agent: {s}"))
    }
}
#[derive(Debug, Clone)]
pub struct Options {
    pub agent: Agent,
    pub input: PathBuf,
    pub out: PathBuf,
    pub max_record_bytes: usize,
    /// Stable installation identity for native counters or directory-keyed sessions.
    pub namespace: Option<String>,
}
impl Options {
    pub fn new(agent: Agent, input: PathBuf, out: PathBuf) -> Self {
        Self {
            agent,
            input,
            out,
            max_record_bytes: 16 * 1024 * 1024,
            namespace: None,
        }
    }
}
#[derive(Debug, Default, Serialize)]
pub struct Summary {
    pub files: u64,
    pub sessions: u64,
    pub records: u64,
    pub source_bytes: u64,
    pub diagnostics: std::collections::BTreeMap<String, u64>,
    /// Diagnostic codes grouped by recorded session reference. No source text is included.
    pub session_diagnostics:
        std::collections::BTreeMap<String, std::collections::BTreeMap<String, u64>>,
}
impl Summary {
    pub(crate) fn diagnostic(&mut self, code: &str) {
        *self.diagnostics.entry(code.into()).or_default() += 1;
    }
    pub(crate) fn diagnostic_for(&mut self, session: &str, code: &str) {
        self.diagnostic(code);
        *self
            .session_diagnostics
            .entry(session.into())
            .or_default()
            .entry(code.into())
            .or_default() += 1;
    }
}

pub fn convert(options: &Options) -> Result<Summary> {
    convert_impl(options, None, None)
}

/// Convert a complete group of source files without scanning unrelated sessions.
pub fn convert_files(options: &Options, files: &[PathBuf]) -> Result<Summary> {
    convert_impl(options, Some(files), None)
}

mod collection;
use collection::stage_files;
pub use collection::{discover_agent, identify_sources, source_dependencies};

/// Convert one recorded session from a complete source group.
pub fn convert_session_files(
    options: &Options,
    files: &[PathBuf],
    session: &str,
) -> Result<Summary> {
    convert_impl(options, Some(files), Some(session))
}

fn convert_impl(
    options: &Options,
    files: Option<&[PathBuf]>,
    selected: Option<&str>,
) -> Result<Summary> {
    if options.max_record_bytes < 1024 {
        return Err(Error::Invalid(
            "max_record_bytes must be at least 1024".into(),
        ));
    }
    if !options.input.exists() {
        return Err(Error::Invalid("input does not exist".into()));
    }
    let input = std::fs::canonicalize(&options.input)?;
    let destination = common::destination(&options.out)?;
    if destination.starts_with(&input) && input.is_dir() {
        return Err(Error::Invalid(
            "output must be outside the input directory".into(),
        ));
    }
    common::private_dir(&destination)?;
    let out = std::fs::canonicalize(&destination)?;
    let mut summary = Summary::default();
    let mut profile = profile::Profile::new();
    let mut spool = spool::Spool::new(&out, options.max_record_bytes)?;
    let paths = match files {
        Some(paths) => paths.to_vec(),
        None => discover_agent(options.agent, &options.input, &out)?,
    };
    if selected.is_some() {
        stage_files(&mut spool, options, &paths, &mut summary)?;
    } else {
        collection::stage_isolated(&mut spool, options, &paths, &mut summary)?;
    }
    profile.mark("staging");
    privacy::prepare(&mut spool)?;
    profile.mark("privacy");
    let mut previous = String::new();
    while let Some((session, mut header)) = spool.next_session(&previous)? {
        previous = session.clone();
        if selected.is_some_and(|wanted| {
            wanted
                != asr_core::identity::session_ref(
                    options.agent.name(),
                    header["namespace"].as_str(),
                    header["sessionId"].as_str().unwrap_or(&session),
                )
        }) {
            continue;
        }
        let reference = asr_core::identity::session_ref(
            options.agent.name(),
            header["namespace"].as_str(),
            header["sessionId"].as_str().unwrap_or(&session),
        );
        let result = (|| -> Result<()> {
            spool.begin_session(&session)?;
            let mut context = common::Context::new(options.agent, session.clone());
            context.cwd = header["cwd"].as_str().map(str::to_owned);
            context.namespace = header["namespace"].as_str().map(str::to_owned);
            spool.for_each_native(&session, |pos, mut value| {
                context.position(pos, &value);
                if value["_asrOpaqueOmitted"] == true {
                    context.loss("reasoning");
                    value.as_object_mut().unwrap().remove("_asrOpaqueOmitted");
                }
                if privacy::sanitize(&spool, &mut value)? {
                    context.redacted = true;
                    context.loss("redacted_content");
                    summary.diagnostic("secret_redacted");
                }
                asr_core::jsonl::stringify_large_native(&mut value);
                match options.agent {
                    Agent::ClaudeCode => claude::convert(&spool, &mut context, &value)?,
                    Agent::Codex => codex::convert(&spool, &mut context, &value)?,
                    Agent::Cursor => cursor::convert(&spool, &mut context, &value)?,
                    Agent::GeminiCli => gemini::convert(&spool, &mut context, &value)?,
                    Agent::MistralVibe => mistral_vibe::convert(&spool, &mut context, &value)?,
                    Agent::Mux => mux::convert(&spool, &mut context, &value)?,
                    Agent::Fx => fx::convert(&spool, &mut context, &value)?,
                    Agent::Auggie => auggie::convert(&spool, &mut context, &value)?,
                    Agent::Cline => cline::convert(&spool, &mut context, &value)?,
                    Agent::CodeBuddy => codebuddy::convert(&spool, &mut context, &value)?,
                    Agent::Continue => continue_cli::convert(&spool, &mut context, &value)?,
                    Agent::Hermes => hermes::convert(&spool, &mut context, &value)?,
                    Agent::NanoClaw => nanoclaw::convert(&spool, &mut context, &value)?,
                    Agent::OpenHands => openhands::convert(&spool, &mut context, &value)?,
                    Agent::RooCode => roo_code::convert(&spool, &mut context, &value)?,
                    Agent::RovoDev => rovodev::convert(&spool, &mut context, &value)?,
                    Agent::AstrBot => astrbot::convert(&spool, &mut context, &value)?,
                    Agent::Crush => crush::convert(&spool, &mut context, &value)?,
                    Agent::Lingma => lingma::convert(&spool, &mut context, &value)?,
                    Agent::Shelley => shelley::convert(&spool, &mut context, &value)?,
                    Agent::DeepAgents => deepagents::convert(&spool, &mut context, &value)?,
                    Agent::ForgeCode => forgecode::convert(&spool, &mut context, &value)?,
                    Agent::OpenCode => opencode::convert(&spool, &mut context, &value)?,
                    Agent::Kilo => kilo::convert(&spool, &mut context, &value)?,
                    Agent::MimoCode => mimocode::convert(&spool, &mut context, &value)?,
                    Agent::Zed => zed::convert(&spool, &mut context, &value)?,
                    Agent::Devin => devin::convert(&spool, &mut context, &value)?,
                    Agent::Firebender => firebender::convert(&spool, &mut context, &value)?,
                    Agent::Goose => goose::convert(&spool, &mut context, &value)?,
                    Agent::Kiro => kiro::convert(&spool, &mut context, &value)?,
                    Agent::Warp => warp::convert(&spool, &mut context, &value)?,
                    Agent::OpenClaw if value.get("table").is_some() => {
                        openclaw::convert(&spool, &mut context, &value)?
                    }
                    _ => jsonl::convert(&spool, &mut context, &value)?,
                }
                Ok(())
            })?;
            profile.mark("projection");
            if privacy::sanitize(&spool, &mut header)? {
                header["truncated"] = serde_json::json!(true);
                context.loss("redacted_content");
            }
            asr_core::jsonl::stringify_large_native(&mut header);
            common::finish(&spool, &mut context, header, &out, &mut summary)?;
            profile.mark("output");
            Ok(())
        })();
        if let Err(error) = result {
            let code = match error {
                Error::Session { code, .. } => code,
                _ => "session_conversion_failed",
            };
            if selected.is_some() {
                return Err(Error::Session {
                    session: reference,
                    code,
                });
            }
            summary.diagnostic_for(&reference, code);
        }
    }
    Ok(summary)
}
