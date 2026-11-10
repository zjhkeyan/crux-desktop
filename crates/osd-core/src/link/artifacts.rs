//! Bounded, content-verified file transfer. Incomplete files never replace results.
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Component, Path, PathBuf};

pub const CHUNK_SIZE: usize = 256 * 1024;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ArtifactEntry {
    pub path: String,
    pub sha256: String,
    pub size: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum ArtifactTransfer {
    Stat {
        path: String,
    },
    Read {
        entry: ArtifactEntry,
        offset: u64,
    },
    Write {
        entry: ArtifactEntry,
        offset: u64,
        data: String,
    },
    Complete {
        entry: ArtifactEntry,
    },
    Result {
        entries: Vec<ArtifactEntry>,
        data: Option<String>,
        error: Option<String>,
    },
}

pub fn scoped_path(root: &Path, relative: &str) -> Result<PathBuf, String> {
    if relative.is_empty()
        || Path::new(relative)
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
        || relative.contains('\\')
    {
        return Err("artifact path must be relative without parent traversal".into());
    }
    let mut path = root.canonicalize().map_err(|e| e.to_string())?;
    for part in Path::new(relative).components() {
        path.push(part);
        match std::fs::symlink_metadata(&path) {
            Ok(m) if m.file_type().is_symlink() => {
                return Err("artifact symlinks are not allowed".into())
            }
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => return Err(e.to_string()),
            _ => (),
        }
    }
    Ok(path)
}

pub fn describe(root: &Path, relative: &str) -> Result<ArtifactEntry, String> {
    let mut file = File::open(scoped_path(root, relative)?).map_err(|e| e.to_string())?;
    if !file.metadata().map_err(|e| e.to_string())?.is_file() {
        return Err("artifact must be a regular file".into());
    }
    let mut hasher = Sha256::new();
    let size = std::io::copy(&mut file, &mut hasher).map_err(|e| e.to_string())?;
    Ok(ArtifactEntry {
        path: relative.into(),
        sha256: format!("{:x}", hasher.finalize()),
        size,
    })
}

fn temporary(root: &Path, entry: &ArtifactEntry) -> Result<PathBuf, String> {
    if entry.sha256.len() != 64 || !entry.sha256.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("invalid artifact SHA256".into());
    }
    let target = scoped_path(root, &entry.path)?;
    Ok(target.with_file_name(format!(".crux-{}.part", entry.sha256)))
}

pub fn read_chunk(root: &Path, entry: &ArtifactEntry, offset: u64) -> Result<String, String> {
    if offset > entry.size {
        return Err("artifact offset exceeds size".into());
    }
    let mut file = File::open(scoped_path(root, &entry.path)?).map_err(|e| e.to_string())?;
    file.seek(SeekFrom::Start(offset))
        .map_err(|e| e.to_string())?;
    let mut data = Vec::new();
    file.take((CHUNK_SIZE as u64).min(entry.size - offset))
        .read_to_end(&mut data)
        .map_err(|e| e.to_string())?;
    Ok(STANDARD.encode(data))
}

