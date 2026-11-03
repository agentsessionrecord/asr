//! Exact number tokens and duplicate-key checks apply at every nesting depth.
use crate::Result;
use serde::{de::MapAccess, Deserialize};
use serde_json::{value::RawValue, Value};
use std::{collections::BTreeMap, io::BufRead};

pub fn decode(raw: &str) -> serde_json::Result<Value> {
    let raw: &RawValue = serde_json::from_str(raw)?;
    exact(raw.get())
}
fn exact(raw: &str) -> serde_json::Result<Value> {
    if raw.starts_with('{') {
        let fields = serde_json::from_str::<Unique>(raw)?.0;
        fields
            .into_iter()
            .map(|(k, v)| Ok((k, exact(v.get())?)))
            .collect()
    } else if raw.starts_with('[') {
        let items: Vec<&RawValue> = serde_json::from_str(raw)?;
        Ok(Value::Array(
            items
                .into_iter()
                .map(|v| exact(v.get()))
                .collect::<serde_json::Result<_>>()?,
        ))
    } else {
        serde_json::from_str(raw)
    }
}
struct Unique<'a>(BTreeMap<String, &'a RawValue>);
impl<'de> Deserialize<'de> for Unique<'de> {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct Visitor;
        impl<'de> serde::de::Visitor<'de> for Visitor {
            type Value = Unique<'de>;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("unique JSON object keys")
            }
            fn visit_map<A: MapAccess<'de>>(
                self,
                mut map: A,
            ) -> std::result::Result<Self::Value, A::Error> {
                let mut fields = BTreeMap::new();
                while let Some((k, v)) = map.next_entry::<String, &RawValue>()? {
                    if fields.insert(k, v).is_some() {
                        return Err(serde::de::Error::custom("duplicate JSON key"));
                    }
                }
                Ok(Unique(fields))
            }
        }
        d.deserialize_map(Visitor)
    }
}

#[derive(Debug)]
pub enum Line {
    Record(Value),
    Malformed,
    Oversized,
    Incomplete,
}
pub struct Reader<R> {
    inner: R,
    buffer: Vec<u8>,
    limit: usize,
    pub line: u64,
    pub bytes: u64,
}
impl<R: BufRead> Reader<R> {
    pub fn new(inner: R, limit: usize) -> Self {
        Self {
            inner,
            buffer: Vec::new(),
            limit,
            line: 0,
            bytes: 0,
        }
    }
    /// Over-bound records are drained, and non-empty tails wait for a later read.
    pub fn read(&mut self) -> Result<Option<Line>> {
        self.buffer.clear();
        let mut total = 0usize;
        loop {
            let available = self.inner.fill_buf()?;
            if available.is_empty() {
                if total == 0 {
                    return Ok(None);
                }
                self.line += 1;
                return Ok(Some(Line::Incomplete));
            }
            let end = available.iter().position(|b| *b == b'\n');
            let n = end.map_or(available.len(), |i| i + 1);
            total = total.saturating_add(n);
            self.bytes += n as u64;
            let take = n.min(self.limit.saturating_sub(self.buffer.len()));
            self.buffer.extend_from_slice(&available[..take]);
            self.inner.consume(n);
            if end.is_some() {
                break;
            }
        }
        self.line += 1;
        if total > self.limit {
            return Ok(Some(Line::Oversized));
        }
        Ok(Some(
            match std::str::from_utf8(&self.buffer)
                .ok()
                .and_then(|s| decode(s).ok())
                .filter(Value::is_object)
            {
                Some(value) => Line::Record(value),
                None => Line::Malformed,
            },
        ))
    }
}

/// Native integers beyond interoperable JSON precision use their exact token as text.
/// ASR readers use `decode` directly and never apply this native-value conversion.
pub fn stringify_large_native(value: &mut Value) -> bool {
    let mut changed = false;
    match value {
        Value::Number(n) => {
            if n.as_f64().is_none_or(|n| n.abs() > 9_007_199_254_740_991.0) {
                *value = Value::String(n.to_string());
                changed = true;
            }
        }
        Value::Array(a) => {
            for v in a {
                changed |= stringify_large_native(v);
            }
        }
        Value::Object(o) => {
            for v in o.values_mut() {
                changed |= stringify_large_native(v);
            }
        }
        _ => {}
    }
    changed
}
