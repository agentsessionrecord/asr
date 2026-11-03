use crate::{util::*, Error, Result};
use chrono::{DateTime, SecondsFormat, Utc};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    fs::File,
    io::{BufReader, Write},
    path::{Path, PathBuf},
};

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Receipt {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sha256: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub byte_length: Option<u64>,
    pub received_at: String,
    pub uploader: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub producer: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub replaces: Option<Value>,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub identity_mismatch: Option<Value>,
}

pub struct ReceiptStore {
    root: PathBuf,
    db: Connection,
    window: i64,
    validator: PathBuf,
    schema: jsonschema::Validator,
    entry_schema: jsonschema::Validator,
    _lock: FileLock,
}

#[derive(Debug)]
pub struct ManifestFile {
    pub key: String,
    pub bytes: Vec<u8>,
    pub sha256: String,
}

pub struct Failure<'a> {
    pub reason: &'a str,
    pub session: Option<&'a str>,
}

fn timestamp(time: DateTime<Utc>) -> String {
    time.to_rfc3339_opts(SecondsFormat::Millis, true)
}
fn boundary(time: DateTime<Utc>, window: i64) -> i64 {
    time.timestamp().div_euclid(window) * window
}

impl ReceiptStore {
    pub fn open(root: &Path, window: u64, validator: &Path) -> Result<Self> {
        if window == 0 || window > 31 * 86400 {
            return Err(Error::Invalid(
                "window seconds must be between 1 and 2678400",
            ));
        }
        private_dir(root)?;
        let lock = lock(&root.join("store.lock"))?;
        private_dir(&root.join("objects"))?;
        private_dir(&root.join("manifests"))?;
        let db = private_database(&root.join("receipts.sqlite3"))?;
        db.execute_batch(
            "PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS settings (window INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS machines (
                machine TEXT PRIMARY KEY, start INTEGER NOT NULL, previous TEXT);
            CREATE TABLE IF NOT EXISTS receipts (
                seq INTEGER PRIMARY KEY, machine TEXT NOT NULL, window INTEGER NOT NULL,
                request TEXT NOT NULL, entry TEXT NOT NULL, UNIQUE(machine, request));
            CREATE TABLE IF NOT EXISTS versions (
                machine TEXT NOT NULL, session TEXT NOT NULL, sha TEXT NOT NULL,
                PRIMARY KEY(machine, session));
            CREATE TABLE IF NOT EXISTS manifests (
                machine TEXT NOT NULL, start INTEGER NOT NULL, sha TEXT NOT NULL,
                bytes BLOB NOT NULL, materialized INTEGER NOT NULL DEFAULT 0,
                published INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(machine, start));",
        )?;
        let configured: Option<u64> = db
            .query_row("SELECT window FROM settings", [], |r| r.get(0))
            .optional()?;
        match configured {
            Some(value) if value != window => {
                return Err(Error::Invalid(
                    "receipt window size differs from saved state",
                ))
            }
            None => {
                db.execute("INSERT INTO settings VALUES(?1)", [window])?;
            }
            _ => {}
        }
        let schema: Value =
            serde_json::from_str(include_str!("../../../schema/v0/manifest.schema.json"))?;
        let entry_schema = jsonschema::options()
            .with_draft(jsonschema::Draft::Draft202012)
            .should_validate_formats(true)
            .build(&schema["properties"]["entries"]["items"])
            .map_err(|_| Error::Invalid("manifest entry schema could not be compiled"))?;
        let schema = jsonschema::options()
            .with_draft(jsonschema::Draft::Draft202012)
            .should_validate_formats(true)
            .build(&schema)
            .map_err(|_| Error::Invalid("manifest schema could not be compiled"))?;
        let mut store = Self {
            root: root.to_owned(),
            db,
            window: window as i64,
            validator: validator.to_owned(),
            schema,
            entry_schema,
            _lock: lock,
        };
        store.materialize()?;
        Ok(store)
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn heartbeat(&mut self, machine: &str, now: DateTime<Utc>) -> Result<()> {
        if !valid_machine(machine) {
            return Err(Error::Invalid("invalid machine ID"));
        }
        self.db.execute(
            "INSERT OR IGNORE INTO machines VALUES(?1,?2,NULL)",
            params![machine, boundary(now, self.window)],
        )?;
        self.rotate(now)
    }

