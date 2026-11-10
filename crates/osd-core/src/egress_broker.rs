//! Loopback-only provider proxy. Provider secrets never cross the SSH boundary.
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::{
    atomic::{AtomicBool, AtomicU64, Ordering},
    Arc, Mutex,
};
use std::thread::JoinHandle;
use std::time::Duration;

pub type CredentialRefresher = Arc<dyn Fn() -> Result<String, String> + Send + Sync>;

pub struct ProviderCredential {
    pub base_url: String,
    pub key: String,
    /// `authorization` for bearer providers, `x-api-key` for Anthropic.
    pub header: String,
    pub refresh: Option<CredentialRefresher>,
}
struct Provider {
    credential: Mutex<ProviderCredential>,
    state: Mutex<&'static str>,
}
struct Budget {
    max: Option<f64>,
    accumulated: f64,
}
struct Shared {
    epoch: AtomicU64,
    token: String,
    nonce: String,
    budget: Mutex<Budget>,
    providers: Mutex<HashMap<String, Arc<Provider>>>,
    client: reqwest::blocking::Client,
    stop: AtomicBool,
}
pub struct EgressBroker {
    address: SocketAddr,
    shared: Arc<Shared>,
    worker: Option<JoinHandle<()>>,
}
impl EgressBroker {
    pub fn start(max_cost_usd: Option<f64>) -> Result<Self, String> {
        validate_cost(max_cost_usd)?;
        let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
        let address = listener.local_addr().map_err(|e| e.to_string())?;
        let shared = Arc::new(Shared {
            epoch: AtomicU64::new(1),
            token: crate::runtime::random_hex(32),
            nonce: crate::runtime::random_hex(16),
            budget: Mutex::new(Budget {
                max: max_cost_usd,
                accumulated: 0.0,
            }),
            providers: Mutex::default(),
            client: reqwest::blocking::Client::builder()
                .redirect(reqwest::redirect::Policy::none())
                .connect_timeout(Duration::from_secs(15))
                .timeout(Duration::from_secs(6 * 3600))
                .build()
                .map_err(|e| e.to_string())?,
            stop: AtomicBool::new(false),
        });
        let state = shared.clone();
        let worker = std::thread::spawn(move || {
            for socket in listener.incoming() {
                if state.stop.load(Ordering::Acquire) {
                    break;
                }
                if let Ok(socket) = socket {
                    let state = state.clone();
                    std::thread::spawn(move || serve(socket, &state));
                }
            }
        });
        Ok(Self {
            address,
            shared,
            worker: Some(worker),
        })
    }
    pub fn port(&self) -> u16 {
        self.address.port()
    }
    pub fn token(&self) -> &str {
        &self.shared.token
    }
    pub fn nonce(&self) -> &str {
        &self.shared.nonce
    }
    pub fn epoch(&self) -> u64 {
        self.shared.epoch.load(Ordering::Acquire)
    }
    pub fn new_epoch(&self) -> u64 {
        self.shared.epoch.fetch_add(1, Ordering::AcqRel) + 1
    }
    pub fn set_budget(&self, max: Option<f64>) -> Result<(), String> {
        validate_cost(max)?;
        self.shared.budget.lock().map_err(|e| e.to_string())?.max = max;
        self.new_epoch();
        Ok(())
    }
    pub fn add_cost(&self, cost: f64) -> Result<(), String> {
        validate_cost(Some(cost))?;
        self.shared
            .budget
            .lock()
            .map_err(|e| e.to_string())?
            .accumulated += cost;
        Ok(())
    }
    pub fn set_provider(&self, name: &str, credential: ProviderCredential) -> Result<(), String> {
        if name.is_empty()
            || !name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        {
            return Err("invalid provider name".into());
        }
        let url = reqwest::Url::parse(&credential.base_url).map_err(|_| "invalid provider URL")?;
        if !(url.scheme() == "https"
            || (url.scheme() == "http"
                && matches!(url.host_str(), Some("127.0.0.1" | "localhost" | "[::1]"))))
            || !url.username().is_empty()
            || url.password().is_some()
            || url.query().is_some()
            || url.fragment().is_some()
            || !["authorization", "x-api-key"].contains(&credential.header.as_str())
            || credential.key.is_empty()
            || reqwest::header::HeaderValue::from_str(&credential.key).is_err()
        {
            return Err(
                "provider needs HTTPS, a supported credential header, and a valid key".into(),
            );
        }
        self.shared
            .providers
            .lock()
            .map_err(|e| e.to_string())?
            .insert(
                name.into(),
                Arc::new(Provider {
                    credential: Mutex::new(credential),
                    state: Mutex::new("valid"),
                }),
            );
        self.new_epoch();
        Ok(())
    }
    pub fn health(&self) -> Value {
        health(&self.shared)
    }
}
impl Drop for EgressBroker {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::Release);
        let _ = TcpStream::connect_timeout(&self.address, Duration::from_secs(1));
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}
fn validate_cost(cost: Option<f64>) -> Result<(), String> {
    if cost.is_some_and(|c| !c.is_finite() || c < 0.0) {
        Err("budget and cost must be finite and non-negative".into())
    } else {
        Ok(())
    }
}
fn health(shared: &Shared) -> Value {
    let budget = shared.budget.lock().unwrap();
    let providers: HashMap<_, _> = shared
        .providers
        .lock()
        .unwrap()
        .iter()
        .map(|(k, p)| (k.clone(), *p.state.lock().unwrap()))
        .collect();
    json!({"status":"ok", "proto":1, "broker":"ok", "epoch": shared.epoch.load(Ordering::Acquire),
        "budget":{"max_cost_usd":budget.max, "accumulated_cost_usd":budget.accumulated, "exceeded":budget.max.is_some_and(|max| budget.accumulated >= max)},
        "providers":providers, "desktop":{"suspending":false}})
}
fn response(stream: &mut TcpStream, status: u16, body: Value) {
    let text = body.to_string();
    let reason = match status {
        200 => "OK",
        400 => "Bad Request",
        401 => "Unauthorized",
        402 => "Payment Required",
        404 => "Not Found",
        413 => "Payload Too Large",
        _ => "Bad Gateway",
    };
    let _ = write!(stream, "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{text}", text.len());
}
fn constant_eq(a: &str, b: &str) -> bool {
    a.len() == b.len() && a.bytes().zip(b.bytes()).fold(0, |x, (a, b)| x | (a ^ b)) == 0
}
fn serve(mut stream: TcpStream, shared: &Shared) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(15)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(30)));
    if let Err((status, message)) = handle(&mut stream, shared) {
        response(&mut stream, status, json!({"error":message}));
    }
}
fn handle(stream: &mut TcpStream, shared: &Shared) -> Result<(), (u16, &'static str)> {
    let mut reader = BufReader::new(
        stream
            .try_clone()
            .map_err(|_| (400, "socket unavailable"))?,
    );
    let mut line = String::new();
    reader
        .by_ref()
        .take(8193)
        .read_line(&mut line)
        .map_err(|_| (400, "invalid request"))?;
    if line.len() > 8192 {
        return Err((400, "request line too long"));
    }
    let mut words = line.split_whitespace();
    let method = words.next().ok_or((400, "missing method"))?.to_string();
    let path = words.next().ok_or((400, "missing path"))?.to_string();
    let mut headers = Vec::new();
    let mut count = line.len();
    let mut content_length = None;
    loop {
        line.clear();
        let read = reader
            .by_ref()
            .take(32769)
            .read_line(&mut line)
            .map_err(|_| (400, "invalid headers"))?;
        count += read;
        if count > 32768 || read == 0 {
            return Err((400, "invalid headers"));
        }
        if line == "\r\n" || line == "\n" {
            break;
        }
        let (key, value) = line
            .trim_end_matches(['\r', '\n'])
            .split_once(':')
            .ok_or((400, "invalid header"))?;
        let key = key.to_ascii_lowercase();
        let value = value.trim().to_string();
        if key == "transfer-encoding" {
            return Err((400, "chunked requests are not supported"));
        }
        if key == "content-length" {
            let n: usize = value.parse().map_err(|_| (400, "invalid content length"))?;
            if content_length.replace(n).is_some() {
                return Err((400, "duplicate content length"));
            }
        }
        headers.push((key, value));
    }
    let expected = format!("Bearer {}", shared.token);
    let bearer = headers
        .iter()
        .filter(|(k, _)| k == "authorization")
        .collect::<Vec<_>>();
    let run_tokens = headers
        .iter()
        .filter(|(k, _)| k == "x-crux-run-token")
        .collect::<Vec<_>>();
    let authenticated = if run_tokens.len() == 1 {
        constant_eq(&run_tokens[0].1, &shared.token)
    } else {
        run_tokens.is_empty() && bearer.len() == 1 && constant_eq(&bearer[0].1, &expected)
    };
    if !authenticated {
        return Err((401, "invalid link token"));
    }
    if method == "GET" && path == "/v1/egress/health" {
        response(stream, 200, health(shared));
        return Ok(());
    }
    if method == "GET" && path == "/v1/egress/nonce" {
        let body = &shared.nonce;
        write!(stream, "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).map_err(|_| (502,"probe disconnected"))?;
        return Ok(());
    }
    if method != "POST" {
        return Err((404, "unknown egress route"));
    }
    let rest = path
        .strip_prefix("/v1/egress/")
        .ok_or((404, "unknown egress route"))?;
    let (name, upstream_path) = rest
        .split_once('/')
        .ok_or((400, "provider path is required"))?;
    if upstream_path.starts_with('/')
        || upstream_path
            .split(['/', '?'])
            .any(|p| matches!(p, "." | "..") || p.contains('%') || p.contains('\\'))
    {
        return Err((400, "invalid upstream path"));
    }
    let provider = shared
        .providers
        .lock()
        .unwrap()
        .get(name)
        .cloned()
        .ok_or((404, "unknown provider"))?;
    {
        let budget = shared.budget.lock().unwrap();
        if budget.max.is_some_and(|max| budget.accumulated >= max) {
            response(
                stream,
                402,
                json!({"error":{"code":"billing_hard_limit_reached", "message":"Crux Link local budget cap reached"}}),
            );
            return Ok(());
        }
    }
    let size = content_length.unwrap_or(0);
    if size > 16 * 1024 * 1024 {
        return Err((413, "request body exceeds 16 MiB"));
    }
    let mut body = vec![0; size];
    reader
        .read_exact(&mut body)
        .map_err(|_| (400, "incomplete body"))?;
    let (base_url, header, key) = {
        let cred = provider.credential.lock().unwrap();
        (cred.base_url.clone(), cred.header.clone(), cred.key.clone())
    };
    let url = format!("{}/{upstream_path}", base_url.trim_end_matches('/'));
    let send = |key: &str| {
        let mut request = shared.client.post(&url).body(body.clone());
        for (k, v) in &headers {
            if ![
                "authorization",
                "x-api-key",
                "host",
                "content-length",
                "connection",
                "transfer-encoding",
                "proxy-authorization",
                "x-crux-run-token",
                "cookie",
                "te",
                "trailer",
                "upgrade",
            ]
            .contains(&k.as_str())
            {
                request = request.header(k, v);
            }
        }
        let value = if header == "authorization" {
            format!("Bearer {key}")
        } else {
            key.into()
        };
        request.header(&header, value).send()
    };
    let mut upstream = send(&key).map_err(|_| {
        *provider.state.lock().unwrap() = "unreachable";
        (502, "provider unreachable")
    })?;
    if upstream.status().as_u16() == 401 {
        // Hold one mutex across refresh; concurrent 401s reuse the new credential.
        let mut credential = provider.credential.lock().unwrap();
        if credential.key == key {
            if let Some(refresh) = &credential.refresh {
                let refreshed = refresh().map_err(|_| {
                    *provider.state.lock().unwrap() = "auth_required";
                    (401, "provider sign-in required")
                })?;
                if refreshed.is_empty()
                    || reqwest::header::HeaderValue::from_str(&refreshed).is_err()
                {
                    return Err((401, "invalid refreshed credential"));
                }
                credential.key = refreshed;
                shared.epoch.fetch_add(1, Ordering::AcqRel);
            }
        }
        if credential.key != key {
            upstream = send(&credential.key).map_err(|_| (502, "provider unreachable"))?;
        }
    }
    let status = upstream.status();
    *provider.state.lock().unwrap() = if matches!(status.as_u16(), 401 | 403) {
        "auth_required"
    } else if status.is_server_error() {
        "degraded"
    } else {
        "valid"
    };
    let state = if matches!(status.as_u16(), 401 | 403) {
        "auth-required"
    } else {
        "ok"
    };
    write!(
        stream,
        "HTTP/1.1 {} {}\r\nConnection: close\r\nx-crux-egress: {state}\r\n",
        status.as_u16(),
        status.canonical_reason().unwrap_or("Upstream")
    )
    .map_err(|_| (502, "client disconnected"))?;
    for (key, value) in upstream.headers() {
        if ![
            "connection",
            "transfer-encoding",
            "content-length",
            "set-cookie",
            "x-crux-egress",
        ]
        .contains(&key.as_str())
        {
            if let Ok(value) = value.to_str() {
                write!(stream, "{key}: {value}\r\n").map_err(|_| (502, "client disconnected"))?;
            }
        }
    }
    write!(stream, "\r\n").map_err(|_| (502, "client disconnected"))?;
    // Closing delimits the response, preserving streaming without buffering tokens.
    let _ = std::io::copy(&mut upstream, stream);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn call(broker: &EgressBroker, method: &str, path: &str, body: &str) -> (u16, String) {
        let client = reqwest::blocking::Client::new();
        let response = client
            .request(
                method.parse().unwrap(),
                format!("http://127.0.0.1:{}{path}", broker.port()),
            )
            .bearer_auth(broker.token())
            .header("x-api-key", "crux-ephemeral-placeholder")
            .body(body.to_string())
            .send()
            .unwrap();
        (response.status().as_u16(), response.text().unwrap())
    }
    #[test]
    fn health_nonce_epoch_and_budget_are_local_and_authenticated() {
        let broker = EgressBroker::start(Some(50.0)).unwrap();
        broker
            .set_provider(
                "openai",
                ProviderCredential {
                    base_url: "http://127.0.0.1:1".into(),
                    key: "real-key".into(),
                    header: "authorization".into(),
                    refresh: None,
                },
            )
            .unwrap();
        broker.add_cost(12.34).unwrap();
        let epoch = broker.epoch();
        broker.set_budget(Some(12.34)).unwrap();
        assert!(broker.epoch() > epoch);
        let (status, text) = call(&broker, "GET", "/v1/egress/health", "");
        assert_eq!(status, 200);
        let health: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(health["budget"]["exceeded"], true);
        assert_eq!(health["providers"]["openai"], "valid");
        assert_eq!(
            call(&broker, "GET", "/v1/egress/nonce", "").1,
            broker.nonce()
        );
        let (status, text) = call(
            &broker,
            "POST",
            "/v1/egress/openai/v1/chat/completions",
            "{}",
        );
        assert_eq!(status, 402);
        assert_eq!(
            serde_json::from_str::<Value>(&text).unwrap()["error"]["code"],
            "billing_hard_limit_reached"
        );
        assert_eq!(
            reqwest::blocking::get(format!(
                "http://127.0.0.1:{}/v1/egress/health",
                broker.port()
            ))
            .unwrap()
            .status(),
            401
        );
    }
    #[test]
    fn replaces_remote_credentials_and_refreshes_once_on_401() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = std::thread::spawn(move || {
            for i in 0..3 {
                let (mut socket, _) = listener.accept().unwrap();
                let mut reader = BufReader::new(socket.try_clone().unwrap());
                let mut request = String::new();
                loop {
                    let mut line = String::new();
                    reader.read_line(&mut line).unwrap();
                    if line == "\r\n" {
                        break;
                    }
                    request.push_str(&line);
                }
                assert!(!request.contains("crux-ephemeral"));
                assert!(!request.to_lowercase().contains("x-api-key"));
                assert!(request.contains(if i == 0 {
                    "Bearer old-secret"
                } else {
                    "Bearer new-secret"
                }));
                let status = if i == 0 { "401 Unauthorized" } else { "200 OK" };
                write!(
                    socket,
                    "HTTP/1.1 {status}\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
                )
                .unwrap();
            }
        });
        let broker = EgressBroker::start(None).unwrap();
        let count = Arc::new(AtomicU64::new(0));
        let calls = count.clone();
        broker
            .set_provider(
                "openai",
                ProviderCredential {
                    base_url: format!("http://127.0.0.1:{port}"),
                    key: "old-secret".into(),
                    header: "authorization".into(),
                    refresh: Some(Arc::new(move || {
                        calls.fetch_add(1, Ordering::Relaxed);
                        Ok("new-secret".into())
                    })),
                },
            )
            .unwrap();
        for _ in 0..2 {
            assert_eq!(
                call(
                    &broker,
                    "POST",
                    "/v1/egress/openai/v1/chat/completions",
                    "{}"
                )
                .0,
                200
            );
        }
        assert_eq!(count.load(Ordering::Relaxed), 1);
        server.join().unwrap();
    }
}
