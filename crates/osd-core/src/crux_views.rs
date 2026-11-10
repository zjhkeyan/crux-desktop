//! Read-only Crux discovery projections. Private ledger state is never opened here.
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

/// Resolve a run inside the active workspace for both HTTP and Tauri callers.
pub fn scoped_run_dir(env: &crate::Env, run_dir: &str) -> Result<PathBuf, String> {
    let workspace = crate::runtime::workspace_dir(env)?
        .canonicalize()
        .map_err(|e| e.to_string())?;
    let path = workspace
        .join(run_dir)
        .canonicalize()
        .map_err(|e| e.to_string())?;
    if !path.starts_with(&workspace) {
        return Err("Crux discovery run is outside the workspace".into());
    }
    Ok(path)
}

fn is_state_dir_name(name: &std::ffi::OsStr) -> bool {
    name == ".crux" || name == ".coral"
}

fn run_root(run_dir: &Path) -> Result<&Path, String> {
    if run_dir.file_name().is_some_and(is_state_dir_name) {
        run_dir.parent().ok_or_else(|| "Crux discovery run has no parent".into())
    } else {
        Ok(run_dir)
    }
}

fn public_dir(run_dir: &Path) -> Result<PathBuf, String> {
    let root = run_root(run_dir)?;
    let crux = root.join(".crux");
    let coral = root.join(".coral");
    if std::fs::symlink_metadata(&crux).is_ok() && std::fs::symlink_metadata(&coral).is_ok() {
        return Err("both .crux and .coral exist in the run directory; remove or migrate one".into());
    }
    if run_dir.file_name().is_some_and(is_state_dir_name) {
        return Ok(run_dir.join("public"));
    }
    if std::fs::symlink_metadata(&crux).is_ok() {
        Ok(crux.join("public"))
    } else if std::fs::symlink_metadata(&coral).is_ok() {
        Ok(coral.join("public"))
    } else {
        Ok(crux.join("public"))
    }
}

fn public_path(run_dir: &Path, relative: &str) -> Result<PathBuf, String> {
    let components: Vec<_> = run_dir.components().collect();
    if components
        .windows(2)
        .any(|pair| is_state_dir_name(pair[0].as_os_str()) && pair[1].as_os_str() == "private")
    {
        return Err("Crux discovery private storage cannot be used as a run directory".into());
    }
    // Reject symlinks at every level, including public itself, before opening.
    let public = public_dir(run_dir)?;
    let run = run_root(run_dir)?;
    let file = public.join(relative);
    let rel = file.strip_prefix(run).map_err(|e| e.to_string())?;
    let mut path = run.to_path_buf();
    for component in rel.components() {
        if !matches!(component, std::path::Component::Normal(_)) {
            return Err("invalid public path".into());
        }
        path.push(component);
        match std::fs::symlink_metadata(&path) {
            Ok(meta) if meta.file_type().is_symlink() => {
                return Err("Crux discovery public views cannot be symlinks".into());
            }
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => return Err(e.to_string()),
            _ => (),
        }
    }
    Ok(file)
}

fn read_public(run_dir: &Path, relative: &str) -> Result<Value, String> {
    let file = public_path(run_dir, relative)?;
    use std::io::Read;
    let mut bytes = Vec::new();
    std::fs::File::open(&file)
        .map_err(|e| e.to_string())?
        .take(25 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() > 25 * 1024 * 1024 {
        return Err("Crux discovery public view exceeds 25 MiB".into());
    }
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|e| format!("invalid Crux discovery public view: {e}"))?;
    if let Some(seq) = value.get("head_seq") {
        let seq = seq.as_u64().ok_or("invalid view sequence")?;
        let hmac = value["head_hmac"]
            .as_str()
            .filter(|s| !s.is_empty())
            .ok_or("missing view HMAC")?;
        let run = run_root(run_dir)?;
        crate::provenance::verify_discovery_anchor(run, seq, hmac)?;
    }
    Ok(value)
}

pub fn read_ledger_head(run_dir: &Path) -> Result<Value, String> {
    let mut head = read_public(run_dir, "ledger_head")?;
    let seq = head["head_seq"]
        .as_u64()
        .ok_or("invalid ledger head sequence")?;
    let hmac = head["head_hmac"]
        .as_str()
        .filter(|s| !s.is_empty())
        .ok_or("invalid ledger head HMAC")?;
    let run = run_root(run_dir)?;
    let status = crate::provenance::verify_discovery_anchor(run, seq, hmac)?;
    head["anchor_status"] = json!(status);
    Ok(head)
}

pub fn read_board_view(run_dir: &Path) -> Result<Value, String> {
    let pub_dir = public_dir(run_dir)?;
    if std::fs::symlink_metadata(pub_dir.join("views/board.json")).is_ok() {
        read_public(run_dir, "views/board.json")
    } else {
        read_public(run_dir, "directions/board_snapshot.json")
    }
}

