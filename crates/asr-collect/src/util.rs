use crate::{Error, Result};
use fs2::FileExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

pub fn private_dir(path: &Path) -> Result<()> {
    // Check ancestors before creation or chmod so an existing symlink cannot
    // redirect private storage or change permissions on an unrelated directory.
    for ancestor in path.ancestors().filter(|p| !p.as_os_str().is_empty()) {
        match fs::symlink_metadata(ancestor) {
            Ok(meta) if !meta.is_dir() || meta.file_type().is_symlink() => {
                return Err(Error::Invalid(
                    "storage directories cannot contain symlinks",
                ));
            }
            Ok(_) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
    }
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        if fs::symlink_metadata(path)?.uid() != unsafe { libc::geteuid() } {
            return Err(Error::Invalid("storage directory must belong to this user"));
        }
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

pub struct FileLock(File);

impl Drop for FileLock {
    fn drop(&mut self) {
        // Release explicitly even when a concurrent spawn briefly inherits the descriptor.
        let _ = FileExt::unlock(&self.0);
    }
}

pub fn lock(path: &Path) -> Result<FileLock> {
    let mut options = OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let file = options.open(path)?;
    check_private_file(&file)?;
    file.try_lock_exclusive()
        .map_err(|_| Error::Invalid("another process owns this state or receipt store"))?;
    Ok(FileLock(file))
}

pub fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path
        .parent()
        .ok_or(Error::Invalid("output needs a parent directory"))?;
    private_dir(parent)?;
    let mut temp = tempfile::NamedTempFile::new_in(parent)?;
    temp.write_all(bytes)?;
    temp.as_file().sync_all()?;
    temp.persist(path).map_err(|e| e.error)?;
    #[cfg(unix)]
    File::open(parent)?.sync_all()?;
    Ok(())
}

pub fn immutable_write(path: &Path, bytes: &[u8]) -> Result<()> {
    if path.exists() {
        if private_file_limit(path, 64 * 1024 * 1024)? != bytes {
            return Err(Error::Invalid("immutable receipt object has changed"));
        }
        return Ok(());
    }
    atomic_write(path, bytes)
}

pub fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

pub fn hash_file(path: &Path) -> Result<(String, u64)> {
    let mut input = File::open(path)?;
    let mut hash = Sha256::new();
    let mut bytes = 0;
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let n = input.read(&mut buffer)?;
        if n == 0 {
            break;
        }
        hash.update(&buffer[..n]);
        bytes += n as u64;
    }
    Ok((format!("{:x}", hash.finalize()), bytes))
}

pub fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}

pub fn valid_machine(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c))
}

pub fn private_file(path: &Path) -> Result<Vec<u8>> {
    private_file_limit(path, 1024 * 1024)
}

pub fn private_file_limit(path: &Path, limit: u64) -> Result<Vec<u8>> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    let file = options.open(path)?;
    check_private_file(&file)?;
    if file.metadata()?.len() > limit {
        return Err(Error::Invalid("private file exceeds byte limit"));
    }
    let mut bytes = Vec::new();
    file.take(limit.saturating_add(1)).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > limit {
        return Err(Error::Invalid("private file exceeds byte limit"));
    }
    Ok(bytes)
}

fn check_private_file(file: &File) -> Result<()> {
    let metadata = file.metadata()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::{MetadataExt, PermissionsExt};
        if metadata.permissions().mode() & 0o077 != 0
            || metadata.uid() != unsafe { libc::geteuid() }
            || metadata.nlink() != 1
        {
            return Err(Error::Invalid(
                "private file needs one link, this owner and owner-only permissions",
            ));
        }
    }
    if !metadata.is_file() {
        return Err(Error::Invalid("private file must be regular"));
    }
    Ok(())
}

