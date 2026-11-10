//! Remote half of Crux Link. stdout contains framed control only.
use osd_core::link::{
    artifacts,
    control::{self, ControlFrame},
    ExecOutput, BOOTSTRAP,
};
use serde_json::{json, Value};
use std::io::{BufRead, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

pub fn run_link_agent(argv: &[String]) -> Result<(), String> {
    if argv == ["--gateway-daemon"] {
        return gateway_daemon();
    }
    if argv.iter().any(|a| a != "--stdio") {
        return Err("usage: crux link-agent [--stdio]".into());
    }
    let root = std::env::current_dir().map_err(|e| e.to_string())?;
    let mut info = preflight()?;
    match ensure_gateway() {
        Ok((port, token)) => {
            info["gateway_port"] = json!(port);
            info["gateway_token"] = json!(token);
        }
        Err(error) => {
            info["gateway_error"] = json!(error);
        }
    }
    info["executable"] = json!(std::env::current_exe().map_err(|e| e.to_string())?);
    serve_control(
        &root,
        std::io::stdin().lock(),
        &mut std::io::stdout().lock(),
        info,
    )
}

fn preflight() -> Result<Value, String> {
    let output = Command::new("sh")
        .args(["-c", BOOTSTRAP, "crux-bootstrap", "probe"])
        .output()
        .map_err(|e| e.to_string())?;
    String::from_utf8_lossy(&output.stdout)
        .split_inclusive('\n')
        .filter_map(control::decode_line)
        .find_map(|frame| match frame {
            Ok(ControlFrame::Hello { info, .. }) => Some(Ok(info)),
            Err(e) => Some(Err(e)),
            _ => None,
        })
        .unwrap_or_else(|| Err("cannot read remote preflight".into()))
}

pub fn serve_control(
    root: &Path,
    mut input: impl BufRead,
    output: &mut impl Write,
    info: Value,
) -> Result<(), String> {
    fn send(out: &mut impl Write, frame: &ControlFrame) -> Result<(), String> {
        out.write_all(control::encode_frame(frame).as_bytes())
            .and_then(|_| out.flush())
            .map_err(|e| e.to_string())
    }
    send(
        output,
        &ControlFrame::Hello {
            protocol: 1,
            info: info.clone(),
        },
    )?;
    loop {
        let mut line = String::new();
        let count = input
            .by_ref()
            .take(control::MAX_FRAME as u64 + 1)
            .read_line(&mut line)
            .map_err(|e| e.to_string())?;
        if count == 0 {
            return Ok(());
        }
        if count > control::MAX_FRAME {
            return Err("control line exceeds limit".into());
        }
        let Some(frame) = control::decode_line(&line) else {
            continue;
        };
        let frame = frame?;
        let reply = match frame {
            ControlFrame::Hello { .. } => Some(ControlFrame::Hello {
                protocol: 1,
                info: info.clone(),
            }),
            ControlFrame::Preflight { .. } => Some(ControlFrame::Preflight { info: preflight()? }),
            ControlFrame::Heartbeat { epoch } => Some(ControlFrame::Heartbeat { epoch }),
            ControlFrame::ExecReq { id, argv } => {
                let result = exec(&argv).unwrap_or_else(|error| ExecOutput {
                    exit_code: 127,
                    stdout: String::new(),
                    stderr: error,
                });
                Some(ControlFrame::ExecResp {
                    id,
                    exit_code: result.exit_code,
                    stdout: result.stdout,
                    stderr: result.stderr,
                })
            }
            ControlFrame::ReverseProbeReq {
                id,
                endpoint,
                nonce,
                bearer,
            } => {
                let result = probe_reverse(&endpoint, &nonce, bearer.as_deref()).and_then(|()| {
                    if endpoint.starts_with("tcp:") {
                        write_endpoint(
                            &id,
                            &endpoint,
                            bearer
                                .as_deref()
                                .ok_or("reverse TCP requires a session token")?,
                        )?;
                    }
                    Ok(())
                });
                Some(ControlFrame::ReverseProbeResp {
                    id,
                    forward_ok: result.is_ok(),
                    error: result.err(),
                })
            }
            ControlFrame::ArtifactManifest { id, transfer } => {
                Some(ControlFrame::ArtifactManifest {
                    id,
                    transfer: artifacts::handle(root, transfer),
                })
            }
            ControlFrame::Suspending => {
                write_egress(root, "PAUSED_NO_EGRESS", 0)?;
                None
            }
            ControlFrame::Resumed { epoch } => {
                write_egress(root, "RESUMING", epoch)?;
                None
            }
            _ => None,
        };
        if let Some(reply) = reply {
            send(output, &reply)?;
        }
    }
}

fn exec(argv: &[String]) -> Result<ExecOutput, String> {
    let first = argv
        .first()
        .filter(|s| !s.is_empty())
        .ok_or("remote exec requires argv")?;
    if argv.iter().any(|s| s.contains('\0')) {
        return Err("remote argv contains a NUL byte".into());
    }
    let program = if first == "crux" {
        std::env::current_exe().map_err(|e| e.to_string())?
    } else {
        PathBuf::from(first)
    };
    let mut child = Command::new(program)
        .args(&argv[1..])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    // Drain both pipes concurrently; bounded capture prevents unbounded control frames.
    fn capture(mut reader: impl Read) -> String {
        let mut bytes = Vec::new();
        let mut chunk = [0u8; 8192];
        while let Ok(n) = reader.read(&mut chunk) {
            if n == 0 {
                break;
            }
            let keep = n.min(128 * 1024usize - bytes.len());
            bytes.extend_from_slice(&chunk[..keep]);
        }
        let mut text = String::from_utf8_lossy(&bytes).into_owned();
        if bytes.len() == 128 * 1024 {
            text.push_str(
                "\n[Crux Link output limited to 128 KiB; redirect large output to an artifact]\n",
            );
        }
        text
    }
    let stdout = child.stdout.take().ok_or("missing child stdout")?;
    let stderr = child.stderr.take().ok_or("missing child stderr")?;
    let out = std::thread::spawn(move || capture(stdout));
    let err = std::thread::spawn(move || capture(stderr));
    let status = child.wait().map_err(|e| e.to_string())?;
    Ok(ExecOutput {
        exit_code: status.code().unwrap_or(1),
        stdout: out.join().map_err(|_| "stdout reader stopped")?,
        stderr: err.join().map_err(|_| "stderr reader stopped")?,
    })
}

trait ProbeStream: Read + Write {}
impl<T: Read + Write> ProbeStream for T {}
fn probe_reverse(endpoint: &str, nonce: &str, bearer: Option<&str>) -> Result<(), String> {
    if nonce.len() != 32 || !nonce.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("probe nonce must be 16 random bytes encoded as hex".into());
    }
    let mut stream: Box<dyn ProbeStream> = if let Some(address) = endpoint.strip_prefix("tcp:") {
        let address: std::net::SocketAddr = address
            .parse()
            .map_err(|_| "invalid reverse TCP endpoint")?;
        if address.ip() != std::net::Ipv4Addr::LOCALHOST || address.port() == 0 {
            return Err("reverse TCP must bind loopback".into());
        }
        let stream = std::net::TcpStream::connect_timeout(&address, Duration::from_secs(3))
            .map_err(|e| e.to_string())?;
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .map_err(|e| e.to_string())?;
        stream
            .set_write_timeout(Some(Duration::from_secs(3)))
            .map_err(|e| e.to_string())?;
        Box::new(stream)
    } else {
        #[cfg(unix)]
        {
            let stream =
                std::os::unix::net::UnixStream::connect(endpoint).map_err(|e| e.to_string())?;
            stream
                .set_read_timeout(Some(Duration::from_secs(3)))
                .map_err(|e| e.to_string())?;
            stream
                .set_write_timeout(Some(Duration::from_secs(3)))
                .map_err(|e| e.to_string())?;
            Box::new(stream)
        }
        #[cfg(not(unix))]
        {
            return Err("remote Unix sockets require Linux or macOS".into());
        }
    };
    let token = bearer.unwrap_or("");
    if token.contains(['\r', '\n']) {
        return Err("invalid reverse token".into());
    }
    write!(stream,"GET /v1/egress/nonce HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n").map_err(|e| e.to_string())?;
    let mut response = String::new();
    stream
        .take(8193)
        .read_to_string(&mut response)
        .map_err(|e| e.to_string())?;
    let (head, body) = response
        .split_once("\r\n\r\n")
        .ok_or("invalid reverse probe response")?;
    if response.len() > 8192 || !head.starts_with("HTTP/1.1 200 ") || body.trim() != nonce {
        return Err("reverse probe nonce mismatch".into());
    }
    Ok(())
}