pub fn read_tree_view(run_dir: &Path, commit: Option<&str>) -> Result<Value, String> {
    if commit.is_some_and(|c| {
        c.is_empty()
            || !c
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    }) {
        return Err("invalid commit".into());
    }
    let pub_dir = public_dir(run_dir)?;
    let tree = if std::fs::symlink_metadata(pub_dir.join("views/tree.json")).is_ok() {
        read_public(run_dir, "views/tree.json")?
    } else {
        let dir = public_path(run_dir, "attempts")?;
        let mut files = std::fs::read_dir(dir)
            .map_err(|e| e.to_string())?
            .map(|e| e.map(|e| e.file_name()))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?;
        files.sort();
        let mut nodes = Vec::new();
        for file in files {
            if Path::new(&file).extension().is_some_and(|s| s == "json") {
                nodes.push(read_public(
                    run_dir,
                    &format!("attempts/{}", file.to_string_lossy()),
                )?);
            }
        }
        json!({"nodes": nodes})
    };
    if let Some(commit) = commit {
        let nodes = tree
            .get("nodes")
            .or_else(|| tree.get("attempts"))
            .unwrap_or(&tree);
        let found = match nodes {
            Value::Array(nodes) => nodes
                .iter()
                .find(|n| n["commit"] == commit || n["commit_hash"] == commit || n["id"] == commit),
            Value::Object(nodes) => nodes.get(commit),
            _ => None,
        };
        return found
            .cloned()
            .ok_or_else(|| "Crux discovery commit not found".into());
    }
    Ok(tree)
}

pub fn read_archive_view(run_dir: &Path) -> Result<Value, String> {
    let mut archive = read_public(run_dir, "views/archive.json")?;
    if archive.get("comparison").is_none() {
        if let Ok(comp) = read_public(run_dir, "views/comparison.json") {
            if let Some(obj) = archive.as_object_mut() {
                obj.insert("comparison".into(), comp);
            }
        }
    }
    Ok(archive)
}

pub fn read_radio_view(run_dir: &Path) -> Result<Value, String> {
    read_public(run_dir, "views/radio.json")
}