pub fn write_chunk(
    root: &Path,
    entry: &ArtifactEntry,
    offset: u64,
    data: &str,
) -> Result<(), String> {
    if data.len() > CHUNK_SIZE.div_ceil(3) * 4 {
        return Err("artifact chunk exceeds limit".into());
    }
    let bytes = STANDARD.decode(data).map_err(|e| e.to_string())?;
    if offset
        .checked_add(bytes.len() as u64)
        .is_none_or(|n| n > entry.size)
    {
        return Err("artifact chunk exceeds size".into());
    }
    let tmp = temporary(root, entry)?;
    std::fs::create_dir_all(tmp.parent().unwrap()).map_err(|e| e.to_string())?;
    if std::fs::symlink_metadata(&tmp).is_ok_and(|m| m.file_type().is_symlink()) {
        return Err("artifact temporary path is a symlink".into());
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    if offset == 0 {
        options.create_new(true);
    }
    let mut file = match options.open(&tmp) {
        Err(e) if offset == 0 && e.kind() == std::io::ErrorKind::AlreadyExists => {
            OpenOptions::new().read(true).write(true).open(&tmp)
        }
        result => result,
    }
    .map_err(|e| e.to_string())?;
    let size = file.metadata().map_err(|e| e.to_string())?.len();
    if size < offset || size > entry.size {
        return Err("artifact chunks must be contiguous".into());
    }
    file.seek(SeekFrom::Start(offset))
        .map_err(|e| e.to_string())?;
    let existing = (size - offset).min(bytes.len() as u64) as usize;
    if existing > 0 {
        let mut previous = vec![0; existing];
        file.read_exact(&mut previous).map_err(|e| e.to_string())?;
        if previous != bytes[..existing] {
            return Err("retransmitted artifact chunk differs".into());
        }
    }
    file.write_all(&bytes[existing..])
        .map_err(|e| e.to_string())
}

pub fn complete(root: &Path, entry: &ArtifactEntry) -> Result<(), String> {
    let tmp = temporary(root, entry)?;
    let relative = tmp
        .strip_prefix(root.canonicalize().map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?
        .to_string_lossy()
        .into_owned();
    let actual = describe(root, &relative)?;
    if actual.sha256 != entry.sha256 || actual.size != entry.size {
        let _ = std::fs::remove_file(&tmp);
        return Err("artifact integrity verification failed".into());
    }
    File::open(&tmp)
        .and_then(|f| f.sync_all())
        .map_err(|e| e.to_string())?;
    std::fs::rename(tmp, scoped_path(root, &entry.path)?).map_err(|e| e.to_string())
}

pub fn handle(root: &Path, transfer: ArtifactTransfer) -> ArtifactTransfer {
    let result = (|| -> Result<(Vec<ArtifactEntry>, Option<String>), String> {
        match transfer {
            ArtifactTransfer::Stat { path } => Ok((vec![describe(root, &path)?], None)),
            ArtifactTransfer::Read { entry, offset } => {
                let data = read_chunk(root, &entry, offset)?;
                Ok((vec![entry], Some(data)))
            }
            ArtifactTransfer::Write {
                entry,
                offset,
                data,
            } => {
                write_chunk(root, &entry, offset, &data)?;
                Ok((vec![entry], None))
            }
            ArtifactTransfer::Complete { entry } => {
                complete(root, &entry)?;
                Ok((vec![entry], None))
            }
            ArtifactTransfer::Result { .. } => Err("expected an artifact request".into()),
        }
    })();
    match result {
        Ok((entries, data)) => ArtifactTransfer::Result {
            entries,
            data,
            error: None,
        },
        Err(error) => ArtifactTransfer::Result {
            entries: vec![],
            data: None,
            error: Some(error),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn chunks_are_verified_before_replacing_a_file() {
        let root =
            std::env::temp_dir().join(format!("crux-artifact-{}", crate::runtime::random_hex(8)));
        struct Cleanup(PathBuf);
        impl Drop for Cleanup {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
        let _cleanup = Cleanup(root.clone());
        std::fs::create_dir_all(&root).unwrap();
        let entry = ArtifactEntry {
            path: "result.txt".into(),
            sha256: "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad".into(),
            size: 3,
        };
        write_chunk(&root, &entry, 0, "YWJj").unwrap();
        write_chunk(&root, &entry, 0, "YWJj").expect("a retransmitted chunk is idempotent");
        assert!(!root.join("result.txt").exists());
        complete(&root, &entry).unwrap();
        assert_eq!(describe(&root, "result.txt").unwrap(), entry);
        assert_eq!(read_chunk(&root, &entry, 0).unwrap(), "YWJj");
        assert!(describe(&root, "../secret").is_err());
        write_chunk(&root, &entry, 0, "eHl6").unwrap();
        assert!(complete(&root, &entry).is_err());
        assert_eq!(std::fs::read(root.join("result.txt")).unwrap(), b"abc");
        std::fs::remove_dir_all(root).unwrap();
    }
}
