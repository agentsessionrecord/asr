use clap::Args;
use std::{net::SocketAddr, path::PathBuf};

#[derive(Debug, Clone, Args)]
pub struct CollectArgs {
    /// Local directory, file://, s3://, gs://, az://, or HTTP receiver URL.
    #[arg(long)]
    pub target: String,
    /// Private directory for incremental state and pending uploads.
    #[arg(long)]
    pub state: PathBuf,
    /// Stable machine ID. Assigned and retained in state when omitted.
    #[arg(long)]
    pub machine: Option<String>,
    /// Configured uploader identity for direct storage targets.
    #[arg(long)]
    pub uploader: Option<String>,
    /// Native root as agent=path. Repeat for more roots. Defaults to installed agents.
    #[arg(long = "source")]
    pub sources: Vec<String>,
    /// Restrict default discovery to these supported agents.
    #[arg(long = "agent")]
    pub agents: Vec<asr_convert::Agent>,
    /// Stable installation namespace for sources whose native IDs repeat.
    #[arg(long)]
    pub namespace: Option<String>,
    /// Bearer token file for an HTTP receiver. Never pass tokens as arguments.
    #[arg(long)]
    pub token_file: Option<PathBuf>,
    /// Continue watching after the initial scan.
    #[arg(long)]
    pub watch: bool,
    /// Poll interval. Polling continues when file events are unavailable.
    #[arg(long, default_value_t = 30)]
    pub poll_seconds: u64,
    /// Disable file events and use polling only.
    #[arg(long)]
    pub poll_only: bool,
    /// Fixed UTC receipt window size in seconds.
    #[arg(long, default_value_t = 3600)]
    pub window_seconds: u64,
    /// Select only files modified within this many hours on initial discovery.
    #[arg(long)]
    pub recent_hours: Option<u64>,
    /// Convert at most this many changed sessions per scan, newest first.
    #[arg(long)]
    pub max_sessions: Option<usize>,
    #[arg(long, default_value_t = 16 * 1024 * 1024)]
    pub max_record_bytes: usize,
}

#[derive(Debug, Clone, Args)]
pub struct ReceiveArgs {
    /// Bind address. Use a TLS reverse proxy for remote connections.
    #[arg(long, default_value = "127.0.0.1:8787")]
    pub bind: SocketAddr,
    /// Private receipt store directory.
    #[arg(long)]
    pub out: PathBuf,
    /// Private JSON array of {token, uploader, machines} entries.
    #[arg(long)]
    pub auth_file: PathBuf,
    #[arg(long, default_value_t = 3600)]
    pub window_seconds: u64,
    /// Maximum bytes accepted in one upload.
    #[arg(long, default_value_t = 256 * 1024 * 1024)]
    pub max_upload_bytes: u64,
}
