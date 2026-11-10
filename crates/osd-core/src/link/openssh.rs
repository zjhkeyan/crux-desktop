//! OpenSSH owns all three channels; Windows never needs ControlMaster.
use super::{
    artifacts::{ArtifactEntry, ArtifactTransfer, CHUNK_SIZE},
    control::{self, ControlFrame},
    ExecOutput, LinkStatus, LinkTransport, BOOTSTRAP,
};
use crate::{
    remote_hosts::{self, RemoteHostProfile},
    Env,
};
use serde_json::Value;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Stdio};
use std::sync::{
    atomic::{AtomicBool, AtomicU16, Ordering},
    mpsc::{self, Receiver},
    Arc, Mutex,
};
use std::time::{Duration, Instant};

#[derive(Clone)]
pub struct BootstrapArtifact {
    pub path: PathBuf,
    pub version: String,
    pub sha256: String,
}
#[derive(Clone)]
pub struct ReverseForward {
    pub socket: String,
    pub local_port: u16,
    pub bearer: String,
    pub nonce: String,
}
#[derive(Clone)]
pub struct OpenSshConfig {
    pub host: RemoteHostProfile,
    pub known_hosts: PathBuf,
    pub ssh_bin: PathBuf,
    pub gateway_forward: Option<(u16, String)>,
    pub reverse: Option<ReverseForward>,
    pub bootstrap: Option<BootstrapArtifact>,
    pub timeout: Duration,
}
impl OpenSshConfig {
    pub fn new(env: &Env, host: RemoteHostProfile) -> Result<Self, String> {
        host.validate()?;
        Ok(Self {
            host,
            known_hosts: remote_hosts::known_hosts_path(env)?,
            ssh_bin: resolve_ssh(Some(env))?,
            gateway_forward: None,
            reverse: None,
            bootstrap: None,
            timeout: Duration::from_secs(180),
        })
    }
}

pub fn resolve_ssh(env: Option<&Env>) -> Result<PathBuf, String> {
    if let Some(path) = std::env::var_os("CRUX_SSH_BIN").filter(|s| !s.is_empty()) {
        let path = PathBuf::from(path);
        return path
            .is_file()
            .then_some(path)
            .ok_or_else(|| "CRUX_SSH_BIN does not name an SSH executable".into());
    }
    if let Some(env) = env {
        for name in [
            "win32-openssh/ssh.exe",
            "binaries/ssh.exe",
            "ssh.exe",
            "ssh",
        ] {
            if let Some(path) = env.resource(name) {
                return Ok(path);
            }
        }
    }
    if let Some(path) = crate::runtime::sidecar_bin("ssh") {
        return Ok(path);
    }
    #[cfg(windows)]
    {
        let path =
            PathBuf::from(std::env::var_os("SystemRoot").unwrap_or_else(|| "C:\\Windows".into()))
                .join("System32/OpenSSH/ssh.exe");
        if path.is_file() {
            return Ok(path);
        }
    }
    crate::which::find_on_path("ssh", Some(&crate::runtime::enriched_path()))
        .ok_or_else(|| "OpenSSH is missing; install the bundled SSH component".into())
}

