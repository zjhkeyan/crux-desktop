// Crux Discovery front door: routes top-level agent verbs (`crux eval`, `crux board`, …)
// and operator subcommands (`crux discovery <verb>` / `crux swarm <verb>`) to `crux-engine`,
// while enforcing the allowlist Agent Guard (exit 77) whenever `CRUX_AGENT_ID` or
// `CORAL_AGENT_ID` is present in the environment.

use std::path::{Path, PathBuf};
use std::process::Command;

pub const AGENT_VERBS: &[&str] = &[
    "eval",
    "board",
    "direction",
    "claim",
    "release",
    "tree",
    "insight",
    "review",
    "radio",
];

pub const OPERATOR_VERBS: &[&str] = &[
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

#[cfg(test)]
pub const DESKTOP_VERBS: &[&str] = &[
    "server",
    "serve",
    "login",
    "status",
    "session",
    "screen",
    "term",
    "audit",
    "project",
    "worktree",
    "run",
    "fs",
    "settings",
    "model",
    "permission",
    "question",
    "approval",
    "auth",
    "account",
    "version",
    "termd",
    "remote",
    "link-agent",
];

const AGENT_ALLOW_TOP: &[&str] = &[
    "eval",
    "board",
    "direction",
    "claim",
    "release",
    "tree",
    "insight",
    "review",
    "radio",
    "worktree",
    "version",
    "--version",
    "help",
    "--help",
    "-h",
    "discovery",
    "swarm",
];

const AGENT_DISCOVERY_ALLOW: &[&str] = &[
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
    "help",
    "--help",
    "-h",
];

/// True when running inside a managed discovery agent worktree/session.
/// No CLI flag can lift this check.
pub fn agent_context() -> bool {
    std::env::var_os("CRUX_AGENT_ID").is_some_and(|v| !v.is_empty())
        || std::env::var_os("CORAL_AGENT_ID").is_some_and(|v| !v.is_empty())
}

/// Pure allowlist check on `argv` (the arguments after `crux`).
/// Returns `Ok(())` if allowed, or `Err(denied_command_label)` if forbidden to discovery agents.
pub fn check_allowed_for_agent(argv: &[String]) -> Result<(), String> {
    let Some(first) = argv.first().map(String::as_str) else {
        return Ok(());
    };
    if !AGENT_ALLOW_TOP.contains(&first) {
        return Err(first.to_string());
    }
    if first == "discovery" || first == "swarm" {
        if let Some(sub) = argv.get(1).map(String::as_str) {
            if !AGENT_DISCOVERY_ALLOW.contains(&sub) {
                return Err(format!("{first} {sub}"));
            }
        }
    }
    Ok(())
}

/// Enforce the allowlist guard when `agent_context()` is active. Exits 77 on violation.
pub fn enforce_agent_guard(argv: &[String]) {
    if agent_context() {
        if let Err(denied) = check_allowed_for_agent(argv) {
            eprintln!("crux: '{denied}' is not available to discovery agents");
            std::process::exit(77);
        }
    }
}

/// Whether `argv` should be routed to the discovery engine instead of desktop `osd-cli`.
pub fn should_route(argv: &[String]) -> bool {
    let Some(first) = argv.first().map(String::as_str) else {
        return false;
    };
    first == "discovery" || first == "swarm" || AGENT_VERBS.contains(&first)
}

/// Compute `(prog_name, engine_args)` from `argv`.
pub fn translate_args(argv: &[String]) -> Result<(String, Vec<String>), String> {
    let Some(first) = argv.first().map(String::as_str) else {
        return Err("missing discovery command".into());
    };
    if first == "discovery" || first == "swarm" {
        let rest = &argv[1..];
        if rest.is_empty() {
            return Ok(("crux discovery".into(), vec!["--help".into()]));
        }
        let sub = rest[0].as_str();
        if matches!(sub, "help" | "--help" | "-h") {
            return Ok(("crux discovery".into(), vec!["--help".into()]));
        }
        if !AGENT_VERBS.contains(&sub) && !OPERATOR_VERBS.contains(&sub) {
            return Err(format!("unknown discovery command: {sub}"));
        }
        let mut forwarded: Vec<String> = rest.to_vec();
        if forwarded[0] == "ls" {
            forwarded[0] = "runs".into();
        }
        Ok(("crux discovery".into(), forwarded))
    } else if AGENT_VERBS.contains(&first) {
        Ok(("crux".into(), argv.to_vec()))
    } else {
        Err(format!("not a discovery command: {first}"))
    }
}

fn resolve_engine_command() -> Result<(PathBuf, Vec<String>), String> {
    if let Some(explicit) = std::env::var_os("CRUX_ENGINE").filter(|v| !v.is_empty()) {
        let path = PathBuf::from(explicit);
        if path.is_file() {
            return Ok((path, Vec::new()));
        }
    }
    let names: &[&str] = if cfg!(windows) {
        &["crux-engine.exe", "crux-engine.cmd", "coral.exe", "coral.cmd"]
    } else {
        &["crux-engine", "coral"]
    };
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for name in names {
                let candidate = dir.join(name);
                if candidate.is_file() && candidate != exe {
                    return Ok((candidate, Vec::new()));
                }
            }
        }
    }
    if let Ok(env) = osd_core::Env::headless(None, None, env!("CARGO_PKG_VERSION").to_string()) {
        if let Ok(bin) = osd_core::crux_bridge::bin_dir(&env) {
            for name in names {
                let candidate = bin.join(name);
                if candidate.is_file() {
                    return Ok((candidate, Vec::new()));
                }
            }
        }
    }
    if let Some(home) = std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" }).map(PathBuf::from) {
        let local_bin = home.join(".local/bin");
        for name in names {
            let candidate = local_bin.join(name);
            if candidate.is_file() {
                return Ok((candidate, Vec::new()));
            }
        }
    }
    let path_env = osd_core::runtime::enriched_path();
    for name in ["crux-engine", "coral"] {
        if let Some(found) = osd_core::which::find_on_path(name, Some(&path_env)) {
            if std::env::current_exe().ok().as_ref() != Some(&found) {
                return Ok((found, Vec::new()));
            }
        }
    }
    // Development checkout fallback via uv.
    for base in [std::env::current_dir().ok(), std::env::current_exe().ok()]
        .into_iter()
        .flatten()
    {
        for ancestor in base.ancestors() {
            let coral_dir = ancestor.join("CORAL");
            if coral_dir.join("pyproject.toml").is_file() {
                let uv = osd_core::runtime::sidecar_bin("uv").unwrap_or_else(|| PathBuf::from("uv"));
                return Ok((
                    uv,
                    vec![
                        "--directory".into(),
                        coral_dir.to_string_lossy().into_owned(),
                        "run".into(),
                        "coral".into(),
                    ],
                ));
            }
        }
    }
    Err("crux-engine is not installed; run scripts/dev/setup-crux-engine.sh or start Crux Desktop".into())
}

