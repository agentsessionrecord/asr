use crate::{identity::valid_id, state::SessionState, Error, Record, Result};
use serde::Serialize;
use std::{collections::BTreeSet, io::Write};

/// A disk implementation lets a long-running converter bound identity memory.
pub trait IdentityStore {
    fn reserve(&mut self, kind: &str, key: &str) -> Result<bool>;
}
#[derive(Default)]
pub struct MemoryStore(BTreeSet<(String, String)>);
impl IdentityStore for MemoryStore {
    fn reserve(&mut self, kind: &str, key: &str) -> Result<bool> {
        Ok(self.0.insert((kind.into(), key.into())))
    }
}
pub struct Writer<W, S = MemoryStore> {
    out: W,
    ids: S,
    pub state: SessionState,
    pub records: u64,
}
impl<W: Write> Writer<W, MemoryStore> {
    pub fn new(out: W, header: &impl Serialize) -> Result<Self> {
        Self::with_store(out, header, MemoryStore::default())
    }
}
impl<W: Write, S: IdentityStore> Writer<W, S> {
    pub fn with_store(out: W, header: &impl Serialize, ids: S) -> Result<Self> {
        let mut writer = Self {
            out,
            ids,
            state: SessionState::default(),
            records: 0,
        };
        writer.append(header)?;
        Ok(writer)
    }
    pub fn append(&mut self, record: &impl Serialize) -> Result<()> {
        let value = serde_json::to_value(record)?;
        let kind = value["type"]
            .as_str()
            .ok_or_else(|| Error::Invalid("record requires type".into()))?;
        if (self.records == 0) != (kind == "session") {
            return Err(Error::Invalid("one session header must be first".into()));
        }
        if kind == "session" && value["formatVersion"] != "0.1" {
            return Err(Error::Invalid("unsupported formatVersion".into()));
        }
        // Field shapes and required fields come from the current schema.
        Record::from_value(value.clone())?;
        for (a, b) in [("input", "inputText"), ("patch", "edits")] {
            if value.get(a).is_some() && value.get(b).is_some() {
                return Err(Error::Invalid(format!("exclusive fields {a} and {b}")));
            }
        }
        if kind == "session_info"
            && ![
                "title",
                "endedAt",
                "repos",
                "usage",
                "cost",
                "agentSettings",
                "tools",
                "missing",
            ]
            .iter()
            .any(|k| value.get(*k).is_some())
        {
            return Err(Error::Invalid("empty session_info".into()));
        }
        if kind == "inference"
            && value.get("model").is_none()
            && !self.state.missing.contains("model")
        {
            return Err(Error::Invalid(
                "inference without model requires a declared model loss".into(),
            ));
        }
        let id = value["id"]
            .as_str()
            .filter(|id| valid_id(id))
            .ok_or_else(|| Error::Invalid("invalid record ID".into()))?;
        let mut bytes = serde_json::to_vec(&value)?;
        bytes.push(b'\n');
        if !self.ids.reserve("id", id)? {
            return Err(Error::Invalid("duplicate record ID".into()));
        }
        if kind == "tool_result" {
            if let Some(call) = value["callId"].as_str() {
                if !self.ids.reserve("result", call)? {
                    return Err(Error::Invalid("duplicate tool result".into()));
                }
            }
        }
        self.out.write_all(&bytes)?;
        self.state.apply(&value);
        self.records += 1;
        Ok(())
    }
    pub fn flush(&mut self) -> Result<()> {
        self.out.flush()?;
        Ok(())
    }
    pub fn into_inner(mut self) -> Result<W> {
        self.flush()?;
        Ok(self.out)
    }
}