/// Exposed for platform-independent verification of forwarding and quoting.
pub fn build_ssh_args(config: &OpenSshConfig, tcp_fallback: bool) -> Result<Vec<String>, String> {
    config.host.validate()?;
    let mut args: Vec<String> = [
        "-T",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "StreamLocalBindUnlink=yes",
        "-o",
        "StreamLocalBindMask=0177",
        "-o",
        "ConnectTimeout=15",
        "-o",
        if config.host.host_key_fingerprint.is_some() {
            "StrictHostKeyChecking=yes"
        } else {
            "StrictHostKeyChecking=accept-new"
        },
        "-o",
    ]
    .iter()
    .map(|s| (*s).into())
    .collect();
    args.push(format!(
        "UserKnownHostsFile={}",
        remote_hosts::ssh_option_path(&config.known_hosts)
    ));
    args.extend(["-p".into(), config.host.port.to_string()]);
    if let Some(jump) = &config.host.jump_host {
        args.extend(["-J".into(), jump.clone()]);
    }
    if let Some(key) = &config.host.paired_key_path {
        args.extend(["-i".into(), key.clone()]);
    }
    if let Some((port, target)) = &config.gateway_forward {
        if *port == 0 || target.is_empty() || target.contains(['\n', '\r', '\0']) {
            return Err("invalid gateway forward".into());
        }
        args.extend(["-L".into(), format!("127.0.0.1:{port}:{target}")]);
    }
    if let Some(reverse) = &config.reverse {
        if !reverse.socket.starts_with('/')
            || reverse.socket.contains([':', '\n', '\r', '\0'])
            || reverse.local_port == 0
        {
            return Err("invalid reverse forward".into());
        }
        let listen = if tcp_fallback {
            "127.0.0.1:0"
        } else {
            reverse.socket.as_str()
        };
        args.extend([
            "-R".into(),
            format!("{listen}:127.0.0.1:{}", reverse.local_port),
        ]);
    }
    args.push(config.host.destination());
    Ok(args)
}

/// A separate owner can stop SSH while another thread is awaiting a control reply.
#[derive(Clone, Default)]
pub struct LinkCancellation {
    child: Arc<Mutex<Option<Child>>>,
    cancelled: Arc<AtomicBool>,
}
impl LinkCancellation {
    pub fn cancel(&self) -> Result<(), String> {
        self.cancelled.store(true, Ordering::Release);
        self.stop()
    }
    fn stop(&self) -> Result<(), String> {
        let child = self.child.lock().map_err(|e| e.to_string())?.take();
        if let Some(mut child) = child {
            let _ = child.kill();
            child.wait().map_err(|e| e.to_string())?;
        }
        Ok(())
    }
}