    /// Close only completed windows. Empty windows retain the same chain semantics.
    pub fn rotate(&mut self, now: DateTime<Utc>) -> Result<()> {
        let end = boundary(now, self.window);
        let tx = self.db.transaction()?;
        let machines: Vec<(String, i64, Option<String>)> = tx
            .prepare("SELECT machine,start,previous FROM machines ORDER BY machine")?
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
            .collect::<std::result::Result<_, _>>()?;
        for (machine, mut start, mut previous) in machines {
            if start > end {
                return Err(Error::Invalid("receipt clock precedes the current window"));
            }
            while start < end {
                let entries: Vec<String> = tx
                    .prepare(
                        "SELECT entry FROM receipts WHERE machine=?1 AND window=?2 ORDER BY seq",
                    )?
                    .query_map(params![machine, start], |r| r.get(0))?
                    .collect::<std::result::Result<_, _>>()?;
                let entries: Vec<Value> = entries
                    .iter()
                    .map(|s| serde_json::from_str(s))
                    .collect::<std::result::Result<_, _>>()?;
                let manifest = json!({
                    "$schema":"https://agentsessionrecord.org/schema/v0/manifest.schema.json",
                    "collector":{"name":"asr-collect","version":env!("CARGO_PKG_VERSION")},
                    "machine":machine,
                    "window":{"start": timestamp(DateTime::from_timestamp(start,0).ok_or(Error::Invalid("window time is out of range"))?),
                        "end":timestamp(DateTime::from_timestamp(start+self.window,0).ok_or(Error::Invalid("window time is out of range"))?)},
                    "previousManifest":previous.as_ref().map(|sha| json!({"sha256":sha})),
                    "entries":entries
                });
                if !self.schema.is_valid(&manifest) {
                    return Err(Error::Invalid(
                        "generated manifest failed the repository schema",
                    ));
                }
                let mut bytes = serde_json::to_vec_pretty(&manifest)?;
                bytes.push(b'\n');
                let sha = digest(&bytes);
                tx.execute(
                    "INSERT INTO manifests(machine,start,sha,bytes) VALUES(?1,?2,?3,?4)",
                    params![machine, start, sha, bytes],
                )?;
                previous = Some(sha);
                start += self.window;
            }
            tx.execute(
                "UPDATE machines SET start=?2,previous=?3 WHERE machine=?1",
                params![machine, start, previous],
            )?;
        }
        tx.commit()?;
        self.materialize()
    }

