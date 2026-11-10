//! Saved SSH destinations, host-key pins, and the app-owned pairing key.
use crate::Env;
use base64::{engine::general_purpose::STANDARD, Engine};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RemoteHostProfile {
    pub id: String,
    pub label: String,
    pub host: String,
    pub user: String,
    #[serde(default = "default_port")]
    pub port: u16,
    pub jump_host: Option<String>,
    pub pinned_node: Option<String>,
    pub tier: Option<String>,
    #[serde(default = "default_egress")]
    pub egress_mode: String,
    pub scratch_root: Option<String>,
    pub paired_key_path: Option<String>,
    pub host_key_fingerprint: Option<String>,
    pub max_cost_usd: Option<f64>,
}
fn default_port() -> u16 {
    22
}
fn default_egress() -> String {
    "auto".into()
}

impl RemoteHostProfile {
    pub fn validate(&self) -> Result<(), String> {
        let safe = |s: &str| {
            !s.is_empty()
                && !s.starts_with('-')
                && s.bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"._-:@[]".contains(&b))
        };
        if !safe(&self.id)
            || !safe(&self.host)
            || (!self.user.is_empty() && !safe(&self.user))
            || self.port == 0
            || self.jump_host.as_ref().is_some_and(|s| !safe(s))
            || self.pinned_node.as_ref().is_some_and(|s| !safe(s))
        {
            return Err("invalid SSH host, user, port, or jump host".into());
        }
        if !["auto", "direct", "tunnel", "relay"].contains(&self.egress_mode.as_str())
            || self
                .tier
                .as_ref()
                .is_some_and(|t| !["T1", "T2"].contains(&t.as_str()))
            || self.max_cost_usd.is_some_and(|n| !n.is_finite() || n < 0.0)
        {
            return Err("invalid remote tier, egress mode, or budget".into());
        }
        Ok(())
    }
    pub fn destination(&self) -> String {
        let host = self.pinned_node.as_deref().unwrap_or(&self.host);
        if self.user.is_empty() {
            host.into()
        } else {
            format!("{}@{host}", self.user)
        }
    }
}

pub fn ssh_dir(env: &Env) -> Result<PathBuf, String> {
    let path = env.data_dir().join("ssh");
    fs::create_dir_all(&path).map_err(|e| e.to_string())?;
    crate::runtime::tighten_private(&path);
    Ok(path)
}
pub fn known_hosts_path(env: &Env) -> Result<PathBuf, String> {
    Ok(ssh_dir(env)?.join("known_hosts"))
}

