use crate::{util::*, Error, Failure, ReceiptStore, ReceiveArgs, Result};
use chrono::Utc;
use serde::Deserialize;
use serde_json::json;
use std::{
    collections::BTreeSet,
    io::{Read, Write},
    net::SocketAddr,
    path::PathBuf,
    time::Duration,
};
use tiny_http::{Header, Method, Request, Response, Server, StatusCode};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AuthEntry {
    pub token: String,
    pub uploader: String,
    pub machines: Vec<String>,
}

struct Principal {
    token_digest: [u8; 32],
    uploader: String,
    machines: Vec<String>,
}

pub struct Receiver {
    server: Server,
    store: ReceiptStore,
    principals: Vec<Principal>,
    max_bytes: u64,
}

impl Receiver {
    pub fn bind(args: ReceiveArgs, validator: PathBuf) -> Result<Self> {
        if args.max_upload_bytes == 0 || args.max_upload_bytes == u64::MAX {
            return Err(Error::Invalid(
                "upload byte limit must be positive and bounded",
            ));
        }
        let auth: Vec<AuthEntry> = serde_json::from_slice(&private_file(&args.auth_file)?)?;
        if auth.is_empty() {
            return Err(Error::Invalid(
                "receiver needs at least one authenticated uploader",
            ));
        }
        let mut seen = BTreeSet::new();
        let mut principals = Vec::new();
        for entry in auth {
            if entry.token.len() < 16
                || !entry.token.bytes().all(|b| b.is_ascii_graphic())
                || entry.uploader.is_empty()
                || entry.machines.is_empty()
                || !entry.machines.iter().all(|m| valid_machine(m))
            {
                return Err(Error::Invalid("invalid receiver authentication entry"));
            }
            let token_digest = token_digest(&entry.token);
            if !seen.insert(token_digest) {
                return Err(Error::Invalid("receiver token is duplicated"));
            }
            principals.push(Principal {
                token_digest,
                uploader: entry.uploader,
                machines: entry.machines,
            });
        }
        let store = ReceiptStore::open(&args.out, args.window_seconds, &validator)?;
        let server = Server::http(args.bind)
            .map_err(|_| Error::Invalid("receiver could not bind its socket"))?;
        Ok(Self {
            server,
            store,
            principals,
            max_bytes: args.max_upload_bytes,
        })
    }

    pub fn address(&self) -> Result<SocketAddr> {
        self.server
            .server_addr()
            .to_ip()
            .ok_or(Error::Invalid("receiver has no IP socket"))
    }

    pub fn run(&mut self) -> Result<()> {
        eprintln!("asr receive: listening on {}", self.address()?);
        loop {
            self.serve_once(Duration::from_millis(250))?;
        }
    }

    pub fn serve_once(&mut self, timeout: Duration) -> Result<()> {
        self.store.rotate(Utc::now())?;
        if let Some(mut request) = self.server.recv_timeout(timeout)? {
            let result = self.handle(&mut request);
            let (status, value) = match result {
                Ok(response) => response,
                Err(Error::Invalid(_)) => (
                    409,
                    json!({"error":"upload metadata conflicts with stored state"}),
                ),
                Err(_) => (500, json!({"error":"receipt storage failed"})),
            };
            let bytes = serde_json::to_vec(&value)?;
            let response = Response::from_data(bytes)
                .with_status_code(StatusCode(status))
                .with_header(
                    Header::from_bytes("Content-Type", "application/json")
                        .map_err(|_| Error::Invalid("invalid response header"))?,
                );
            // A disconnected uploader retries with the same upload ID.
            let _ = request.respond(response);
        }
        Ok(())
    }

