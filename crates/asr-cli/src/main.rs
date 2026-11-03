use clap::{Parser, Subcommand};
mod tools;
use std::{
    io::{self, Write},
    path::{Path, PathBuf},
    process::{Command, ExitCode},
};

#[derive(Parser)]
#[command(
    name = "asr",
    version,
    about = "Convert, collect, inspect, redact, replay and validate Agent Session Record files"
)]
struct Cli {
    #[command(subcommand)]
    command: Action,
}
#[derive(Subcommand)]
enum Action {
    /// Discover, convert and collect changed native sessions.
    Collect(asr_collect::CollectArgs),
    /// Accept authenticated exact-file uploads and write receipt manifests.
    Receive(asr_collect::ReceiveArgs),
    /// Make a redacted derived file. The source is never overwritten.
    Redact(tools::redact::Options),
    /// Find recorded edit and commit evidence behind a Git line.
    Blame(tools::blame::Options),
    /// Re-ask one model call without executing any tools.
    Replay(tools::replay::Options),
    /// Convert one native file or a directory of native history.
    Convert {
        #[arg(long)]
        agent: asr_convert::Agent,
        input: PathBuf,
        #[arg(long)]
        out: PathBuf,
        #[arg(long,default_value_t=16*1024*1024)]
        max_record_bytes: usize,
        /// Stable installation/profile identifier for local session counters.
        #[arg(long)]
        namespace: Option<String>,
    },
    /// List supported agents.
    Agents,
    /// Run the repository's Node validator and preserve its exit code.
    Validate {
        #[arg(long)]
        json: bool,
        #[arg(long)]
        summary: bool,
        input: PathBuf,
    },
}
fn validator() -> Option<PathBuf> {
    if let Some(root) = std::env::var_os("ASR_REPO_ROOT") {
        let p = Path::new(&root).join("tools/validator/bin/asr-validate.js");
        return p.is_file().then_some(p);
    }
    let cwd = std::env::current_dir().ok()?;
    for root in cwd
        .ancestors()
        .chain(Path::new(env!("CARGO_MANIFEST_DIR")).ancestors())
    {
        let p = root.join("tools/validator/bin/asr-validate.js");
        if p.is_file() {
            return Some(p);
        }
    }
    None
}
fn run() -> Result<u8, Box<dyn std::error::Error>> {
    let mut stdout = io::BufWriter::new(io::stdout().lock());
    match Cli::parse().command {
        Action::Collect(args) => {
            let validator =
                validator().ok_or("Node validator was not found. Set ASR_REPO_ROOT.")?;
            let summary = asr_collect::collect(args, &validator)?;
            writeln!(stdout, "{}", serde_json::to_string_pretty(&summary)?)?;
            if summary.failures > 0 {
                stdout.flush()?;
                return Ok(1);
            }
        }
        Action::Receive(args) => {
            let validator =
                validator().ok_or("Node validator was not found. Set ASR_REPO_ROOT.")?;
            asr_collect::receive(args, &validator)?;
        }
        Action::Redact(options) => writeln!(
            stdout,
            "{}",
            serde_json::to_string_pretty(&tools::redact::run(options)?)?
        )?,
        Action::Blame(options) => writeln!(
            stdout,
            "{}",
            serde_json::to_string_pretty(&tools::blame::run(options)?)?
        )?,
        Action::Replay(options) => {
            let report = tools::replay::run(options)?;
            writeln!(stdout, "{}", serde_json::to_string_pretty(&report)?)?;
            if report["requestFailed"] == true {
                stdout.flush()?;
                return Ok(1);
            }
        }
        Action::Agents => {
            for agent in asr_convert::Agent::ALL {
                writeln!(stdout, "{}\t{}", agent.name(), agent.source())?;
            }
        }
        Action::Convert {
            agent,
            input,
            out,
            max_record_bytes,
            namespace,
        } => {
            let summary = match asr_convert::convert(&asr_convert::Options {
                agent,
                input,
                out,
                max_record_bytes,
                namespace,
            }) {
                Ok(summary) => summary,
                Err(error) => {
                    // Parse and source I/O errors may contain recorded private values.
                    match error {
                        asr_convert::Error::Invalid(message) => eprintln!("asr: {message}"),
                        asr_convert::Error::Core(_) => eprintln!("asr: record conversion failed"),
                        asr_convert::Error::Io(_) => eprintln!("asr: source or output I/O failed"),
                        asr_convert::Error::Json(_) => eprintln!("asr: record JSON failed"),
                        asr_convert::Error::Sql(_) => eprintln!("asr: staging index failed"),
                        asr_convert::Error::Session { session, code } => {
                            eprintln!("asr: session {session}: {code}")
                        }
                    }
                    return Ok(2);
                }
            };
            writeln!(stdout, "{}", serde_json::to_string_pretty(&summary)?)?;
            if summary.sessions == 0
                || summary
                    .diagnostics
                    .contains_key("session_conversion_failed")
                || summary.diagnostics.contains_key("session_header_shape")
                || summary.diagnostics.contains_key("source_staging_failed")
                || summary
                    .diagnostics
                    .contains_key("colliding_session_identity")
            {
                stdout.flush()?;
                return Ok(1);
            }
        }
        Action::Validate {
            json,
            summary,
            input,
        } => {
            let validator = validator().ok_or(
                "Node validator was not found. Run from the ASR repository or set ASR_REPO_ROOT.",
            )?;
            let mut command = Command::new("node");
            command.arg(validator);
            if json {
                command.arg("--json");
            }
            if summary {
                command.arg("--summary");
            }
            let status = command.arg(input).status()?;
            return Ok(status
                .code()
                .and_then(|n| u8::try_from(n).ok())
                .unwrap_or(2));
        }
    }
    stdout.flush()?;
    Ok(0)
}
fn main() -> ExitCode {
    match run() {
        Ok(code) => ExitCode::from(code),
        Err(error)
            if error
                .downcast_ref::<io::Error>()
                .is_some_and(|e| e.kind() == io::ErrorKind::BrokenPipe) =>
        {
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("asr: {error}");
            ExitCode::from(2)
        }
    }
}