fn write_endpoint(id: &str, endpoint: &str, token: &str) -> Result<PathBuf, String> {
    if id.len() > 64
        || !id.bytes().all(|b| b.is_ascii_alphanumeric())
        || token.len() != 64
        || !token.bytes().all(|b| b.is_ascii_hexdigit())
    {
        return Err("invalid endpoint session".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt, PermissionsExt};
        let uid = unsafe { libc::geteuid() };
        let runtime = PathBuf::from(format!("/run/user/{uid}"));
        let metadata=std::fs::symlink_metadata(&runtime).map_err(|_| "reverse TCP needs a private /run/user/$UID directory; enable the user runtime directory")?;
        if metadata.file_type().is_symlink()
            || metadata.uid() != uid
            || metadata.mode() & 0o077 != 0
        {
            return Err("reverse runtime directory is not private".into());
        }
        let dir = runtime.join(format!("crux-{id}"));
        std::fs::DirBuilder::new()
            .mode(0o700)
            .create(&dir)
            .map_err(|e| e.to_string())?;
        let path = dir.join("llm.endpoint");
        let mut file = std::fs::OpenOptions::new()
            .create_new(true)
            .write(true)
            .mode(0o600)
            .open(&path)
            .map_err(|e| e.to_string())?;
        file.write_all(
            json!({"url":format!("http://{}",endpoint.trim_start_matches("tcp:")),"token":token})
                .to_string()
                .as_bytes(),
        )
        .map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))
            .map_err(|e| e.to_string())?;
        Ok(path)
    }
    #[cfg(not(unix))]
    {
        Err("reverse endpoint installation requires a Unix remote host".into())
    }
}
fn write_egress(root: &Path, state: &str, epoch: u64) -> Result<(), String> {
    let crux = root.join(".crux");
    let legacy = root.join(".coral");
    if crux.exists() && legacy.exists() {
        return Err("both .crux and .coral exist".into());
    }
    let dir = if legacy.exists() { legacy } else { crux };
    let relative = format!(
        "{}/public/views/egress.json",
        dir.file_name().unwrap().to_string_lossy()
    );
    let target = artifacts::scoped_path(root, &relative)?;
    osd_core::runtime::write_atomic(
        &target,
        &json!({"state":state,"mode":"tunnel","epoch":epoch}).to_string(),
    )
}
fn agent_env() -> Result<osd_core::Env, String> {
    osd_core::Env::headless(None, None, env!("CARGO_PKG_VERSION").into())
}
fn ensure_gateway() -> Result<(u16, String), String> {
    let env = agent_env()?;
    let existing = osd_core::gateway::read_persisted(&env);
    if let Some(port) = existing
        .port
        .filter(|p| osd_core::gateway::port_is_answering(*p))
    {
        return Ok((port, osd_core::gateway::ensure_token(&env, None)?));
    }
    let mut command = Command::new(std::env::current_exe().map_err(|e| e.to_string())?);
    command
        .args(["link-agent", "--gateway-daemon"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        unsafe {
            command.pre_exec(|| {
                if libc::setsid() == -1 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
    }
    let mut child = command.spawn().map_err(|e| e.to_string())?;
    for _ in 0..100 {
        if let Some(port) = osd_core::gateway::read_persisted(&env)
            .port
            .filter(|p| osd_core::gateway::port_is_answering(*p))
        {
            return Ok((port, osd_core::gateway::ensure_token(&env, None)?));
        }
        if child.try_wait().map_err(|e| e.to_string())?.is_some() {
            return Err("remote gateway could not start".into());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
    let _ = child.wait();
    Err("remote gateway startup timed out".into())
}
fn gateway_daemon() -> Result<(), String> {
    let env = agent_env()?;
    let runtime = osd_core::runtime::runtime_root(&env)?;
    std::fs::create_dir_all(&runtime).map_err(|e| e.to_string())?;
    osd_core::runtime::tighten_private(&runtime);
    let lock_path = runtime.join("link-gateway.lock");
    let lock = std::fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(lock_path)
        .map_err(|e| e.to_string())?;
    if lock.try_lock().is_err() {
        return Ok(());
    }
    let state = osd_core::gateway::GatewayState::default();
    let mut config = osd_core::gateway::read_persisted(&env);
    config.token = osd_core::gateway::ensure_token(&env, None)?;
    config.lan = false;
    config.enabled = true;
    config.mode = "full".into();
    osd_core::gateway::start_at(&env, &state, &config, Some(0))?;
    let pid = osd_core::runtime::runtime_root(&env)?.join("link-gateway.pid");
    osd_core::runtime::write_atomic(&pid, &std::process::id().to_string())?;
    loop {
        std::thread::park();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn link_agent_starts_a_gateway_in_a_fresh_state_directory() {
        const CHILD: &str = "CRUX_LINK_GATEWAY_TEST_CHILD";
        if std::env::var_os(CHILD).is_some() {
            run_link_agent(&["--gateway-daemon".into()]).unwrap();
            return;
        }
        struct Cleanup {
            child: std::process::Child,
            root: PathBuf,
        }
        impl Drop for Cleanup {
            fn drop(&mut self) {
                let _ = self.child.kill();
                let _ = self.child.wait();
                let _ = std::fs::remove_dir_all(&self.root);
            }
        }
        let root = std::env::temp_dir().join(format!(
            "crux-link-gateway-{}",
            osd_core::runtime::random_hex(8)
        ));
        let child = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "link_agent::tests::link_agent_starts_a_gateway_in_a_fresh_state_directory",
            ])
            .env(CHILD, "1")
            .env("CRUX_STATE_DIR", &root)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap();
        let mut cleanup = Cleanup {
            child,
            root: root.clone(),
        };
        let env = osd_core::Env::new(root.clone(), root.clone(), None, "test".into());
        let mut port = None;
        for _ in 0..100 {
            port = osd_core::gateway::read_persisted(&env)
                .port
                .filter(|p| osd_core::gateway::port_is_answering(*p));
            if port.is_some() {
                break;
            }
            assert!(
                cleanup.child.try_wait().unwrap().is_none(),
                "link gateway exited before startup"
            );
            std::thread::sleep(Duration::from_millis(20));
        }
        let port = port.expect("fresh link gateway started");
        let response = reqwest::blocking::Client::builder()
            .no_proxy()
            .build()
            .unwrap()
            .get(format!("http://127.0.0.1:{port}/v1/health"))
            .send()
            .unwrap();
        assert_eq!(response.status().as_u16(), 200);
        assert!(response.text().unwrap().contains("open-science-gateway"));
    }

    #[test]
    fn stdio_handles_banners_argv_heartbeat_and_exec_errors() {
        let input = format!(
            "cluster MOTD\n{}{}{}",
            control::encode_frame(&ControlFrame::Heartbeat { epoch: 7 }),
            control::encode_frame(&ControlFrame::ExecReq {
                id: "bad".into(),
                argv: vec!["crux-program-that-does-not-exist".into()]
            }),
            control::encode_frame(&ControlFrame::Hello {
                protocol: 1,
                info: Value::Null
            })
        );
        let mut output = Vec::new();
        serve_control(
            Path::new("."),
            std::io::Cursor::new(input),
            &mut output,
            json!({"ready":true}),
        )
        .unwrap();
        let text = String::from_utf8(output).unwrap();
        let frames: Vec<_> = text
            .split_inclusive('\n')
            .filter_map(control::decode_line)
            .map(Result::unwrap)
            .collect();
        assert_eq!(frames.len(), 4);
        assert_eq!(frames[1], ControlFrame::Heartbeat { epoch: 7 });
        assert!(matches!(&frames[2],ControlFrame::ExecResp {exit_code:127,id,..} if id=="bad"));
    }
    #[test]
    fn functional_reverse_probe_checks_real_nonce_and_session_auth() {
        let broker = osd_core::egress_broker::EgressBroker::start(None).unwrap();
        let endpoint = format!("tcp:127.0.0.1:{}", broker.port());
        assert!(probe_reverse(&endpoint, broker.nonce(), Some(broker.token())).is_ok());
        assert!(probe_reverse(
            &endpoint,
            "00000000000000000000000000000000",
            Some(broker.token())
        )
        .is_err());
        assert!(probe_reverse(&endpoint, broker.nonce(), Some("wrong-token")).is_err());
        assert!(probe_reverse("tcp:0.0.0.0:1234", broker.nonce(), Some(broker.token())).is_err());
    }
    #[cfg(unix)]
    #[test]
    fn exec_preserves_literal_metacharacters() {
        let out = exec(&[
            "printf".into(),
            "%s".into(),
            "$(touch /tmp/never-execute) & ^ ! % '".into(),
        ])
        .unwrap();
        assert_eq!(out.exit_code, 0);
        assert_eq!(out.stdout, "$(touch /tmp/never-execute) & ^ ! % '");
    }
}