    fn handle(&mut self, request: &mut Request) -> Result<(u16, serde_json::Value)> {
        let Some(bearer) =
            single_header(request, "Authorization").and_then(|s| s.strip_prefix("Bearer "))
        else {
            return Ok((401, json!({"error":"authentication required"})));
        };
        let candidate = token_digest(bearer);
        let principal = self
            .principals
            .iter()
            .find(|p| constant_time_eq(&p.token_digest, &candidate));
        let Some(principal) = principal else {
            return Ok((401, json!({"error":"authentication required"})));
        };
        let machine = single_header(request, "X-ASR-Machine")
            .unwrap_or("")
            .to_owned();
        if !principal.machines.contains(&machine) {
            return Ok((
                403,
                json!({"error":"machine is not assigned to this uploader"}),
            ));
        }
        let uploader = principal.uploader.clone();
        if request.method() != &Method::Post {
            return Ok((405, json!({"error":"POST required"})));
        }
        if request.url() == "/v1/heartbeat" {
            self.store.heartbeat(&machine, Utc::now())?;
            return Ok((200, json!({"status":"ok"})));
        }
        let id = single_header(request, "X-ASR-Upload-ID")
            .unwrap_or("")
            .to_owned();
        if id.is_empty() || id.len() > 128 {
            return Ok((400, json!({"error":"upload ID required"})));
        }
        match request.url() {
            "/v1/sessions" => {
                let sha = single_header(request, "X-ASR-Sha256")
                    .unwrap_or("")
                    .to_owned();
                if !valid_digest(&sha) {
                    return Ok((400, json!({"error":"SHA-256 required"})));
                }
                let mut file = tempfile::NamedTempFile::new_in(self.store.root())?;
                let declared_length = request.body_length();
                let length = match std::io::copy(
                    &mut request.as_reader().take(self.max_bytes + 1),
                    &mut file,
                ) {
                    Ok(length) => length,
                    Err(_) => {
                        self.store.failure(
                            &machine,
                            &uploader,
                            &id,
                            Failure {
                                reason: "Upload ended before its complete bytes arrived.",
                                session: None,
                            },
                            Utc::now(),
                        )?;
                        return Ok((400, json!({"error":"incomplete upload"})));
                    }
                };
                if length > self.max_bytes {
                    self.store.failure(
                        &machine,
                        &uploader,
                        &id,
                        Failure {
                            reason: "Upload exceeded the configured byte limit.",
                            session: None,
                        },
                        Utc::now(),
                    )?;
                    return Ok((413, json!({"error":"upload exceeds byte limit"})));
                }
                if declared_length.is_some_and(|declared| declared as u64 != length) {
                    self.store.failure(
                        &machine,
                        &uploader,
                        &id,
                        Failure {
                            reason: "Upload ended before its complete bytes arrived.",
                            session: None,
                        },
                        Utc::now(),
                    )?;
                    return Ok((400, json!({"error":"incomplete upload"})));
                }
                file.flush()?;
                let receipt =
                    self.store
                        .ingest(&machine, &uploader, &id, file.path(), &sha, Utc::now())?;
                Ok((200, serde_json::to_value(receipt)?))
            }
            "/v1/failures" => {
                let mut bytes = Vec::new();
                request.as_reader().take(8193).read_to_end(&mut bytes)?;
                if bytes.len() > 8192 {
                    return Ok((413, json!({"error":"failure report exceeds byte limit"})));
                }
                let report: serde_json::Value = match std::str::from_utf8(&bytes)
                    .ok()
                    .and_then(|s| asr_core::jsonl::decode(s).ok())
                {
                    Some(v) => v,
                    None => return Ok((400, json!({"error":"invalid failure report"}))),
                };
                let Some(reason) = report["reason"]
                    .as_str()
                    .filter(|s| !s.is_empty() && s.len() <= 1024)
                else {
                    return Ok((400, json!({"error":"failure reason required"})));
                };
                let session = match report.get("session") {
                    None | Some(serde_json::Value::Null) => None,
                    Some(serde_json::Value::String(s)) => Some(s.as_str()),
                    _ => return Ok((400, json!({"error":"invalid session reference"}))),
                };
                match self.store.failure(
                    &machine,
                    &uploader,
                    &id,
                    Failure { reason, session },
                    Utc::now(),
                ) {
                    Ok(receipt) => Ok((200, serde_json::to_value(receipt)?)),
                    Err(Error::Invalid(_)) => Ok((400, json!({"error":"invalid failure report"}))),
                    Err(error) => Err(error),
                }
            }
            _ => Ok((404, json!({"error":"unknown receiver route"}))),
        }
    }
}

fn single_header<'a>(request: &'a Request, name: &str) -> Option<&'a str> {
    let mut values = request
        .headers()
        .iter()
        .filter(|h| h.field.as_str().as_str().eq_ignore_ascii_case(name));
    let first = values.next()?.value.as_str();
    values.next().is_none().then_some(first)
}
fn token_digest(value: &str) -> [u8; 32] {
    use sha2::{Digest, Sha256};
    Sha256::digest(value.as_bytes()).into()
}
fn constant_time_eq(left: &[u8; 32], right: &[u8; 32]) -> bool {
    left.iter()
        .zip(right)
        .fold(0u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}