pub fn private_database(path: &Path) -> Result<rusqlite::Connection> {
    let mut options = OpenOptions::new();
    options.write(true).create(true).truncate(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    check_private_file(&options.open(path)?)?;
    Ok(rusqlite::Connection::open_with_flags(
        path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE | rusqlite::OpenFlags::SQLITE_OPEN_NOFOLLOW,
    )?)
}

#[derive(Debug, Default, Clone, Deserialize, Serialize)]
pub struct Validation {
    pub errors: u64,
    pub warnings: u64,
    #[serde(default)]
    pub counts: BTreeMap<String, u64>,
}

pub fn validate_file(validator: &Path, path: &Path) -> Result<Validation> {
    let output = Command::new("node")
        .arg(validator)
        .args(["--json", "--summary"])
        .arg(path)
        .stdin(Stdio::null())
        .output()?;
    let value: Validation = serde_json::from_slice(&output.stdout)
        .map_err(|_| Error::Invalid("validator did not return a structured summary"))?;
    if !output.status.success() && value.errors == 0 {
        return Err(Error::Invalid("validator could not read the file"));
    }
    Ok(value)
}

pub fn object_path(root: &Path, sha256: &str) -> PathBuf {
    root.join("objects").join(format!("{sha256}.jsonl"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn owner_release_does_not_wait_for_an_inherited_descriptor() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("owner.lock");
        let owner = lock(&path).unwrap();
        let inherited = owner.0.try_clone().unwrap();
        assert!(lock(&path).is_err());
        drop(owner);
        let next = lock(&path).unwrap();
        drop(inherited);
        assert!(lock(&path).is_err());
        drop(next);
        assert!(lock(&path).is_ok());
    }

    #[cfg(unix)]
    #[test]
    fn storage_rejects_symlinks_and_hard_links_without_touching_targets() {
        use std::os::unix::fs::{symlink, PermissionsExt};
        let temp = tempfile::tempdir().unwrap();
        let target = temp.path().join("unrelated");
        fs::create_dir(&target).unwrap();
        fs::set_permissions(&target, fs::Permissions::from_mode(0o755)).unwrap();
        let alias = temp.path().join("alias");
        symlink(&target, &alias).unwrap();
        assert!(private_dir(&alias).is_err());
        assert!(private_dir(&alias.join("child")).is_err());
        assert!(!target.join("child").exists());
        assert_eq!(
            fs::metadata(&target).unwrap().permissions().mode() & 0o777,
            0o755
        );
        let original = temp.path().join("original");
        fs::write(&original, b"synthetic-private-value").unwrap();
        fs::set_permissions(&original, fs::Permissions::from_mode(0o600)).unwrap();
        assert!(private_file_limit(&original, 8).is_err());
        assert_eq!(
            private_file_limit(&original, 64).unwrap(),
            b"synthetic-private-value"
        );
        let linked = temp.path().join("linked");
        symlink(&original, &linked).unwrap();
        assert!(lock(&linked).is_err());
        assert!(private_file(&linked).is_err());
        assert!(private_database(&linked).is_err());
        fs::remove_file(&linked).unwrap();
        fs::hard_link(&original, &linked).unwrap();
        assert!(lock(&linked).is_err());
        assert!(private_file(&linked).is_err());
        assert!(private_database(&linked).is_err());
        assert_eq!(fs::read(original).unwrap(), b"synthetic-private-value");
    }

    #[cfg(unix)]
    #[test]
    fn new_storage_parents_and_database_are_private() {
        use std::os::unix::fs::PermissionsExt;
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("one/two");
        private_dir(&path).unwrap();
        for dir in [&path, &path.parent().unwrap().to_owned()] {
            assert_eq!(
                fs::metadata(dir).unwrap().permissions().mode() & 0o777,
                0o700
            );
        }
        let db = path.join("receipts.sqlite3");
        private_database(&db)
            .unwrap()
            .execute_batch("CREATE TABLE test (id INTEGER)")
            .unwrap();
        assert_eq!(
            fs::metadata(db).unwrap().permissions().mode() & 0o777,
            0o600
        );
    }
}