pub fn read_egress_view(run_dir: &Path) -> Result<Value, String> {
    let path = public_path(run_dir, "views/egress.json")?;
    match std::fs::symlink_metadata(&path) {
        Ok(_) => read_public(run_dir, "views/egress.json"),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(json!({"state":"RUNNING","mode":"direct"})),
        Err(e) => Err(e.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Run(PathBuf);
    impl Run {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "crux-discovery-views-{}",
                crate::runtime::random_hex(12)
            ));
            std::fs::create_dir_all(root.join(".coral/public/views")).unwrap();
            Self(root)
        }
        fn write(&self, path: &str, value: Value) {
            let file = self.0.join(path);
            std::fs::create_dir_all(file.parent().unwrap()).unwrap();
            std::fs::write(file, value.to_string()).unwrap();
        }
    }
    impl Drop for Run {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn egress_defaults_only_when_missing_and_still_rejects_unsafe_views() {
        let run = Run::new();
        assert_eq!(read_egress_view(&run.0).unwrap(), json!({"state":"RUNNING","mode":"direct"}));
        run.write(".coral/public/views/egress.json", json!({"state":"PAUSED_AUTH","mode":"tunnel"}));
        assert_eq!(read_egress_view(&run.0).unwrap()["state"], "PAUSED_AUTH");
        std::fs::write(run.0.join(".coral/public/views/egress.json"), "broken").unwrap();
        assert!(read_egress_view(&run.0).is_err());
    }

    #[test]
    fn discovery_views_prefer_crux_fallback_to_coral_and_reject_both() {
        let root = std::env::temp_dir().join(format!(
            "crux-both-views-{}",
            crate::runtime::random_hex(12)
        ));
        std::fs::create_dir_all(root.join(".crux/public/views")).unwrap();
        std::fs::write(
            root.join(".crux/public/views/board.json"),
            r#"{"directions":[{"id":"crux-dir"}]}"#,
        )
        .unwrap();
        assert_eq!(
            read_board_view(&root).unwrap()["directions"][0]["id"],
            "crux-dir"
        );
        std::fs::create_dir_all(root.join(".coral/public/views")).unwrap();
        assert!(read_board_view(&root)
            .unwrap_err()
            .contains("both .crux and .coral"));
        let _ = std::fs::remove_dir_all(&root);
    }

    #[test]
    fn coral_reads_tree_commit_and_attempt_fallback_archive_and_radio() {
        let r = Run::new();
        r.write(
            ".coral/public/attempts/b.json",
            json!({"commit":"b", "parent":"a", "inspired_by":["c"], "status":"PROVISIONAL"}),
        );
        r.write(".coral/public/attempts/a.json", json!({"commit":"a"}));
        assert_eq!(
            read_tree_view(&r.0, None).unwrap()["nodes"][0]["commit"],
            "a"
        );
        assert_eq!(
            read_tree_view(&r.0, Some("b")).unwrap()["status"],
            "PROVISIONAL"
        );
        assert!(read_tree_view(&r.0, Some("../private")).is_err());
        assert!(read_tree_view(&r.0, Some("missing")).is_err());
        r.write(
            ".coral/public/views/tree.json",
            json!({"nodes":[{"commit":"c", "status":"REFUTED"}]}),
        );
        assert_eq!(
            read_tree_view(&r.0, Some("c")).unwrap()["status"],
            "REFUTED"
        );
        r.write(
            ".coral/public/views/archive.json",
            json!({"insights":[{"state":"PROMOTED"}], "constraints":[{"scope":"d1", "ttl":20}]}),
        );
        assert_eq!(
            read_archive_view(&r.0).unwrap()["constraints"][0]["ttl"],
            20
        );
        r.write(".coral/public/views/radio.json", json!({"messages":[{"kind":"REVIEW_VERDICT", "verdict":"SUSPECT"}], "rejected_count":3}));
        assert_eq!(
            read_radio_view(&r.0.join(".coral")).unwrap()["rejected_count"],
            3
        );
    }

    #[test]
    fn coral_head_detects_truncation_and_substitution_without_anchoring_reads() {
        let r = Run::new();
        r.write(
            ".coral/public/ledger_head",
            json!({"head_seq":12, "head_hmac":"abc"}),
        );
        assert_eq!(
            read_ledger_head(&r.0).unwrap()["anchor_status"],
            "unanchored"
        );
        assert!(!r.0.join(".provenance").exists());
        crate::provenance::record_discovery_anchor(&r.0, 12, "abc", "best", 3.5).unwrap();
        crate::provenance::record_coral_anchor(&r.0, 12, "abc", "best", 3.5).unwrap();
        let text = std::fs::read_to_string(r.0.join(".provenance/runs.jsonl")).unwrap();
        assert_eq!(text.lines().count(), 1);
        let entry: Value = serde_json::from_str(text.trim()).unwrap();
        assert_eq!(entry["best_commit"], "best");
        assert_eq!(entry["best_score"], 3.5);
        assert_eq!(read_ledger_head(&r.0).unwrap()["anchor_status"], "matched");
        r.write(
            ".coral/public/ledger_head",
            json!({"head_seq":11, "head_hmac":"old"}),
        );
        assert!(read_ledger_head(&r.0).unwrap_err().contains("truncation"));
        r.write(
            ".coral/public/ledger_head",
            json!({"head_seq":12, "head_hmac":"forged"}),
        );
        assert!(read_ledger_head(&r.0).unwrap_err().contains("HMAC"));
        r.write(
            ".coral/public/views/archive.json",
            json!({"head_seq":10, "head_hmac":"old"}),
        );
        assert!(read_archive_view(&r.0).is_err());
        r.write(
            ".coral/public/ledger_head",
            json!({"head_seq":13, "head_hmac":"new"}),
        );
        assert_eq!(read_ledger_head(&r.0).unwrap()["anchor_status"], "ahead");
        assert!(crate::provenance::record_coral_anchor(&r.0, 1, "old", "best", 0.).is_err());
    }

    #[test]
    #[cfg(unix)]
    fn coral_never_follows_public_symlinks_into_private_state() {
        let r = Run::new();
        r.write(".coral/private/secret.json", json!({"secret":true}));
        r.write(
            ".coral/private/nested/.coral/public/views/archive.json",
            json!({"secret":true}),
        );
        assert!(read_archive_view(&r.0.join(".coral/private/nested"))
            .unwrap_err()
            .contains("private storage"));
        let file = r.0.join(".coral/public/views/archive.json");
        std::os::unix::fs::symlink("../../private/secret.json", &file).unwrap();
        assert!(read_archive_view(&r.0).unwrap_err().contains("symlink"));
        std::fs::remove_file(file).unwrap();
        std::fs::remove_dir_all(r.0.join(".coral/public/views")).unwrap();
        std::os::unix::fs::symlink("../private", r.0.join(".coral/public/views")).unwrap();
        assert!(read_archive_view(&r.0).is_err());
        assert!(read_radio_view(&r.0).is_err());
    }

    #[test]
    fn coral_public_board_prefers_view_and_falls_back_only_when_missing() {
        let r = Run::new();
        r.write(
            ".coral/public/directions/board_snapshot.json",
            json!({"directions": [{"id":"d1"}]}),
        );
        assert_eq!(read_board_view(&r.0).unwrap()["directions"][0]["id"], "d1");
        r.write(".coral/public/views/board.json", json!({"directions": []}));
        assert_eq!(read_board_view(&r.0).unwrap()["directions"], json!([]));
        std::fs::write(r.0.join(".coral/public/views/board.json"), "broken").unwrap();
        assert!(read_board_view(&r.0).is_err());
    }
}