pub fn split_remote(argv: &[String]) -> Result<(Vec<String>, Option<String>), String> {
    let mut forwarded = Vec::new();
    let mut host = None;
    let mut args = argv.iter();
    while let Some(arg) = args.next() {
        if arg == "--" {forwarded.push(arg.clone()); forwarded.extend(args.cloned()); break;}
        let remote = if arg == "--on" {Some(args.next().ok_or("--on needs a saved host id")?.clone())}
            else {arg.strip_prefix("--on=").map(str::to_string)};
        if let Some(remote) = remote {
            if remote.is_empty() || host.replace(remote).is_some() {return Err("--on requires exactly one saved host id".into());}
        } else {forwarded.push(arg.clone());}
    }
    Ok((forwarded, host))
}

pub fn run(argv: &[String]) -> Result<(), String> {
    let (argv, remote) = split_remote(argv)?;
    let (prog, forwarded) = translate_args(&argv)?;
    if let Some(host) = remote {return crate::remote::run_discovery(&host, &forwarded);}
    let (program, mut prefix_args) = resolve_engine_command()?;
    prefix_args.extend(forwarded);

    let mut cmd = Command::new(&program);
    cmd.args(&prefix_args).env("CRUX_PROG", &prog);

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        let err = cmd.exec();
        Err(format!("failed to exec {}: {err}", program.display()))
    }
    #[cfg(not(unix))]
    {
        let status = cmd
            .status()
            .map_err(|e| format!("failed to spawn {}: {e}", program.display()))?;
        std::process::exit(status.code().unwrap_or(1));
    }
}

