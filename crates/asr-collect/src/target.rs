use crate::{util::*, Error, Failure, Receipt, ReceiptStore, Result};
use chrono::Utc;
use object_store::{
    path::Path as ObjectPath, Attribute, Attributes, ObjectStore, PutMultipartOptions,
};
use reqwest::{
    blocking::{Client, RequestBuilder},
    Url,
};
use std::{
    fs::File,
    io::{Read, Write},
    path::Path,
    sync::Arc,
    time::Duration,
};

pub enum Target {
    Local {
        store: ReceiptStore,
        uploader: String,
    },
    Cloud {
        store: ReceiptStore,
        uploader: String,
        remote: Arc<dyn ObjectStore>,
        prefix: ObjectPath,
        runtime: tokio::runtime::Runtime,
    },
    Http {
        base: Url,
        client: Client,
        token: String,
    },
}

impl Target {
    pub fn open(
        value: &str,
        state: &Path,
        uploader: Option<&str>,
        token_file: Option<&Path>,
        window: u64,
        validator: &Path,
    ) -> Result<Self> {
        if !value.contains("://") {
            let uploader = configured_uploader(uploader)?;
            return Ok(Self::Local {
                store: ReceiptStore::open(Path::new(value), window, validator)?,
                uploader,
            });
        }
        let url = Url::parse(value).map_err(|_| Error::Invalid("invalid target URL"))?;
        if !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
        {
            return Err(Error::Invalid(
                "target URLs cannot contain credentials, queries or fragments",
            ));
        }
        if url.scheme() == "file" {
            let path = url
                .to_file_path()
                .map_err(|_| Error::Invalid("invalid local file URL"))?;
            return Ok(Self::Local {
                store: ReceiptStore::open(&path, window, validator)?,
                uploader: configured_uploader(uploader)?,
            });
        }
        if matches!(url.scheme(), "http" | "https") {
            if url.scheme() == "http"
                && !matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "[::1]"))
            {
                return Err(Error::Invalid("remote receivers require HTTPS"));
            }
            let bytes = private_file(
                token_file.ok_or(Error::Invalid("HTTP targets require --token-file"))?,
            )?;
            let token = std::str::from_utf8(&bytes)
                .map_err(|_| Error::Invalid("invalid token file"))?
                .trim()
                .to_owned();
            if token.is_empty() || !token.bytes().all(|c| c.is_ascii_graphic()) {
                return Err(Error::Invalid("invalid bearer token"));
            }
            let client = Client::builder()
                .timeout(Duration::from_secs(120))
                .redirect(reqwest::redirect::Policy::none())
                .no_proxy()
                .build()?;
            return Ok(Self::Http {
                base: url,
                client,
                token,
            });
        }
        let bucket = url
            .host_str()
            .ok_or(Error::Invalid("object target needs a bucket or container"))?;
        let remote: Arc<dyn ObjectStore> = match url.scheme() {
            "s3" => Arc::new(
                object_store::aws::AmazonS3Builder::from_env()
                    .with_bucket_name(bucket)
                    .build()?,
            ),
            "gs" | "gcs" => Arc::new(
                object_store::gcp::GoogleCloudStorageBuilder::from_env()
                    .with_bucket_name(bucket)
                    .build()?,
            ),
            "az" | "azure" => Arc::new(
                object_store::azure::MicrosoftAzureBuilder::from_env()
                    .with_container_name(bucket)
                    .build()?,
            ),
            _ => return Err(Error::Invalid("unsupported collection target scheme")),
        };
        let prefix = ObjectPath::parse(url.path().trim_matches('/'))
            .map_err(|_| Error::Invalid("invalid object prefix"))?;
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(1)
            .enable_all()
            .build()?;
        Ok(Self::Cloud {
            store: ReceiptStore::open(&state.join("receipts"), window, validator)?,
            uploader: configured_uploader(uploader)?,
            remote,
            prefix,
            runtime,
        })
    }

    fn request(
        base: &Url,
        client: &Client,
        token: &str,
        machine: &str,
        route: &str,
    ) -> Result<RequestBuilder> {
        let mut url = base.clone();
        url.set_path(&format!("{}/v1/{route}", base.path().trim_end_matches('/')));
        Ok(client
            .post(url)
            .bearer_auth(token)
            .header("X-ASR-Machine", machine))
    }

    pub fn heartbeat(&mut self, machine: &str) -> Result<()> {
        match self {
            Self::Local { store, .. } | Self::Cloud { store, .. } => {
                store.heartbeat(machine, Utc::now())?
            }
            Self::Http {
                base,
                client,
                token,
            } => {
                Self::request(base, client, token, machine, "heartbeat")?
                    .send()?
                    .error_for_status()?;
            }
        }
        self.flush()
    }

    pub fn send(&mut self, machine: &str, request: &str, path: &Path) -> Result<Receipt> {
        let (sha, length) = hash_file(path)?;
        let receipt = match self {
            Self::Local { store, uploader } => {
                store.ingest(machine, uploader, request, path, &sha, Utc::now())?
            }
            Self::Cloud {
                store,
                uploader,
                remote,
                prefix,
                runtime,
            } => {
                let key = prefix.child("objects").child(format!("{sha}.jsonl"));
                upload_file(runtime, remote.as_ref(), &key, path, &sha)?;
                let receipt = store.ingest(machine, uploader, request, path, &sha, Utc::now())?;
                // The remote store owns the bytes. Local retry state retains only receipts.
                std::fs::remove_file(object_path(store.root(), &sha))?;
                receipt
            }
            Self::Http {
                base,
                client,
                token,
            } => {
                let response = Self::request(base, client, token, machine, "sessions")?
                    .header("X-ASR-Upload-ID", request)
                    .header("X-ASR-Sha256", &sha)
                    .header("Content-Type", "application/vnd.agent-session+jsonl")
                    .header("Content-Length", length)
                    .body(File::open(path)?)
                    .send()?
                    .error_for_status()?;
                let receipt: Receipt = serde_json::from_reader(response.take(64 * 1024))?;
                if receipt.sha256.as_deref() != Some(&sha) || receipt.byte_length != Some(length) {
                    return Err(Error::Invalid(
                        "receiver receipt does not identify the uploaded bytes",
                    ));
                }
                receipt
            }
        };
        if receipt.status != "received" {
            return Err(Error::Invalid(
                "receiver could not read the uploaded session",
            ));
        }
        self.flush()?;
        Ok(receipt)
    }

    pub fn failure(&mut self, machine: &str, request: &str, failure: Failure<'_>) -> Result<()> {
        match self {
            Self::Local { store, uploader }
            | Self::Cloud {
                store, uploader, ..
            } => {
                store.failure(machine, uploader, request, failure, Utc::now())?;
            }
            Self::Http {
                base,
                client,
                token,
            } => {
                Self::request(base, client, token, machine, "failures")?
                    .header("X-ASR-Upload-ID", request)
                    .json(&serde_json::json!({"reason":failure.reason,"session":failure.session}))
                    .send()?
                    .error_for_status()?;
            }
        }
        self.flush()
    }

    pub fn flush(&mut self) -> Result<()> {
        match self {
            Self::Local { store, .. } => store.rotate(Utc::now())?,
            Self::Cloud {
                store,
                remote,
                prefix,
                runtime,
                ..
            } => {
                store.rotate(Utc::now())?;
                for manifest in store.unpublished()? {
                    let mut file = tempfile::NamedTempFile::new_in(store.root())?;
                    file.write_all(&manifest.bytes)?;
                    let key = ObjectPath::parse(
                        format!("{prefix}/{}", manifest.key).trim_start_matches('/'),
                    )
                    .map_err(|_| Error::Invalid("invalid manifest object key"))?;
                    upload_file(
                        runtime,
                        remote.as_ref(),
                        &key,
                        file.path(),
                        &manifest.sha256,
                    )?;
                    store.mark_published(&manifest.sha256)?;
                }
            }
            Self::Http { .. } => {}
        }
        Ok(())
    }
}