    pub fn ingest(
        &mut self,
        machine: &str,
        uploader: &str,
        request: &str,
        source: &Path,
        expected: &str,
        now: DateTime<Utc>,
    ) -> Result<Receipt> {
        self.heartbeat(machine, now)?;
        if !valid_digest(expected)
            || uploader.is_empty()
            || request.is_empty()
            || request.len() > 128
        {
            return Err(Error::Invalid("invalid upload metadata"));
        }
        // Copy before hashing and validating so receipt facts refer to one immutable snapshot.
        let mut snapshot = tempfile::NamedTempFile::new_in(self.root.join("objects"))?;
        std::io::copy(&mut File::open(source)?, &mut snapshot)?;
        snapshot.flush()?;
        snapshot.as_file().sync_all()?;
        let (sha, length) = hash_file(snapshot.path())?;
        if let Some(receipt) = self.existing(machine, request)? {
            if receipt.sha256.as_deref() != Some(&sha)
                || receipt.uploader != uploader
                || receipt.status == "received" && expected != sha
            {
                return Err(Error::Invalid(
                    "upload ID was already used for different bytes or identity",
                ));
            }
            let dest = if receipt.status == "received" {
                object_path(&self.root, &sha)
            } else {
                object_path(&self.root, &sha).with_extension("bin")
            };
            retain_snapshot(snapshot, &dest, &sha, length)?;
            return Ok(receipt);
        }
        let valid = validate_file(&self.validator, snapshot.path())?;
        let mut input = asr_core::jsonl::Reader::new(
            BufReader::new(File::open(snapshot.path())?),
            16 * 1024 * 1024,
        );
        let header = match input
            .read()
            .map_err(|_| Error::Invalid("session header could not be read"))?
        {
            Some(asr_core::jsonl::Line::Record(v)) if v["type"] == "session" => Some(v),
            _ => None,
        };
        let facts = header.as_ref().and_then(|v| {
            Some((
                asr_core::identity::session_ref(
                    v["agent"]["name"].as_str()?,
                    v["namespace"].as_str(),
                    v["sessionId"].as_str()?,
                ),
                json!({"method":v["producer"]["method"].as_str()?}),
            ))
        });
        let readable = sha == expected && valid.errors == 0 && facts.is_some();
        let dest = if readable {
            object_path(&self.root, &sha)
        } else {
            object_path(&self.root, &sha).with_extension("bin")
        };
        retain_snapshot(snapshot, &dest, &sha, length)?;
        let identity_mismatch = header.as_ref().filter(|_| valid.errors == 0).and_then(|v| {
            v["user"]["id"]
                .as_str()
                .filter(|id| *id != uploader)
                .map(|_| {
                    json!({
                        "recordedUser":v["user"],"authenticatedUploader":uploader
                    })
                })
        });
        let (session, producer) = if valid.errors == 0 && facts.is_some() {
            let (session, producer) =
                facts.ok_or(Error::Invalid("validated header was not readable"))?;
            (Some(session), Some(producer))
        } else {
            (None, None)
        };
        let previous: Option<String> = if let Some(session) = &session {
            self.db
                .query_row(
                    "SELECT sha FROM versions WHERE machine=?1 AND session=?2",
                    params![machine, session],
                    |r| r.get(0),
                )
                .optional()?
        } else {
            None
        };
        let receipt = Receipt {
            session,
            sha256: Some(sha.clone()),
            byte_length: Some(length),
            received_at: timestamp(now),
            uploader: uploader.to_owned(),
            producer,
            replaces: previous.filter(|s| s != &sha).map(|s| json!({"sha256":s})),
            status: if readable { "received" } else { "unreadable" }.into(),
            identity_mismatch,
            reason: if sha != expected {
                Some("Uploaded bytes do not match the declared digest.".into())
            } else if !readable {
                Some("The uploaded file did not pass ASR validation.".into())
            } else {
                None
            },
        };
        self.record(machine, request, &receipt, now)?;
        Ok(receipt)
    }

    pub fn failure(
        &mut self,
        machine: &str,
        uploader: &str,
        request: &str,
        failure: Failure<'_>,
        now: DateTime<Utc>,
    ) -> Result<Receipt> {
        let Failure { reason, session } = failure;
        self.heartbeat(machine, now)?;
        if uploader.is_empty()
            || request.is_empty()
            || request.len() > 128
            || reason.is_empty()
            || reason.len() > 1024
        {
            return Err(Error::Invalid("invalid failure report"));
        }
        if let Some(receipt) = self.existing(machine, request)? {
            if receipt.status != "failed"
                || receipt.uploader != uploader
                || receipt.reason.as_deref() != Some(reason)
                || receipt.session.as_deref() != session
            {
                return Err(Error::Invalid("failure upload ID was reused"));
            }
            return Ok(receipt);
        }
        let receipt = Receipt {
            session: session.map(str::to_owned),
            sha256: None,
            byte_length: None,
            received_at: timestamp(now),
            uploader: uploader.into(),
            producer: None,
            replaces: None,
            status: "failed".into(),
            reason: Some(reason.into()),
            identity_mismatch: None,
        };
        self.record(machine, request, &receipt, now)?;
        Ok(receipt)
    }