#[allow(dead_code)]
pub fn is_valid_engine_dir(path: &Path) -> bool {
    path.join("pyproject.toml").is_file()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn remote_selector_is_removed_without_changing_engine_arguments() {
        let argv: Vec<_> = ["discovery", "start", "--on", "hpc", "--config", "a & b.yaml"].map(String::from).into();
        let (args, host) = split_remote(&argv).unwrap();
        assert_eq!(host.as_deref(), Some("hpc"));
        assert_eq!(args, ["discovery", "start", "--config", "a & b.yaml"]);
        assert!(split_remote(&["board".into(), "--on".into()]).is_err());
        assert!(split_remote(&["board".into(), "--on=hpc".into(), "--on=other".into()]).is_err());
        assert_eq!(split_remote(&["board".into(), "--".into(), "--on=hpc".into()]).unwrap().1, None);
    }

    #[test]
    fn agent_and_desktop_top_level_verbs_are_strictly_disjoint() {
        for verb in AGENT_VERBS {
            assert!(
                !DESKTOP_VERBS.contains(verb),
                "top-level agent verb '{verb}' collides with desktop verb"
            );
        }
    }

    #[test]
    fn operator_verbs_require_discovery_prefix_unless_also_agent_verbs() {
        for verb in OPERATOR_VERBS {
            if !AGENT_VERBS.contains(verb) {
                assert!(
                    !should_route(&[(*verb).to_string()]),
                    "operator verb '{verb}' must not route at top-level"
                );
            }
            let routed = translate_args(&["discovery".into(), (*verb).to_string()]).unwrap();
            assert_eq!(routed.0, "crux discovery");
            let expected = if *verb == "ls" { "runs" } else { *verb };
            assert_eq!(routed.1, vec![expected.to_string()]);
        }
    }

    #[test]
    fn agent_verbs_work_both_top_level_and_under_discovery() {
        for verb in AGENT_VERBS {
            assert!(should_route(&[(*verb).to_string()]));
            let top = translate_args(&[(*verb).to_string(), "--help".into()]).unwrap();
            assert_eq!(top.0, "crux");
            assert_eq!(top.1, vec![(*verb).to_string(), "--help".to_string()]);

            let nested =
                translate_args(&["discovery".into(), (*verb).to_string(), "--help".into()])
                    .unwrap();
            assert_eq!(nested.0, "crux discovery");
            assert_eq!(nested.1, vec![(*verb).to_string(), "--help".to_string()]);
        }
    }

    #[test]
    fn agent_guard_allows_only_allowlisted_verbs_and_has_no_flag_override() {
        for allowed in [
            vec!["eval", "-m", "test"],
            vec!["board"],
            vec!["direction", "--id", "d1"],
            vec!["claim", "d1", "-i", "plan"],
            vec!["release", "d1"],
            vec!["tree"],
            vec!["insight", "--claim", "c"],
            vec!["review", "--target", "abc", "--verdict", "CONFIRMED"],
            vec!["radio", "inbox"],
            vec!["discovery", "eval", "-m", "test"],
            vec!["discovery", "show", "abc"],
            vec!["discovery", "diff", "abc"],
            vec!["discovery", "notes"],
            vec!["discovery", "skills"],
            vec!["discovery", "attempts"],
            vec!["version"],
            vec!["help"],
        ] {
            let argv: Vec<String> = allowed.into_iter().map(String::from).collect();
            assert!(
                check_allowed_for_agent(&argv).is_ok(),
                "expected {:?} to be allowed for agents",
                argv
            );
        }

        for denied in [
            vec!["permission", "allow", "123"],
            vec!["permission", "allow", "123", "--operator-override"],
            vec!["approval", "set", "full"],
            vec!["server"],
            vec!["session", "ls"],
            vec!["screen", "ls"],
            vec!["term", "send", "1", "rm -rf"],
            vec!["settings", "set", "k=v"],
            vec!["auth", "set", "openai", "--key", "sk-123"],
            vec!["discovery", "start", "-c", "task.yaml"],
            vec!["discovery", "stop"],
            vec!["discovery", "doctor"],
            vec!["discovery", "init", "foo"],
            vec!["swarm", "stop"],
        ] {
            let argv: Vec<String> = denied.into_iter().map(String::from).collect();
            assert!(
                check_allowed_for_agent(&argv).is_err(),
                "expected {:?} to be denied for agents",
                argv
            );
        }
    }
}
