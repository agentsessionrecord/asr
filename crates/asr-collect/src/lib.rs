//! Local collection and exact-byte receipt storage. Recorded content is never executed.
mod args;
mod collector;
mod discovery;
mod receiver;
mod store;
mod target;
mod util;

pub use args::{CollectArgs, ReceiveArgs};
pub use collector::{collect, CollectionSummary};
pub use receiver::{AuthEntry, Receiver};
pub use store::{Failure, Receipt, ReceiptStore};
pub use target::Target;
pub use util::{hash_file, validate_file, Validation};

use std::path::Path;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("local file I/O failed")]
    Io(#[from] std::io::Error),
    #[error("local state or configuration JSON is invalid")]
    Json(#[from] serde_json::Error),
    #[error("receipt database failed")]
    Sql(#[from] rusqlite::Error),
    #[error("native conversion failed")]
    Convert(#[from] asr_convert::Error),
    #[error("HTTP transfer failed")]
    Http(#[from] reqwest::Error),
    #[error("object storage operation failed")]
    Object(#[from] object_store::Error),
    #[error("{0}")]
    Invalid(&'static str),
}
pub type Result<T> = std::result::Result<T, Error>;

pub fn receive(args: ReceiveArgs, validator: &Path) -> Result<()> {
    let mut receiver = Receiver::bind(args, validator.to_owned())?;
    receiver.run()
}
