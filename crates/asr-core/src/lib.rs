//! Record fields, lossless JSONL reading, append-only writing, and stream helpers.
pub mod identity;
pub mod jsonl;
pub mod ordering;
pub mod state;
pub mod types;
pub mod writer;

use serde::Deserialize;
pub use types::Record;
pub use writer::Writer;

/// An optional supplied null is different from an absent JSON field.
pub fn present<'de, D, T>(deserializer: D) -> std::result::Result<Option<T>, D::Error>
where
    D: serde::Deserializer<'de>,
    T: Deserialize<'de>,
{
    T::deserialize(deserializer).map(Some)
}

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("I/O: {0}")]
    Io(#[from] std::io::Error),
    #[error("JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("{0}")]
    Invalid(String),
}
pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
#[serde(untagged)]
pub enum Nullable<T> {
    Null,
    Value(T),
}