pub struct OpenSshTransport {
    config: OpenSshConfig,
    process: LinkCancellation,
    input: Option<ChildStdin>,
    frames: Option<Receiver<Result<ControlFrame, String>>>,
    allocated_port: Arc<AtomicU16>,
    errors: Arc<Mutex<String>>,
    state: LinkStatus,
    tcp_fallback: bool,
    hello: Option<ControlFrame>,
    alive: Arc<AtomicBool>,
}
impl OpenSshTransport {
    pub fn new(config: OpenSshConfig) -> Self {
        Self {
            config,
            process: LinkCancellation::default(),
            input: None,
            frames: None,
            allocated_port: Arc::new(AtomicU16::new(0)),
            errors: Arc::default(),
            state: LinkStatus::Disconnected,
            tcp_fallback: false,
            hello: None,
            alive: Arc::new(AtomicBool::new(false)),
        }
    }
    pub fn preflight(config: OpenSshConfig) -> Result<Value, String> {
        let mut transport = Self::new(config);
        transport.config.reverse = None;
        transport.config.gateway_forward = None;
        transport.spawn(true)?;
        let result = match transport.receive()? {
            ControlFrame::Hello { info, .. } => Ok(info),
            _ => Err("remote returned no preflight information".into()),
        };
        transport.disconnect()?;
        result
    }
    pub fn cancellation(&self) -> LinkCancellation {
        self.process.clone()
    }
    pub fn config(&self) -> &OpenSshConfig {
        &self.config
    }
    fn spawn(&mut self, probe_only: bool) -> Result<(), String> {
        if self.process.cancelled.load(Ordering::Acquire) {
            return Err("SSH link was cancelled".into());
        }
        self.state = LinkStatus::Connecting;
        self.allocated_port = Arc::new(AtomicU16::new(0));
        self.errors = Arc::default();
        self.alive = Arc::new(AtomicBool::new(false));
        let blob = if let Some(artifact) = &self.config.bootstrap {
            if artifact.version.is_empty()
                || !artifact
                    .version
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
            {
                return Err("invalid bootstrap version".into());
            }
            let parent = artifact.path.parent().unwrap_or(Path::new("."));
            let entry = super::artifacts::describe(
                parent,
                artifact
                    .path
                    .file_name()
                    .and_then(|s| s.to_str())
                    .ok_or("invalid bootstrap path")?,
            )?;
            if entry.sha256 != artifact.sha256 {
                return Err("local bootstrap binary SHA256 mismatch".into());
            }
            #[cfg(not(windows))]
            let out = crate::runtime::quiet_command("gzip")
                .args(["-c", "--"])
                .arg(&artifact.path)
                .output();
            #[cfg(windows)]
            let out = crate::runtime::quiet_command("powershell.exe")
                .args(["-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; $inputFile=[IO.File]::OpenRead($env:CRUX_LINK_BINARY_PATH); $gzip=[IO.Compression.GZipStream]::new([Console]::OpenStandardOutput(),[IO.Compression.CompressionMode]::Compress,$true); try {$inputFile.CopyTo($gzip)} finally {$gzip.Dispose(); $inputFile.Dispose()}"])
                .env("CRUX_LINK_BINARY_PATH", &artifact.path).output();
            let out = out.map_err(|e| format!("cannot compress Crux binary: {e}"))?;
            if !out.status.success() {
                return Err("cannot compress Crux binary".into());
            }
            Some(out.stdout)
        } else {
            None
        };
        let mut args = build_ssh_args(&self.config, self.tcp_fallback)?;
        let artifact = self.config.bootstrap.as_ref();
        let command = format!(
            "sh -c {} crux-bootstrap {} {} {} {}",
            remote_hosts::shell_quote(BOOTSTRAP),
            if probe_only { "probe" } else { "connect" },
            remote_hosts::shell_quote(
                artifact
                    .map(|a| a.version.as_str())
                    .unwrap_or(env!("CARGO_PKG_VERSION"))
            ),
            remote_hosts::shell_quote(artifact.map(|a| a.sha256.as_str()).unwrap_or("")),
            blob.as_ref().map_or(0, Vec::len)
        );
        args.push(command);
        let mut child = crate::runtime::quiet_command(&self.config.ssh_bin)
            .args(args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| e.to_string())?;
        let input = child.stdin.take().ok_or("SSH stdin missing")?;
        let stdout = child.stdout.take().ok_or("SSH stdout missing")?;
        let stderr = child.stderr.take().ok_or("SSH stderr missing")?;
        let (tx, rx) = mpsc::channel();
        let alive = self.alive.clone();
        alive.store(true, Ordering::Release);
        std::thread::spawn(move || {
            let mut reader = BufReader::new(stdout);
            loop {
                let mut line = String::new();
                match reader
                    .by_ref()
                    .take(control::MAX_FRAME as u64 + 1)
                    .read_line(&mut line)
                {
                    Ok(0) => break,
                    Ok(_) if line.len() > control::MAX_FRAME => {
                        let _ = tx.send(Err("SSH control line exceeds limit".into()));
                        break;
                    }
                    Ok(_) => {
                        if let Some(frame) = control::decode_line(&line) {
                            if tx.send(frame).is_err() {
                                break;
                            }
                        }
                    }
                    Err(e) => {
                        let _ = tx.send(Err(e.to_string()));
                        break;
                    }
                }
            }
            alive.store(false, Ordering::Release);
        });
        let port = self.allocated_port.clone();
        let errors = self.errors.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                if let Some(rest) = line.strip_prefix("Allocated port ") {
                    if let Some(n) = rest.split_whitespace().next().and_then(|n| n.parse().ok()) {
                        port.store(n, Ordering::Release);
                    }
                }
                let mut text = errors.lock().unwrap();
                if text.len() + line.len() < 8192 {
                    text.push_str(&line);
                    text.push('\n');
                }
            }
        });
        {
            let mut process = self.process.child.lock().map_err(|e| e.to_string())?;
            if self.process.cancelled.load(Ordering::Acquire) {
                let _ = child.kill();
                let _ = child.wait();
                return Err("SSH link was cancelled".into());
            }
            *process = Some(child);
        }
        self.input = Some(input);
        self.frames = Some(rx);
        // Wait for hello before writing: cached binaries must not receive blob bytes.
        let hello = self.receive()?;
        let installed = match &hello {
            ControlFrame::Hello { info, .. } => info["installed"].as_bool().unwrap_or(false),
            _ => return Err("SSH bootstrap did not report hello".into()),
        };
        // Preserve hello for the caller while finishing the install/agent handshake.
        if !probe_only && !installed {
            let blob = blob.ok_or(
                "remote Crux is missing; provide a verified Linux binary for the bootstrap",
            )?;
            self.input
                .as_mut()
                .ok_or("SSH disconnected")?
                .write_all(&blob)
                .map_err(|e| e.to_string())?;
        }
        // A single cached hello keeps receive semantics identical for probe/connect.
        self.hello = Some(hello);
        Ok(())
    }
    pub fn receive(&mut self) -> Result<ControlFrame, String> {
        self.next_frame(Some(self.config.timeout))
    }
    fn next_frame(&mut self, timeout: Option<Duration>) -> Result<ControlFrame, String> {
        if let Some(hello) = self.hello.take() {
            return Ok(hello);
        }
        let frames = self.frames.as_ref().ok_or("SSH is disconnected")?;
        let result = match timeout {
            Some(timeout) => frames.recv_timeout(timeout).map_err(|e| e.to_string()),
            None => frames.recv().map_err(|e| e.to_string()),
        };
        result.map_err(|e| {
            format!(
                "SSH control channel ended ({e}); {}",
                self.errors.lock().unwrap().trim()
            )
        })?
    }
    pub fn artifact(&mut self, transfer: ArtifactTransfer) -> Result<ArtifactTransfer, String> {
        let id = crate::runtime::random_hex(8);
        self.send_control(&ControlFrame::ArtifactManifest {
            id: id.clone(),
            transfer,
        })?;
        loop {
            if let ControlFrame::ArtifactManifest { id: got, transfer } = self.receive()? {
                if got == id {
                    if let ArtifactTransfer::Result {
                        error: Some(error), ..
                    } = &transfer
                    {
                        return Err(error.clone());
                    }
                    return Ok(transfer);
                }
            }
        }
    }
    pub fn put(
        &mut self,
        root: &Path,
        source: &str,
        destination: &str,
    ) -> Result<ArtifactEntry, String> {
        let source_entry = super::artifacts::describe(root, source)?;
        let mut entry = source_entry.clone();
        entry.path = destination.into();
        let mut offset = 0;
        loop {
            let data = super::artifacts::read_chunk(root, &source_entry, offset)?;
            self.artifact(ArtifactTransfer::Write {
                entry: entry.clone(),
                offset,
                data,
            })?;
            if offset + CHUNK_SIZE as u64 >= entry.size {
                break;
            }
            offset += CHUNK_SIZE as u64;
        }
        self.artifact(ArtifactTransfer::Complete {
            entry: entry.clone(),
        })?;
        Ok(entry)
    }
    pub fn get(
        &mut self,
        source: &str,
        root: &Path,
        destination: &str,
    ) -> Result<ArtifactEntry, String> {
        let response = self.artifact(ArtifactTransfer::Stat {
            path: source.into(),
        })?;
        let ArtifactTransfer::Result { entries, .. } = response else {
            return Err("invalid artifact manifest".into());
        };
        let remote = entries.first().ok_or("remote artifact missing")?.clone();
        let mut entry = remote.clone();
        entry.path = destination.into();
        let mut offset = 0;
        loop {
            let response = self.artifact(ArtifactTransfer::Read {
                entry: remote.clone(),
                offset,
            })?;
            let ArtifactTransfer::Result {
                data: Some(data), ..
            } = response
            else {
                return Err("remote artifact data missing".into());
            };
            super::artifacts::write_chunk(root, &entry, offset, &data)?;
            if offset + CHUNK_SIZE as u64 >= entry.size {
                break;
            }
            offset += CHUNK_SIZE as u64;
        }
        super::artifacts::complete(root, &entry)?;
        Ok(entry)
    }
    fn probe(
        &mut self,
        endpoint: String,
        nonce: &str,
        bearer: Option<String>,
    ) -> Result<bool, String> {
        let id = crate::runtime::random_hex(8);
        self.send_control(&ControlFrame::ReverseProbeReq {
            id: id.clone(),
            endpoint,
            nonce: nonce.into(),
            bearer,
        })?;
        loop {
            if let ControlFrame::ReverseProbeResp {
                id: got,
                forward_ok,
                ..
            } = self.receive()?
            {
                if got == id {
                    return Ok(forward_ok);
                }
            }
        }
    }
    fn connect_once(&mut self) -> Result<Value, String> {
        self.spawn(false)?;
        let mut hello = match self.receive()? {
            ControlFrame::Hello { info, .. } => info,
            _ => return Err("no bootstrap hello".into()),
        };
        loop {
            if let ControlFrame::Hello { protocol, info } = self.receive()? {
                if protocol != 1 {
                    return Err("unsupported Crux Link protocol".into());
                }
                hello["agent"] = info;
                break;
            }
        }
        self.state = LinkStatus::Connected;
        Ok(hello)
    }
}
impl LinkTransport for OpenSshTransport {
    fn connect(&mut self) -> Result<Value, String> {
        self.disconnect()?;
        if self.config.reverse.is_none() {
            let result = self.connect_once();
            if result.is_err() {
                self.disconnect()?;
            }
            return result;
        }
        static TCP_HOSTS: std::sync::OnceLock<Mutex<std::collections::HashSet<String>>> =
            std::sync::OnceLock::new();
        let cache = TCP_HOSTS.get_or_init(Mutex::default);
        let version = crate::runtime::quiet_command(&self.config.ssh_bin)
            .arg("-V")
            .output()
            .map_err(|e| e.to_string())?;
        let key = format!(
            "{}:{}:{}:{}",
            self.config.ssh_bin.display(),
            String::from_utf8_lossy(&version.stderr),
            self.config.host.destination(),
            self.config.host.port
        );
        self.tcp_fallback = cache.lock().map_err(|e| e.to_string())?.contains(&key);
        let result = (|| {
            if !self.tcp_fallback {
                match self.connect_once() {
                    Ok(mut hello) => {
                        let reverse = self.config.reverse.clone().unwrap();
                        if self.probe_reverse_uds(&reverse.nonce).unwrap_or(false) {
                            hello["reverse_mode"] = Value::String("uds".into());
                            return Ok(hello);
                        }
                    }
                    Err(error) => {
                        let log = self.errors.lock().unwrap().to_lowercase();
                        if ![
                            "remote port forwarding failed",
                            "remote forwarding failed",
                            "streamlocal",
                            "administratively prohibited",
                        ]
                        .iter()
                        .any(|s| log.contains(s))
                        {
                            return Err(error);
                        }
                    }
                }
                self.disconnect()?;
                self.tcp_fallback = true;
            }
            let mut hello = self.connect_once()?;
            let deadline = Instant::now() + Duration::from_secs(3);
            while self.allocated_port.load(Ordering::Acquire) == 0 && Instant::now() < deadline {
                std::thread::sleep(Duration::from_millis(10));
            }
            let port = self.allocated_port.load(Ordering::Acquire);
            if port == 0 {
                return Err(
                    "SSH did not allocate a reverse TCP port; install the bundled SSH component"
                        .into(),
                );
            }
            let reverse = self.config.reverse.clone().unwrap();
            if !self.probe(
                format!("tcp:127.0.0.1:{port}"),
                &reverse.nonce,
                Some(reverse.bearer),
            )? {
                return Err(
                    "reverse egress probe failed; install the bundled SSH component".into(),
                );
            }
            cache.lock().map_err(|e| e.to_string())?.insert(key);
            hello["reverse_mode"] = Value::String("tcp".into());
            Ok(hello)
        })();
        if result.is_err() {
            self.disconnect()?;
        }
        result
    }
    fn send_control(&mut self, frame: &ControlFrame) -> Result<(), String> {
        let input = self.input.as_mut().ok_or("SSH is disconnected")?;
        let encoded = control::encode_frame(frame);
        if encoded.len() > control::MAX_FRAME {
            return Err("control frame exceeds 2 MiB".into());
        }
        input
            .write_all(encoded.as_bytes())
            .and_then(|_| input.flush())
            .map_err(|e| e.to_string())
    }
    fn exec_remote(&mut self, argv: &[String]) -> Result<ExecOutput, String> {
        if argv.is_empty() || argv.iter().any(|s| s.contains('\0')) {
            return Err("remote exec requires argv without NUL bytes".into());
        }
        let id = crate::runtime::random_hex(8);
        self.send_control(&ControlFrame::ExecReq {
            id: id.clone(),
            argv: argv.to_vec(),
        })?;
        loop {
            if let ControlFrame::ExecResp {
                id: got,
                exit_code,
                stdout,
                stderr,
            } = self.next_frame(None)?
            {
                if got == id {
                    return Ok(ExecOutput {
                        exit_code,
                        stdout,
                        stderr,
                    });
                }
            }
        }
    }
    fn probe_reverse_uds(&mut self, nonce: &str) -> Result<bool, String> {
        let reverse = self
            .config
            .reverse
            .clone()
            .ok_or("egress reverse forwarding is not configured")?;
        self.probe(reverse.socket, nonce, Some(reverse.bearer))
    }
    fn disconnect(&mut self) -> Result<(), String> {
        self.alive.store(false, Ordering::Release);
        self.input.take();
        self.frames.take();
        self.hello.take();
        self.process.stop()?;
        self.state = LinkStatus::Disconnected;
        Ok(())
    }
    fn status(&self) -> LinkStatus {
        if self.process.child.lock().is_ok_and(|child| child.is_some())
            && self.alive.load(Ordering::Acquire)
        {
            self.state.clone()
        } else {
            LinkStatus::Disconnected
        }
    }
}
impl Drop for OpenSshTransport {
    fn drop(&mut self) {
        let _ = self.disconnect();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[cfg(unix)]
    #[test]
    fn public_transport_probes_falls_back_and_reuses_the_host_capability() {
        use std::os::unix::fs::PermissionsExt;
        struct Temp(PathBuf);
        impl Drop for Temp {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
        let temp = Temp(
            std::env::temp_dir().join(format!("crux-ssh-test-{}", crate::runtime::random_hex(8))),
        );
        std::fs::create_dir_all(&temp.0).unwrap();
        let log = temp.0.join("connections");
        let script = r##"#!/usr/bin/python3
import json, subprocess, sys, time
if sys.argv[-1] == '-V':
    print('OpenSSH_test_1', file=sys.stderr)
    sys.exit(0)
tcp = any(arg.startswith('127.0.0.1:0:') for arg in sys.argv)
with open(LOG, 'a') as log:
    log.write('tcp\n' if tcp else 'uds\n')
if tcp:
    print('Allocated port 45555 for remote forward', file=sys.stderr, flush=True)
def send(frame):
    print('\x1eCRUX1 ' + json.dumps(frame), flush=True)
send({'t':'hello','protocol':1,'info':{'installed':True}})
send({'t':'hello','protocol':1,'info':{'ready':True}})
for line in sys.stdin:
    if not line.startswith('\x1eCRUX1 '):
        continue
    frame = json.loads(line[len('\x1eCRUX1 '):])
    if frame['t'] == 'reverse_probe_req':
        send({'t':'reverse_probe_resp','id':frame['id'],'forward_ok':tcp,'error':None})
    elif frame['t'] == 'heartbeat':
        send(frame)
    elif frame['t'] == 'exec_req':
        if frame['argv'] == ['stall']:
            time.sleep(60)
        out = subprocess.run(frame['argv'], capture_output=True, text=True)
        send({'t':'exec_resp','id':frame['id'],'exit_code':out.returncode,'stdout':out.stdout,'stderr':out.stderr})
"##.replace("LOG", &serde_json::to_string(&log.to_string_lossy()).unwrap());
        let ssh = temp.0.join("ssh");
        std::fs::write(&ssh, script).unwrap();
        std::fs::set_permissions(&ssh, std::fs::Permissions::from_mode(0o700)).unwrap();
        let host = serde_json::from_value(serde_json::json!({"id":"test", "label":"test", "host":format!("hpc-{}",crate::runtime::random_hex(8)),"user":"alice"})).unwrap();
        let config = OpenSshConfig {
            host,
            known_hosts: temp.0.join("known_hosts"),
            ssh_bin: ssh,
            gateway_forward: None,
            reverse: Some(ReverseForward {
                socket: "/tmp/crux-test.sock".into(),
                local_port: 9000,
                bearer: "a".repeat(64),
                nonce: "b".repeat(32),
            }),
            bootstrap: None,
            timeout: Duration::from_secs(5),
        };
        let mut transport = OpenSshTransport::new(config);
        assert_eq!(transport.connect().unwrap()["reverse_mode"], "tcp");
        assert_eq!(transport.status(), LinkStatus::Connected);
        let output = transport
            .exec_remote(&[
                "printf".into(),
                "%s".into(),
                "literal & ^ ! $(no-shell)".into(),
            ])
            .unwrap();
        assert_eq!(output.stdout, "literal & ^ ! $(no-shell)");
        transport
            .send_control(&ControlFrame::Heartbeat { epoch: 9 })
            .unwrap();
        assert_eq!(
            transport.receive().unwrap(),
            ControlFrame::Heartbeat { epoch: 9 }
        );
        transport.disconnect().unwrap();
        assert_eq!(transport.status(), LinkStatus::Disconnected);
        transport.connect().unwrap();
        let cancellation = transport.cancellation();
        let canceller = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(100));
            cancellation.cancel().unwrap();
        });
        assert!(transport.exec_remote(&["stall".into()]).is_err());
        canceller.join().unwrap();
        transport.disconnect().unwrap();
        assert_eq!(transport.status(), LinkStatus::Disconnected);
        assert_eq!(std::fs::read_to_string(log).unwrap(), "uds\ntcp\ntcp\n");
    }

    #[test]
    fn one_ssh_process_carries_all_three_channels_with_loopback_fallback() {
        let host = serde_json::from_value(
            serde_json::json!({"id":"hpc","label":"HPC","host":"login","user":"alice"}),
        )
        .unwrap();
        let mut config = OpenSshConfig {
            host,
            known_hosts: PathBuf::from("C:/Crux Data/known_hosts"),
            ssh_bin: PathBuf::from("ssh.exe"),
            gateway_forward: Some((8123, "/run/user/1000/crux.sock".into())),
            reverse: Some(ReverseForward {
                socket: "/tmp/crux-random.sock".into(),
                local_port: 9000,
                bearer: "token".into(),
                nonce: "nonce".into(),
            }),
            bootstrap: None,
            timeout: Duration::from_secs(5),
        };
        let args = build_ssh_args(&config, false).unwrap();
        assert!(args
            .windows(2)
            .any(|a| a == ["-L", "127.0.0.1:8123:/run/user/1000/crux.sock"]));
        assert!(args
            .windows(2)
            .any(|a| a == ["-R", "/tmp/crux-random.sock:127.0.0.1:9000"]));
        assert!(args.contains(&"ControlPath=none".into()));
        assert!(args.contains(&"ExitOnForwardFailure=yes".into()));
        assert!(build_ssh_args(&config, true)
            .unwrap()
            .contains(&"127.0.0.1:0:127.0.0.1:9000".into()));
        config.host.host = "-oProxyCommand=evil".into();
        assert!(build_ssh_args(&config, false).is_err());
    }
}