    fn existing(&self, machine: &str, request: &str) -> Result<Option<Receipt>> {
        let entry: Option<String> = self
            .db
            .query_row(
                "SELECT entry FROM receipts WHERE machine=?1 AND request=?2",
                params![machine, request],
                |r| r.get(0),
            )
            .optional()?;
        Ok(entry.map(|s| serde_json::from_str(&s)).transpose()?)
    }

    fn record(
        &mut self,
        machine: &str,
        request: &str,
        receipt: &Receipt,
        now: DateTime<Utc>,
    ) -> Result<()> {
        if !self.entry_schema.is_valid(&serde_json::to_value(receipt)?) {
            return Err(Error::Invalid("invalid receipt fields"));
        }
        let tx = self.db.transaction()?;
        tx.execute(
            "INSERT INTO receipts(machine,window,request,entry) VALUES(?1,?2,?3,?4)",
            params![
                machine,
                boundary(now, self.window),
                request,
                serde_json::to_string(receipt)?
            ],
        )?;
        if let ("received", Some(session), Some(sha)) =
            (receipt.status.as_str(), &receipt.session, &receipt.sha256)
        {
            tx.execute("INSERT INTO versions VALUES(?1,?2,?3) ON CONFLICT(machine,session) DO UPDATE SET sha=excluded.sha",
                params![machine,session,sha])?;
        }
        tx.commit()?;
        Ok(())
    }

    fn key(machine: &str, start: i64) -> String {
        format!(
            "manifests/{}/{start}.manifest.json",
            digest(machine.as_bytes())
        )
    }

    fn materialize(&mut self) -> Result<()> {
        let files: Vec<(String, i64, Vec<u8>)> = self
            .db
            .prepare(
                "SELECT machine,start,bytes FROM manifests WHERE materialized=0 ORDER BY start",
            )?
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?
            .collect::<std::result::Result<_, _>>()?;
        for (machine, start, bytes) in files {
            immutable_write(&self.root.join(Self::key(&machine, start)), &bytes)?;
            self.db.execute(
                "UPDATE manifests SET materialized=1 WHERE machine=?1 AND start=?2",
                params![machine, start],
            )?;
        }
        Ok(())
    }

    pub fn unpublished(&self) -> Result<Vec<ManifestFile>> {
        Ok(self.db.prepare("SELECT machine,start,sha,bytes FROM manifests WHERE published=0 ORDER BY machine,start")?
            .query_map([],|r| {
                let machine: String = r.get(0)?;
                Ok(ManifestFile {key:Self::key(&machine,r.get(1)?),sha256:r.get(2)?,bytes:r.get(3)?})
            })?.collect::<std::result::Result<_,_>>()?)
    }

    pub fn mark_published(&self, sha256: &str) -> Result<()> {
        self.db
            .execute("UPDATE manifests SET published=1 WHERE sha=?1", [sha256])?;
        Ok(())
    }
}

fn retain_snapshot(
    snapshot: tempfile::NamedTempFile,
    dest: &Path,
    sha: &str,
    length: u64,
) -> Result<()> {
    if dest.exists() {
        if hash_file(dest)? != (sha.to_owned(), length) {
            return Err(Error::Invalid("stored session digest mismatch"));
        }
    } else {
        snapshot.persist_noclobber(dest).map_err(|e| e.error)?;
        #[cfg(unix)]
        File::open(
            dest.parent()
                .ok_or(Error::Invalid("object has no parent"))?,
        )?
        .sync_all()?;
    }
    Ok(())
}
