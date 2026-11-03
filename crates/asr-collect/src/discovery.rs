//! Default native roots. Explicit sources support alternate installations.
use asr_convert::Agent;
use std::path::{Path, PathBuf};

fn configured(name: &str, fallback: PathBuf) -> PathBuf {
    std::env::var_os(name)
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or(fallback)
}

fn xum_root(home: &Path) -> PathBuf {
    xum_root_with(
        home,
        std::env::var_os("XUM_ROOT"),
        std::env::var_os("MUX_ROOT"),
    )
}

fn xum_root_with(
    home: &Path,
    current: Option<std::ffi::OsString>,
    legacy: Option<std::ffi::OsString>,
) -> PathBuf {
    current
        .filter(|v| !v.is_empty())
        .or_else(|| legacy.filter(|v| !v.is_empty()))
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            [".xum", ".mux", ".cmux"]
                .into_iter()
                .map(|name| home.join(name))
                .find(|path| path.is_dir())
                .unwrap_or_else(|| home.join(".xum"))
        })
}

pub(crate) fn default_roots(agent: Agent, home: &Path, cwd: &Path) -> Vec<PathBuf> {
    let data = configured("XDG_DATA_HOME", home.join(".local/share"));
    let config = configured("XDG_CONFIG_HOME", home.join(".config"));
    match agent {
        Agent::ClaudeCode => {
            vec![configured("CLAUDE_CONFIG_DIR", home.join(".claude")).join("projects")]
        }
        Agent::Codex => {
            let root = configured("CODEX_HOME", home.join(".codex"));
            vec![root.join("sessions"), root.join("archived_sessions")]
        }
        Agent::Cursor => vec![home.join(".cursor/projects")],
        Agent::GeminiCli => vec![home.join(".gemini/tmp")],
        Agent::MistralVibe => vec![configured("VIBE_HOME", home.join(".vibe")).join("logs")],
        Agent::Mux => vec![configured("MUX_ROOT", home.join(".mux")).join("sessions")],
        Agent::Xum => vec![xum_root(home).join("sessions")],
        Agent::Fx => vec![home.join(".fx/sessions")],
        Agent::Antigravity => vec![home.join(".gemini/antigravity")],
        Agent::Tabnine => vec![home.join(".tabnine/agent")],
        Agent::Qoder => vec![home.join(".qoder/projects")],
        Agent::Droid => vec![home.join(".factory/sessions")],
        Agent::CopilotCli => vec![home.join(".copilot/session-state")],
        Agent::QwenCode => vec![home.join(".qwen/projects")],
        Agent::GrokBuild => vec![home.join(".grok/sessions")],
        Agent::Pi => vec![home.join(".pi/agent/sessions")],
        Agent::KimiCode => vec![configured("KIMI_CODE_HOME", home.join(".kimi-code"))],
        Agent::DeepSeekHarness => vec![configured("DSH_HOME", home.join(".dsh")).join("sessions")],
        Agent::Junie => vec![home.join(".junie/sessions")],
        Agent::OpenClaw => {
            vec![configured("OPENCLAW_STATE_DIR", home.join(".openclaw")).join("agents")]
        }
        Agent::Auggie => vec![home.join(".augment/sessions")],
        Agent::Cline | Agent::RooCode => {
            let mut roots = if agent == Agent::Cline {
                vec![home.join(".cline/data")]
            } else {
                Vec::new()
            };
            let extensions: &[&str] = if agent == Agent::Cline {
                &["saoudrizwan.claude-dev"]
            } else {
                &["rooveterinaryinc.roo-cline", "RooVeterinaryInc.roo-cline"]
            };
            for editor in ["Code", "Code - Insiders", "VSCodium", "Cursor"] {
                for extension in extensions {
                    roots.push(
                        config
                            .join(editor)
                            .join("User/globalStorage")
                            .join(extension)
                            .join("tasks"),
                    );
                }
            }
            roots
        }
        Agent::CodeBuddy => vec![configured("CODEBUDDY_HOME", home.join(".codebuddy"))],
        Agent::Continue => {
            vec![configured("CONTINUE_GLOBAL_DIR", home.join(".continue")).join("sessions")]
        }
        Agent::Hermes => vec![configured("HERMES_HOME", home.join(".hermes"))],
        Agent::NanoClaw => vec![home.join("nanoclaw"), home.join("code/nanoclaw")],
        Agent::OpenHands => vec![
            home.join(".openhands/conversations"),
            home.join(".openhands/v1_conversations"),
        ],
        Agent::RovoDev => vec![configured("ROVODEV_HOME", home.join(".rovodev")).join("sessions")],
        Agent::AstrBot => vec![
            home.join(".astrbot/data"),
            home.join(".astrbot_launcher/instances"),
            cwd.join("data/data_v4.db"),
        ],
        Agent::Crush => vec![data.join("crush"), cwd.join(".crush")],
        Agent::Lingma => vec![home.join(".lingma")],
        Agent::Shelley => vec![cwd.join("shelley.db")],
        Agent::DeepAgents => vec![home.join(".deepagents")],
        Agent::ForgeCode => vec![
            home.join(".forge"),
            home.join("forge"),
            cwd.join(".forge.db"),
        ],
        Agent::OpenCode => vec![data.join("opencode")],
        Agent::Kilo => vec![data.join("kilo")],
        Agent::MimoCode => vec![data.join("mimocode")],
        Agent::Zed => vec![data.join("zed")],
        Agent::Devin => vec![data.join("devin/cli/sessions.db")],
        Agent::Firebender => vec![cwd.join(".idea/firebender/chat_history.db")],
        Agent::Goose => vec![data.join("goose/sessions")],
        Agent::Kiro => vec![
            data.join("kiro-cli"),
            data.join("amazon-q"),
            data.join("kiro"),
        ],
        Agent::Warp => {
            vec![configured("XDG_STATE_HOME", home.join(".local/state")).join("warp-terminal")]
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn xum_root_precedence_and_legacy_homes() {
        let temporary = tempfile::tempdir().unwrap();
        let home = temporary.path();
        assert_eq!(xum_root_with(home, None, None), home.join(".xum"));
        std::fs::create_dir(home.join(".cmux")).unwrap();
        assert_eq!(xum_root_with(home, None, None), home.join(".cmux"));
        std::fs::create_dir(home.join(".mux")).unwrap();
        assert_eq!(xum_root_with(home, None, None), home.join(".mux"));
        std::fs::create_dir(home.join(".xum")).unwrap();
        assert_eq!(xum_root_with(home, None, None), home.join(".xum"));
        assert_eq!(
            xum_root_with(home, None, Some("/legacy".into())),
            Path::new("/legacy")
        );
        assert_eq!(
            xum_root_with(home, Some("/current".into()), Some("/legacy".into())),
            Path::new("/current")
        );
    }
    #[test]
    fn every_registered_converter_has_default_roots() {
        for agent in Agent::ALL {
            assert!(
                !default_roots(
                    agent,
                    Path::new("/synthetic-user"),
                    Path::new("/synthetic-project")
                )
                .is_empty(),
                "{}",
                agent.name()
            );
        }
    }
}
