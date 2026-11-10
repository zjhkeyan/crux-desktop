//! Explicit remote operations share the same profile and Link transport.
use osd_core::{
    link::{
        openssh::{BootstrapArtifact, OpenSshConfig, OpenSshTransport},
        LinkTransport,
    },
    remote_hosts,
};
use std::path::{Path, PathBuf};

pub fn run_remote(argv: &[String]) -> Result<(), String> {
    let (arguments, state_dir, binary, sha256) = options(argv)?;
    let env = osd_core::Env::headless(None, state_dir, env!("CARGO_PKG_VERSION").into())?;
    let verb = arguments.first().map(String::as_str).unwrap_or("list");
    if verb == "list" {
        if arguments.len() > 1 {
            return Err("usage: crux remote list".into());
        }
        println!(
            "{}",
            serde_json::to_string_pretty(&remote_hosts::list_hosts(&env)?)
                .map_err(|e| e.to_string())?
        );
        return Ok(());
    }
    let host_id = arguments
        .get(1)
        .ok_or("usage: crux remote <exec|put|get|pair|status> <host> ...")?;
    let mut host = remote_hosts::find_host(&env, host_id)?;
    if verb == "pair" {
        if arguments.len() != 2 {
            return Err("usage: crux remote pair <host>".into());
        }
        remote_hosts::generate_and_pair_ed25519_key(&env, &mut host)?;
        println!("Paired {}", host.label);
        return Ok(());
    }
    let mut config = OpenSshConfig::new(&env, host)?;
    if let Some(path) = binary {
        let sha256 =
            sha256.ok_or("--binary requires the expected --sha256 from the release manifest")?;
        config.bootstrap = Some(BootstrapArtifact {
            path,
            version: env!("CARGO_PKG_VERSION").into(),
            sha256,
        });
    } else if sha256.is_some() {
        return Err("--sha256 requires --binary".into());
    }
    if verb == "status" {
        if arguments.len() != 2 {
            return Err("usage: crux remote status <host>".into());
        }
        println!(
            "{}",
            serde_json::to_string_pretty(&OpenSshTransport::preflight(config)?)
                .map_err(|e| e.to_string())?
        );
        return Ok(());
    }
    match verb {
        "exec" | "put" | "get" => (),
        _ => return Err(format!("unknown remote command: {verb}")),
    }
    if verb == "exec" && arguments.len() <= 2 {
        return Err("usage: crux remote exec <host> -- <program> [args...]".into());
    }
    if matches!(verb, "put" | "get") && arguments.len() != 4 {
        return Err(format!(
            "usage: crux remote {verb} <host> <source> <destination>"
        ));
    }
    let mut link = OpenSshTransport::new(config);
    link.connect()?;
    match verb {
        "exec" => {
            let argv = arguments[2..]
                .strip_prefix(&["--".into()])
                .unwrap_or(&arguments[2..]);
            let output = link.exec_remote(argv)?;
            print!("{}", output.stdout);
            eprint!("{}", output.stderr);
            link.disconnect()?;
            if output.exit_code != 0 {
                std::process::exit(output.exit_code);
            }
        }
        "put" => {
            let root = std::env::current_dir()
                .map_err(|e| e.to_string())?
                .canonicalize()
                .map_err(|e| e.to_string())?;
            let source = workspace_relative(&root, &arguments[2])?;
            println!(
                "{}",
                serde_json::to_string(&link.put(&root, &source, &arguments[3])?)
                    .map_err(|e| e.to_string())?
            );
        }
        "get" => {
            let root = std::env::current_dir()
                .map_err(|e| e.to_string())?
                .canonicalize()
                .map_err(|e| e.to_string())?;
            let destination = workspace_relative(&root, &arguments[3])?;
            println!(
                "{}",
                serde_json::to_string(&link.get(&arguments[2], &root, &destination)?)
                    .map_err(|e| e.to_string())?
            );
        }
        _ => unreachable!(),
    }
    link.disconnect()
}

pub fn run_discovery(host: &str, argv: &[String]) -> Result<(), String> {
    osd_core::link::validate_discovery_argv(argv, crate::discovery::agent_context())?;
    let env = osd_core::Env::headless(None, None, env!("CARGO_PKG_VERSION").into())?;
    let profile = remote_hosts::find_host(&env, host)?;
    let mut link = OpenSshTransport::new(OpenSshConfig::new(&env, profile)?);
    link.connect()?;
    let mut remote = vec!["crux".into(), "discovery".into()];
    remote.extend_from_slice(argv);
    let output = link.exec_remote(&remote)?;
    link.disconnect()?;
    print!("{}", output.stdout);
    eprint!("{}", output.stderr);
    if output.exit_code != 0 {
        std::process::exit(output.exit_code);
    }
    Ok(())
}
fn workspace_relative(root: &Path, path: &str) -> Result<String, String> {
    let path = Path::new(path);
    let relative = if path.is_absolute() {
        path.strip_prefix(root)
            .map_err(|_| "local artifact is outside the workspace")?
    } else {
        path
    };
    if relative.as_os_str().is_empty()
        || relative
            .components()
            .any(|p| !matches!(p, std::path::Component::Normal(_)))
    {
        return Err("local artifact must stay inside the workspace".into());
    }
    Ok(relative.to_string_lossy().into_owned())
}

type RemoteOptions = (
    Vec<String>,
    Option<PathBuf>,
    Option<PathBuf>,
    Option<String>,
);
fn options(argv: &[String]) -> Result<RemoteOptions, String> {
    let mut args = Vec::new();
    let mut state = None;
    let mut binary = None;
    let mut hash = None;
    let mut iter = argv.iter();
    while let Some(arg) = iter.next() {
        if arg == "--" {
            args.push(arg.clone());
            args.extend(iter.cloned());
            break;
        }
        // Once exec's host is read, everything belongs to the remote program.
        if args.first().is_some_and(|v| v == "exec") && args.len() >= 2 {
            args.push(arg.clone());
            args.extend(iter.cloned());
            break;
        }
        match arg.as_str() {
            "--state-dir" => {
                state = Some(PathBuf::from(
                    iter.next().ok_or("--state-dir needs a path")?,
                ))
            }
            "--binary" => binary = Some(PathBuf::from(iter.next().ok_or("--binary needs a path")?)),
            "--sha256" => hash = Some(iter.next().ok_or("--sha256 needs a digest")?.clone()),
            _ => args.push(arg.clone()),
        }
    }
    Ok((args, state, binary, hash))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exec_preserves_remote_options_and_shell_metacharacters() {
        let argv: Vec<_> = [
            "--state-dir",
            "/state",
            "exec",
            "hpc",
            "--",
            "printf",
            "--binary",
            "%s & ^ !",
        ]
        .map(String::from)
        .into();
        let (args, state, binary, hash) = options(&argv).unwrap();
        assert_eq!(
            args,
            ["exec", "hpc", "--", "printf", "--binary", "%s & ^ !"]
        );
        assert_eq!(state, Some(PathBuf::from("/state")));
        assert!(binary.is_none() && hash.is_none());
        assert!(workspace_relative(Path::new("/work"), "../key").is_err());
        assert!(workspace_relative(Path::new("/work"), "/private/key").is_err());
    }
}