fn configured_uploader(value: Option<&str>) -> Result<String> {
    value
        .filter(|s| !s.is_empty())
        .map(str::to_owned)
        .ok_or(Error::Invalid("direct storage targets require --uploader"))
}

/// Multipart upload keeps memory bounded independently of session size.
fn upload_file(
    runtime: &tokio::runtime::Runtime,
    store: &dyn ObjectStore,
    key: &ObjectPath,
    path: &Path,
    sha: &str,
) -> Result<()> {
    runtime.block_on(async {
        let mut attributes = Attributes::new();
        attributes.insert(Attribute::Metadata("sha256".into()), sha.to_owned().into());
        let options = PutMultipartOptions {
            attributes,
            ..Default::default()
        };
        let mut upload = store.put_multipart_opts(key, options).await?;
        let result: Result<()> = async {
            let mut input = File::open(path)?;
            loop {
                let mut chunk = Vec::with_capacity(8 * 1024 * 1024);
                std::io::copy(
                    &mut Read::by_ref(&mut input).take(8 * 1024 * 1024),
                    &mut chunk,
                )?;
                if chunk.is_empty() {
                    break;
                }
                upload.put_part(chunk.into()).await?;
            }
            upload.complete().await?;
            Ok(())
        }
        .await;
        if result.is_err() {
            let _ = upload.abort().await;
        }
        result
    })
}
