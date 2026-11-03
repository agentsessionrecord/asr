use crate::{Error, Result};
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::{json, Value};
use std::path::Path;

pub(crate) const APPROVAL_LOOKUP: &str = "SELECT fold,value,pos FROM projected \
    WHERE fold>=?1 AND fold<?2 AND fold>?3 ORDER BY fold LIMIT 1";

pub(crate) struct Spool {
    pub db: Connection,
    _dir: tempfile::TempDir,
    pub limit: usize,
    pub has_secrets: bool,
    pub secret_bytes: std::cell::Cell<usize>,
    pub secret_matcher: std::cell::RefCell<Option<crate::privacy::Matcher>>,
}
impl Spool {
    pub fn new(out: &Path, limit: usize) -> Result<Self> {
        let dir = tempfile::Builder::new()
            .prefix(".asr-stage-")
            .tempdir_in(out)?;
        let db = Connection::open(dir.path().join("index.sqlite"))?;
        db.execute_batch("PRAGMA journal_mode=DELETE; PRAGMA synchronous=OFF; PRAGMA cache_size=-4096; PRAGMA temp_store=FILE;
            CREATE TABLE sessions(id TEXT PRIMARY KEY,header TEXT);
            CREATE TABLE failed_sessions(id TEXT PRIMARY KEY);
            CREATE TABLE sources(path TEXT PRIMARY KEY);
            CREATE TABLE native(pos INTEGER PRIMARY KEY,session TEXT,value TEXT,identity TEXT);
            CREATE INDEX native_order ON native(session,pos);
            CREATE UNIQUE INDEX native_identity ON native(session,identity) WHERE identity IS NOT NULL;
            CREATE TABLE projected(pos INTEGER,slot INTEGER,fold TEXT UNIQUE,value TEXT,PRIMARY KEY(pos,slot));
            CREATE INDEX projected_ids ON projected(json_extract(value,'$.id'));
            CREATE TABLE entities(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE reserved(kind TEXT,key TEXT,PRIMARY KEY(kind,key));
            CREATE TABLE secret_questions(id TEXT PRIMARY KEY);
            ATTACH DATABASE ':memory:' AS privacy;
            CREATE TABLE privacy.secrets(value TEXT PRIMARY KEY);
            BEGIN;")?;
        Ok(Self {
            db,
            _dir: dir,
            limit,
            has_secrets: false,
            secret_bytes: std::cell::Cell::new(0),
            secret_matcher: std::cell::RefCell::new(None),
        })
    }
    pub fn session(&self, id: &str, header: &Value) -> Result<()> {
        self.db
            .prepare_cached("INSERT OR IGNORE INTO sessions VALUES(?1,?2)")?
            .execute(params![id, header.to_string()])?;
        Ok(())
    }
    pub fn push(&self, session: &str, value: &Value, identity: Option<&str>) -> Result<()> {
        if let Some(identity) = identity {
            self.db
                .prepare_cached("DELETE FROM native WHERE session=?1 AND identity=?2")?
                .execute(params![session, identity])?;
        }
        self.db
            .prepare_cached("INSERT INTO native(session,value,identity) VALUES(?1,?2,?3)")?
            .execute(params![session, value.to_string(), identity])?;
        Ok(())
    }
    pub fn next_session(&self, after: &str) -> Result<Option<(String, Value)>> {
        let row: Option<(String, String)> = self
            .db
            .query_row(
                "SELECT id,header FROM sessions WHERE id>?1 AND id NOT IN (SELECT id FROM failed_sessions) ORDER BY id LIMIT 1",
                [after],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        row.map(|(id, raw)| Ok((id, serde_json::from_str(&raw)?)))
            .transpose()
    }
    pub fn next_native(&self, session: &str, after: u64) -> Result<Option<(u64, Value)>> {
        let row: Option<(u64, String)> = self
            .db
            .query_row(
                "SELECT pos,value FROM native WHERE session=?1 AND pos>?2 ORDER BY pos LIMIT 1",
                params![session, after],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        row.map(|(pos, raw)| Ok((pos, serde_json::from_str(&raw)?)))
            .transpose()
    }
    pub fn for_each_native(
        &self,
        session: &str,
        mut visit: impl FnMut(u64, Value) -> Result<()>,
    ) -> Result<()> {
        let mut statement = self
            .db
            .prepare("SELECT pos,value FROM native WHERE session=?1 ORDER BY pos")?;
        let mut rows = statement.query([session])?;
        while let Some(row) = rows.next()? {
            let raw = row.get_ref(1)?.as_str().map_err(rusqlite::Error::from)?;
            visit(row.get(0)?, serde_json::from_str(raw)?)?;
        }
        Ok(())
    }
    pub fn begin_session(&self, _session: &str) -> Result<()> {
        self.db
            .execute_batch("DELETE FROM projected; DELETE FROM entities; DELETE FROM reserved;")?;
        Ok(())
    }
    pub fn entity(&self, key: &str) -> Result<Option<Value>> {
        let raw: Option<String> = self
            .db
            .prepare_cached("SELECT value FROM entities WHERE key=?1")?
            .query_row([key], |r| r.get(0))
            .optional()?;
        raw.map(|raw| Ok(serde_json::from_str(&raw)?)).transpose()
    }
    pub fn save(&self, key: &str, value: &Value) -> Result<()> {
        self.db
            .prepare_cached("INSERT OR REPLACE INTO entities VALUES(?1,?2)")?
            .execute(params![key, value.to_string()])?;
        Ok(())
    }
    pub fn emit(&self, pos: u64, slot: u64, mut value: Value, fold: Option<&str>) -> Result<()> {
        if let Some(key) = fold {
            let old: Option<String> = self
                .db
                .prepare_cached("SELECT value FROM projected WHERE fold=?1")?
                .query_row([key], |r| r.get(0))
                .optional()?;
            if let Some(old) = old {
                let mut previous: Value = serde_json::from_str(&old)?;
                asr_core::ordering::fold_completed(&mut previous, &value);
                value = previous;
                self.db
                    .prepare_cached("DELETE FROM projected WHERE fold=?1")?
                    .execute([key])?;
            }
        }
        let raw = value.to_string();
        if raw.len() > self.limit {
            return Err(Error::Invalid("assembled record exceeded limit".into()));
        }
        self.db
            .prepare_cached("INSERT INTO projected VALUES(?1,?2,?3,?4)")?
            .execute(params![pos, slot, fold, raw])?;
        Ok(())
    }
    pub fn for_each_record(
        &self,
        mut visit: impl FnMut(u64, u64, Value) -> Result<()>,
    ) -> Result<()> {
        let mut statement = self
            .db
            .prepare("SELECT pos,slot,value FROM projected ORDER BY pos,slot")?;
        let mut rows = statement.query([])?;
        while let Some(row) = rows.next()? {
            let raw = row.get_ref(2)?.as_str().map_err(rusqlite::Error::from)?;
            visit(row.get(0)?, row.get(1)?, serde_json::from_str(raw)?)?;
        }
        Ok(())
    }
    pub fn reserve(&self, kind: &str, key: &str) -> Result<bool> {
        Ok(self
            .db
            .prepare_cached("INSERT OR IGNORE INTO reserved VALUES(?1,?2)")?
            .execute(params![kind, key])?
            == 1)
    }
}
pub(crate) struct DiskIds<'a>(pub &'a Spool);
impl asr_core::writer::IdentityStore for DiskIds<'_> {
    fn reserve(&mut self, kind: &str, key: &str) -> asr_core::Result<bool> {
        self.0
            .reserve(kind, key)
            .map_err(|_| asr_core::Error::Invalid("identity staging failed".into()))
    }
}

pub(crate) fn gap(reason: &str) -> Value {
    json!({"type":"gap","reason":reason,"count":1})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn approval_prefix_range_matches_scan_with_bounded_work() {
        let temp = tempfile::tempdir().unwrap();
        let spool = Spool::new(temp.path(), 1024).unwrap();
        for pos in 1..=8192 {
            spool
                .db
                .execute(
                    "INSERT INTO projected VALUES(?1,0,?2,?3)",
                    params![pos, format!("result:{pos}"), format!(r#"{{"id":"{pos}"}}"#)],
                )
                .unwrap();
        }
        for (offset, call) in ["run", "run:child", "run;child", "雪:%_", "", "a\0b"]
            .iter()
            .enumerate()
        {
            for suffix in ["first", "second", "雪"] {
                spool
                    .emit(
                        9000 + offset as u64,
                        suffix.len() as u64,
                        json!({"id":format!("{offset}:{suffix}")}),
                        Some(&format!("approval:{call}:{suffix}")),
                    )
                    .unwrap();
            }
        }
        for call in [
            "run",
            "run:child",
            "run;child",
            "雪:%_",
            "",
            "a\0b",
            "absent",
        ] {
            let prefix = format!("approval:{call}:");
            let end = format!("approval:{call};");
            let mut old = spool.db.prepare(
                "SELECT fold,value,pos FROM projected WHERE substr(fold,1,length(?1))=?1 AND fold>?2 ORDER BY fold LIMIT 1"
            ).unwrap();
            let mut indexed = spool.db.prepare(APPROVAL_LOOKUP).unwrap();
            let mut cursor = String::new();
            loop {
                let read = |r: &rusqlite::Row<'_>| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, u64>(2)?,
                    ))
                };
                let expected = old
                    .query_row(params![prefix, cursor], read)
                    .optional()
                    .unwrap();
                let actual = if call.contains('\0') {
                    None
                } else {
                    indexed
                        .query_row(
                            params![prefix.as_str().max(cursor.as_str()), end, cursor],
                            read,
                        )
                        .optional()
                        .unwrap()
                };
                assert_eq!(actual, expected);
                let Some((fold, _, _)) = actual else { break };
                cursor = fold;
            }
            let before = old.get_status(rusqlite::StatementStatus::VmStep);
            let after = indexed.get_status(rusqlite::StatementStatus::VmStep);
            assert!(after < 256, "approval lookup took {after} VM steps");
            assert!(before > 8192, "scan fixture must exercise the slow path");
            eprintln!("approval lookup {call:?}: scan={before}, indexed={after} VM steps");
        }
    }
}