pub fn list_hosts(env: &Env) -> Result<Vec<RemoteHostProfile>, String> {
    match fs::read(env.data_dir().join("remote_hosts.json")) {
        Ok(bytes) => {
            serde_json::from_slice(&bytes).map_err(|e| format!("invalid remote host profiles: {e}"))
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(vec![]),
        Err(e) => Err(e.to_string()),
    }
}
pub fn find_host(env: &Env, id: &str) -> Result<RemoteHostProfile, String> {
    list_hosts(env)?
        .into_iter()
        .find(|h| h.id == id)
        .ok_or_else(|| format!("unknown remote host '{id}'; add a server first"))
}
fn edit_hosts(env: &Env, edit: impl FnOnce(&mut Vec<RemoteHostProfile>)) -> Result<(), String> {
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(ssh_dir(env)?.join("profiles.lock"))
        .map_err(|e| e.to_string())?;
    lock.lock().map_err(|e| e.to_string())?;
    let mut hosts = list_hosts(env)?;
    edit(&mut hosts);
    crate::runtime::write_atomic(
        &env.data_dir().join("remote_hosts.json"),
        &serde_json::to_string_pretty(&hosts).map_err(|e| e.to_string())?,
    )
}
pub fn save_host(env: &Env, host: RemoteHostProfile) -> Result<(), String> {
    host.validate()?;
    edit_hosts(env, |hosts| {
        if let Some(old) = hosts.iter_mut().find(|h| h.id == host.id) {
            *old = host;
        } else {
            hosts.push(host);
        }
    })
}
pub fn delete_host(env: &Env, id: &str) -> Result<(), String> {
    edit_hosts(env, |hosts| hosts.retain(|h| h.id != id))
}

pub fn host_key_fingerprint(line: &str) -> Result<String, String> {
    let fields: Vec<_> = line.split_whitespace().collect();
    if fields.len() < 3
        || ![
            "ssh-ed25519",
            "ssh-rsa",
            "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384",
            "ecdsa-sha2-nistp521",
        ]
        .contains(&fields[1])
    {
        return Err("invalid SSH host key".into());
    }
    let bytes = STANDARD
        .decode(fields[2])
        .map_err(|_| "invalid SSH host key encoding")?;
    if bytes.len() < 4 {
        return Err("invalid SSH host key data".into());
    }
    let len = u32::from_be_bytes(bytes[..4].try_into().unwrap()) as usize;
    if bytes.get(4..4 + len) != Some(fields[1].as_bytes()) {
        return Err("SSH host key type mismatch".into());
    }
    Ok(format!(
        "SHA256:{}",
        STANDARD.encode(Sha256::digest(bytes)).trim_end_matches('=')
    ))
}

/// Call only after the user compares this fingerprint through an independent channel.
pub fn pin_host_key(
    env: &Env,
    host: &mut RemoteHostProfile,
    key_line: &str,
    verified_fingerprint: &str,
) -> Result<(), String> {
    host.validate()?;
    let fingerprint = host_key_fingerprint(key_line)?;
    if fingerprint != verified_fingerprint
        || host
            .host_key_fingerprint
            .as_ref()
            .is_some_and(|p| p != &fingerprint)
    {
        return Err("SSH host key changed or was not verified; compare the fingerprint with the server administrator".into());
    }
    let fields: Vec<_> = key_line.split_whitespace().collect();
    let name = if host.port == 22 {
        host.pinned_node
            .as_deref()
            .unwrap_or(&host.host)
            .to_string()
    } else {
        format!(
            "[{}]:{}",
            host.pinned_node.as_deref().unwrap_or(&host.host),
            host.port
        )
    };
    let path = known_hosts_path(env)?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(ssh_dir(env)?.join("known_hosts.lock"))
        .map_err(|e| e.to_string())?;
    lock.lock().map_err(|e| e.to_string())?;
    let mut body = match fs::read_to_string(&path) {
        Ok(s) => s,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(e) => return Err(e.to_string()),
    };
    for line in body
        .lines()
        .filter(|l| l.split_whitespace().next() == Some(name.as_str()))
    {
        if host_key_fingerprint(line)? != fingerprint {
            return Err("SSH known-host pin conflicts with this key".into());
        }
    }
    let line = format!("{name} {} {}", fields[1], fields[2]);
    if !body.lines().any(|l| l == line) {
        body.push_str(&format!("\n{line}\n"));
    }
    crate::runtime::write_atomic(&path, &body)?;
    crate::runtime::tighten_private(&path);
    host.host_key_fingerprint = Some(fingerprint);
    save_host(env, host.clone())
}

pub fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

pub fn authorized_keys_install_script(public_key: &str) -> Result<String, String> {
    let parts: Vec<_> = public_key.split_whitespace().collect();
    if parts.len() < 2 || parts[0] != "ssh-ed25519" || STANDARD.decode(parts[1]).is_err() {
        return Err("invalid Ed25519 public key".into());
    }
    let key = shell_quote(&format!("{} {} # crux-desktop-key", parts[0], parts[1]));
    Ok(format!("umask 077 && mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && (grep -qxF -- {key} ~/.ssh/authorized_keys || printf '\\n%s\\n' {key} >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys"))
}

pub fn unpair_remote_key_script() -> String {
    "umask 077; if test -f ~/.ssh/authorized_keys; then tmp=$(mktemp ~/.ssh/.crux-keys.XXXXXX) || exit 1; trap 'rm -f \"$tmp\"' EXIT HUP INT TERM; sed '/# crux-desktop-key$/d' ~/.ssh/authorized_keys > \"$tmp\" && chmod 600 \"$tmp\" && mv \"$tmp\" ~/.ssh/authorized_keys; fi".into()
}

/// Explicit grants use SYSTEM's well-known SID, independent of Windows locale.
pub fn build_windows_icacls_commands(key_path: &Path) -> Vec<Vec<String>> {
    let user = std::env::var("USERNAME").unwrap_or_else(|_| "CURRENT_USER".into());
    vec![vec![
        key_path.to_string_lossy().into_owned(),
        "/inheritance:r".into(),
        "/grant:r".into(),
        "*S-1-5-18:(F)".into(),
        "/grant:r".into(),
        format!("{user}:(R,W)"),
    ]]
}

pub fn generate_ed25519_key(env: &Env) -> Result<(PathBuf, String), String> {
    let path = ssh_dir(env)?.join("crux_ed25519");
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(ssh_dir(env)?.join("key.lock"))
        .map_err(|e| e.to_string())?;
    lock.lock().map_err(|e| e.to_string())?;
    let ssh = crate::link::openssh::resolve_ssh(Some(env))?;
    let sibling = ssh.with_file_name(if cfg!(windows) {
        "ssh-keygen.exe"
    } else {
        "ssh-keygen"
    });
    let keygen = if sibling.is_file() {
        sibling
    } else {
        PathBuf::from("ssh-keygen")
    };
    if !path.exists() {
        let result = crate::runtime::quiet_command(&keygen)
            .args(["-t", "ed25519", "-N", "", "-f"])
            .arg(&path)
            .output()
            .map_err(|e| e.to_string())?;
        if !result.status.success() {
            return Err("SSH key generation failed; check ssh-keygen is installed".into());
        }
    }
    crate::runtime::tighten_private(&path);
    #[cfg(windows)]
    for args in build_windows_icacls_commands(&path) {
        if !crate::runtime::quiet_command("icacls")
            .args(args)
            .output()
            .map_err(|e| e.to_string())?
            .status
            .success()
        {
            return Err("cannot secure SSH key ACLs".into());
        }
    }
    let result = crate::runtime::quiet_command(keygen)
        .args(["-y", "-f"])
        .arg(&path)
        .output()
        .map_err(|e| e.to_string())?;
    if !result.status.success() {
        return Err("SSH cannot load the pairing key; repair its permissions".into());
    }
    let public_key = String::from_utf8(result.stdout).map_err(|e| e.to_string())?;
    Ok((path, public_key.trim().into()))
}

pub fn ssh_option_path(path: &Path) -> String {
    format!(
        "\"{}\"",
        path.to_string_lossy()
            .replace('\\', "/")
            .replace('"', "\\\"")
    )
}

pub fn ssh_command(env: &Env, host: &RemoteHostProfile, batch: bool) -> Result<Command, String> {
    host.validate()?;
    let mut cmd = crate::runtime::quiet_command(crate::link::openssh::resolve_ssh(Some(env))?);
    cmd.args([
        "-T",
        "-p",
        &host.port.to_string(),
        "-o",
        "ConnectTimeout=15",
        "-o",
        if host.host_key_fingerprint.is_some() {
            "StrictHostKeyChecking=yes"
        } else {
            "StrictHostKeyChecking=accept-new"
        },
        "-o",
    ])
    .arg(format!(
        "UserKnownHostsFile={}",
        ssh_option_path(&known_hosts_path(env)?)
    ));
    if batch {
        cmd.args(["-o", "BatchMode=yes"]);
    }
    if let Some(jump) = &host.jump_host {
        cmd.args(["-J", jump]);
    }
    if let Some(key) = &host.paired_key_path {
        cmd.arg("-i").arg(key);
    }
    cmd.arg(host.destination());
    Ok(cmd)
}

/// Read the key OpenSSH actually accepted, including hashed known-host entries and aliases.
pub fn observed_host_key(env: &Env, host: &RemoteHostProfile) -> Result<Option<String>, String> {
    let base = ssh_command(env, host, true)?;
    let mut inspect = crate::runtime::quiet_command(base.get_program());
    inspect.arg("-G").args(base.get_args());
    let result = inspect.output().map_err(|e| e.to_string())?;
    if !result.status.success() {
        return Err("cannot inspect SSH host configuration".into());
    }
    let config = String::from_utf8_lossy(&result.stdout);
    let hostname = config
        .lines()
        .find_map(|l| l.strip_prefix("hostname "))
        .unwrap_or(&host.host);
    let port = config
        .lines()
        .find_map(|l| l.strip_prefix("port "))
        .unwrap_or("22");
    let lookup = if port == "22" {
        hostname.to_string()
    } else {
        format!("[{hostname}]:{port}")
    };
    let sibling = PathBuf::from(base.get_program()).with_file_name(if cfg!(windows) {
        "ssh-keygen.exe"
    } else {
        "ssh-keygen"
    });
    let keygen = if sibling.is_file() {
        sibling
    } else {
        PathBuf::from("ssh-keygen")
    };
    let result = crate::runtime::quiet_command(keygen)
        .arg("-F")
        .arg(lookup)
        .arg("-f")
        .arg(known_hosts_path(env)?)
        .output()
        .map_err(|e| e.to_string())?;
    Ok(String::from_utf8_lossy(&result.stdout)
        .lines()
        .find(|line| !line.starts_with('#') && host_key_fingerprint(line).is_ok())
        .map(str::to_string))
}

pub fn generate_and_pair_ed25519_key(
    env: &Env,
    host: &mut RemoteHostProfile,
) -> Result<(), String> {
    let (path, public_key) = generate_ed25519_key(env)?;
    let status = ssh_command(env, host, false)?
        .arg(authorized_keys_install_script(&public_key)?)
        .status()
        .map_err(|e| e.to_string())?;
    if !status.success() {
        return Err("server refused SSH key installation; use interactive Link sign-in".into());
    }
    let mut paired = host.clone();
    paired.paired_key_path = Some(path.to_string_lossy().into_owned());
    let status = ssh_command(env, &paired, true)?
        .arg("true")
        .status()
        .map_err(|e| e.to_string())?;
    save_host(env, paired.clone())?;
    *host = paired;
    if !status.success() {
        return Err(
            "key installed; this server still requires interactive sign-in for each connection"
                .into(),
        );
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tofu_pins_verified_keys_and_rejects_changes() {
        let dir = std::env::temp_dir().join(format!("crux-pins-{}", crate::runtime::random_hex(8)));
        let env = Env::new(dir.clone(), dir.clone(), None, "test".into());
        let mut host: RemoteHostProfile = serde_json::from_value(
            serde_json::json!({"id":"hpc","label":"HPC","host":"login.example","user":"alice"}),
        )
        .unwrap();
        let key = "login.example ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f";
        let fingerprint = "SHA256:ZkAslGjFiUHdGf/WUL8rQvkib4PTvQatUV0OUQSncCA";
        assert_eq!(host_key_fingerprint(key).unwrap(), fingerprint);
        assert!(pin_host_key(&env, &mut host, key, "SHA256:wrong").is_err());
        pin_host_key(&env, &mut host, key, fingerprint).unwrap();
        let before = fs::read_to_string(known_hosts_path(&env).unwrap()).unwrap();
        pin_host_key(&env, &mut host, key, fingerprint).unwrap();
        assert_eq!(
            fs::read_to_string(known_hosts_path(&env).unwrap()).unwrap(),
            before
        );
        assert_eq!(
            find_host(&env, "hpc")
                .unwrap()
                .host_key_fingerprint
                .as_deref(),
            Some(fingerprint)
        );
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn profiles_round_trip_and_reject_ssh_option_injection() {
        let dir =
            std::env::temp_dir().join(format!("crux-hosts-{}", crate::runtime::random_hex(8)));
        let env = Env::new(dir.clone(), dir.clone(), None, "test".into());
        let mut host: RemoteHostProfile = serde_json::from_value(
            serde_json::json!({"id":"hpc", "label":"HPC", "host":"login.example", "user":"alice"}),
        )
        .unwrap();
        save_host(&env, host.clone()).unwrap();
        assert_eq!(find_host(&env, "hpc").unwrap(), host);
        host.host = "-oProxyCommand=bad".into();
        assert!(save_host(&env, host).is_err());
        delete_host(&env, "hpc").unwrap();
        assert!(list_hosts(&env).unwrap().is_empty());
        fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn pairing_scripts_and_windows_acl_are_safe_and_locale_independent() {
        let commands = build_windows_icacls_commands(Path::new("C:\\Crux Data\\key"));
        assert_eq!(
            &commands[0][..5],
            &[
                "C:\\Crux Data\\key",
                "/inheritance:r",
                "/grant:r",
                "*S-1-5-18:(F)",
                "/grant:r"
            ]
        );
        assert!(commands[0][5].ends_with(":(R,W)"));
        let script = authorized_keys_install_script("ssh-ed25519 YWJj comment").unwrap();
        assert!(script.contains("&& (grep -qxF"));
        assert!(script.contains("# crux-desktop-key"));
        assert!(unpair_remote_key_script().contains("chmod 600"));
        assert!(authorized_keys_install_script("ssh-ed25519 x'; touch /tmp/bad").is_err());
    }
}
