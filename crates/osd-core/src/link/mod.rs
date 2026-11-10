//! One SSH connection carrying control, gateway traffic, and provider egress.
pub mod artifacts;
pub mod control;
pub mod openssh;

use control::ControlFrame;
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const BOOTSTRAP: &str = include_str!("bootstrap.sh");

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum LinkStatus {
    #[default]
    Disconnected,
    Connecting,
    Connected,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecOutput {
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
}

pub trait LinkTransport {
    fn connect(&mut self) -> Result<Value, String>;
    fn send_control(&mut self, frame: &ControlFrame) -> Result<(), String>;
    fn exec_remote(&mut self, argv: &[String]) -> Result<ExecOutput, String>;
    fn probe_reverse_uds(&mut self, nonce: &str) -> Result<bool, String>;
    fn disconnect(&mut self) -> Result<(), String>;
    fn status(&self) -> LinkStatus;
}

pub const DISCOVERY_VERBS: &[&str] = &[
    "eval",
    "board",
    "direction",
    "claim",
    "release",
    "tree",
    "insight",
    "review",
    "radio",
    "init",
    "start",
    "stop",
    "resume",
    "status",
    "ls",
    "runs",
    "log",
    "validate",
    "doctor",
    "agents",
    "notes",
    "skills",
    "attempts",
    "show",
    "diff",
    "checkout",
    "export",
    "ledger",
    "ui",
    "test-eval",
    "wait",
    "revert",
    "heartbeat",
];

pub fn validate_discovery_argv(argv: &[String], agent: bool) -> Result<(), String> {
    let verb = argv.first().ok_or("argv must contain a discovery verb")?;
    if !DISCOVERY_VERBS.contains(&verb.as_str()) || argv.iter().any(|a| a.contains('\0')) {
        return Err("command is not an allowed discovery verb".into());
    }
    if agent
        && ![
            "eval",
            "board",
            "direction",
            "claim",
            "release",
            "tree",
            "insight",
            "review",
            "radio",
            "show",
            "diff",
            "skills",
            "notes",
            "attempts",
        ]
        .contains(&verb.as_str())
    {
        return Err("command is not available to discovery agents".into());
    }
    Ok(())
}

/// Runs an enumerated engine verb with argv intact, never through a shell.
pub fn run_crux_command(env: &crate::Env, argv: &[String]) -> Result<ExecOutput, String> {
    validate_discovery_argv(argv, false)?;
    let explicit = std::env::var_os("CRUX_ENGINE").map(std::path::PathBuf::from);
    let bin = crate::crux_bridge::bin_dir(env)?;
    let names: &[&str] = if cfg!(windows) {
        &["crux-engine.exe", "crux-engine.cmd"]
    } else {
        &["crux-engine"]
    };
    let engine = explicit
        .or_else(|| {
            names
                .iter()
                .map(|name| bin.join(name))
                .find(|p| p.is_file())
        })
        .or_else(|| {
            crate::which::find_on_path("crux-engine", Some(&crate::runtime::enriched_path()))
        })
        .ok_or("Crux engine is not installed; install the engine before running discovery")?;
    let mut forwarded = argv.to_vec();
    if forwarded[0] == "ls" {
        forwarded[0] = "runs".into();
    }
    let out = crate::runtime::quiet_command(engine)
        .args(forwarded)
        .env("CRUX_PROG", "crux discovery")
        .current_dir(crate::runtime::workspace_dir(env)?)
        .output()
        .map_err(|e| e.to_string())?;
    Ok(ExecOutput {
        exit_code: out.status.code().unwrap_or(1),
        stdout: String::from_utf8_lossy(&out.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
    })
}
