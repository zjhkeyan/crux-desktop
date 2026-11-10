//! CORAL uses app-managed CLI bindings and isolated per-agent profiles.

use std::path::{Path, PathBuf};

use serde_json::{json, Value};

use crate::Env;

pub fn bin_dir(env: &Env) -> Result<PathBuf, String> {
    Ok(crate::runtime::runtime_root(env)?.join("bin"))
}

pub fn engine_agents_config_path(env: &Env) -> Result<PathBuf, String> {
    Ok(crate::runtime::xdg_config_home(env)?.join("crux/engine-agents.yaml"))
}

pub fn coral_agents_config_path(env: &Env) -> Result<PathBuf, String> {
    Ok(crate::runtime::xdg_config_home(env)?.join("coral/agents.yaml"))
}

pub fn user_engine_agents_config_path() -> Option<PathBuf> {
    std::env::var_os("CRUX_AGENTS_CONFIG")
        .or_else(|| std::env::var_os("CORAL_AGENTS_CONFIG"))
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or_else(|| {
            crate::env::home()
                .ok()
                .map(|home| home.join(".config/crux/engine-agents.yaml"))
        })
}

pub fn user_coral_agents_config_path() -> Option<PathBuf> {
    std::env::var_os("CORAL_AGENTS_CONFIG")
        .or_else(|| std::env::var_os("CRUX_AGENTS_CONFIG"))
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .or_else(|| {
            crate::env::home()
                .ok()
                .map(|home| home.join(".config/coral/agents.yaml"))
        })
}

/// Refresh only Crux's bindings; engine setup failures must never block Crux.
pub fn sync(env: &Env) {
    let bindings = match prepare_runtime(env) {
        Ok(bindings) => bindings,
        Err(error) => {
            crate::debug_log::append(env, &format!("CORAL runtime sync failed: {error}"));
            return;
        }
    };
    let bin = match bin_dir(env) {
        Ok(bin) => bin.join(if cfg!(windows) {
            "crux-engine.cmd"
        } else {
            "crux-engine"
        }),
        Err(_) => return,
    };
    if let Err(error) = verify_coral_capabilities(&bin) {
        crate::debug_log::append(env, &format!("CORAL binding refused: {error}"));
        return;
    }
    let Ok(config) = coral_agents_config_path(env) else {
        return;
    };
    let mut paths = vec![config];
    if let Ok(engine_cfg) = engine_agents_config_path(env) {
        if !paths.contains(&engine_cfg) {
            paths.push(engine_cfg);
        }
    }
    for user in [user_coral_agents_config_path(), user_engine_agents_config_path()]
        .into_iter()
        .flatten()
    {
        if !paths.contains(&user) {
            paths.push(user);
        }
    }
    for path in paths {
        if let Err(error) = sync_agents_file(&path, &bindings) {
            crate::debug_log::append(
                env,
                &format!("CORAL binding sync failed ({}): {error}", path.display()),
            );
        }
    }
}

/// Require the discovery contract, rather than silently binding upstream CORAL.
pub fn verify_engine_capabilities(bin: &Path) -> Result<Vec<String>, String> {
    verify_coral_capabilities(bin)
}

pub fn verify_coral_capabilities(bin: &Path) -> Result<Vec<String>, String> {
    let output = crate::runtime::quiet_command(bin)
        .arg("--capabilities")
        .output()
        .map_err(|e| format!("CORAL capability probe failed: {e}"))?;
    if !output.status.success() {
        return Err("CORAL capability probe failed".into());
    }
    let caps: Vec<String> = String::from_utf8(output.stdout)
        .map_err(|e| e.to_string())?
        .split_whitespace()
        .map(str::to_string)
        .collect();
    for required in ["ledger:v1", "board", "radio", "oracle"] {
        if !caps.iter().any(|c| c == required) {
            return Err(format!("CORAL missing capability: {required}"));
        }
    }
    Ok(caps)
}

fn source_dir(env: &Env) -> Option<PathBuf> {
    let mut candidates = vec![
        std::env::var_os("CORAL_SOURCE_DIR").map(PathBuf::from),
        env.resource("coral"),
    ];
    for base in [
        crate::runtime::workspace_dir(env).ok(),
        std::env::current_dir().ok(),
        std::env::current_exe().ok(),
    ] {
        if let Some(base) = base {
            candidates.extend(base.ancestors().map(|p| Some(p.join("CORAL"))));
        }
    }
    candidates
        .into_iter()
        .flatten()
        .find(|p| p.join("pyproject.toml").is_file())
}

// Executed by uv's Python on every launch: keys remain in process memory, never agents.yaml.
const CORAL_LAUNCHER: &str = r#"import json, os, pathlib, sqlite3, subprocess, sys
uv, source, managed, config, db, model, *args = sys.argv[1:]
required = {'ledger:v1', 'board', 'radio', 'oracle'}
source = os.environ.get('CRUX_ENGINE_SOURCE_DIR') or os.environ.get('CORAL_SOURCE_DIR') or source
if source and pathlib.Path(source, 'pyproject.toml').is_file():
    command = [uv, '--directory', source, 'run', 'coral']
elif pathlib.Path(managed).is_file():
    command = [managed]
else:
    user_crux = pathlib.Path.home() / '.local/bin' / ('crux-engine.exe' if os.name == 'nt' else 'crux-engine')
    user = pathlib.Path.home() / '.local/bin' / ('coral.exe' if os.name == 'nt' else 'coral')
    command = [uv, 'tool', 'run', '--from', 'git+https://github.com/Human-Agent-Society/CORAL.git@0123dfb', 'coral']
    wrapper_dir = pathlib.Path(sys.argv[0]).parent
    for candidate in (user_crux, user):
        if candidate.is_file() and candidate.resolve().parent != wrapper_dir.resolve():
            probe = subprocess.run([str(candidate), '--capabilities'], capture_output=True, text=True, timeout=15)
            if probe.returncode == 0 and required <= set(probe.stdout.split()):
                command = [str(candidate)]
                break
probe = subprocess.run(command + ['--capabilities'], capture_output=True, text=True, timeout=60)
if probe.returncode or not required <= set(probe.stdout.split()):
    sys.exit('Crux discovery engine binding refused: ledger:v1 board radio oracle are required')
if args == ['--capabilities']:
    print(probe.stdout.strip())
    sys.exit(0)
# Only operator launches hand keys to the gateway; worktree commands never load Desktop auth.
if not args or args[0] not in ('start', 'resume'):
    for name in list(os.environ):
        if name in ('CORAL_GATEWAY_API_KEYS', 'CRUX_GATEWAY_API_KEYS') or name.startswith(('CORAL_GATEWAY_UPSTREAM_', 'CRUX_GATEWAY_UPSTREAM_')):
            os.environ.pop(name, None)
    os.execvpe(command[0], command + args, os.environ)
# Only API credentials may cross the gateway boundary; OAuth refresh tokens stay in Crux.
keys = {}
try:
    conn = sqlite3.connect(pathlib.Path(db).as_uri() + '?mode=ro', uri=True)
    for provider, text in conn.execute('select integration_id, value from credential order by active desc, time_updated desc'):
        value = json.loads(text)
        if value.get('type') == 'key' and value.get('key'):
            keys.setdefault(provider, value['key'])
    conn.close()
except (sqlite3.Error, OSError, ValueError):
    pass
# Strip JSONC comments outside strings, preserving URL slashes and escaped quotes.
try:
    text = pathlib.Path(config).read_text()
    clean, i, quoted = [], 0, False
    while i < len(text):
        c = text[i]
        if quoted and c == '\\':
            clean.append(text[i:i+2]); i += 2; continue
        if c == '"': quoted = not quoted
        if not quoted and text[i:i+2] == '//':
            end = text.find('\n', i); i = len(text) if end < 0 else end; continue
        if not quoted and text[i:i+2] == '/*':
            end = text.find('*/', i+2)
            if end < 0: raise ValueError('unterminated comment')
            i = end + 2; continue
        clean.append(c); i += 1
    providers = json.loads(''.join(clean)).get('provider', {})
    for provider, value in providers.items():
        key = value.get('options', {}).get('apiKey', '')
        if isinstance(key, str) and key and not key.startswith('{'):
            keys[provider] = key
except (OSError, ValueError, TypeError, AttributeError):
    providers = {}
os.environ['CRUX_GATEWAY_API_KEYS'] = json.dumps(keys)
os.environ['CORAL_GATEWAY_API_KEYS'] = json.dumps(keys)
provider = model.split('/', 1)[0]
for name in (
    'CRUX_GATEWAY_UPSTREAM_API_KEY', 'CRUX_GATEWAY_UPSTREAM_PROVIDER', 'CRUX_GATEWAY_UPSTREAM_BASE_URL',
    'CORAL_GATEWAY_UPSTREAM_API_KEY', 'CORAL_GATEWAY_UPSTREAM_PROVIDER', 'CORAL_GATEWAY_UPSTREAM_BASE_URL',
):
    os.environ.pop(name, None)
if provider in keys:
    os.environ['CRUX_GATEWAY_UPSTREAM_API_KEY'] = keys[provider]
    os.environ['CORAL_GATEWAY_UPSTREAM_API_KEY'] = keys[provider]
    os.environ['CRUX_GATEWAY_UPSTREAM_PROVIDER'] = provider
    os.environ['CORAL_GATEWAY_UPSTREAM_PROVIDER'] = provider
    url = providers.get(provider, {}).get('options', {}).get('baseURL')
    if url:
        os.environ['CRUX_GATEWAY_UPSTREAM_BASE_URL'] = url
        os.environ['CORAL_GATEWAY_UPSTREAM_BASE_URL'] = url
os.execvpe(command[0], command + args, os.environ)
"#;

fn prepare_runtime(env: &Env) -> Result<Vec<(&'static str, Value)>, String> {
    let root = crate::runtime::runtime_root(env)?;
    let bin = bin_dir(env)?;
    std::fs::create_dir_all(&bin).map_err(|e| e.to_string())?;
    crate::runtime::tighten_private(&bin);
    let config = coral_agents_config_path(env)?;
    let opencode = crate::runtime::sidecar_bin("opencode").unwrap_or_else(|| "opencode".into());
    let uv = crate::runtime::sidecar_bin("uv").unwrap_or_else(|| "uv".into());
    let source = source_dir(env).unwrap_or_default();
    let model = crate::runtime::get_default_model(env)
        .ok()
        .flatten()
        .unwrap_or_else(|| "anthropic/claude-sonnet-4-5".into());
    let launcher = bin.join("coral-launch.py");
    crate::runtime::write_atomic(&launcher, CORAL_LAUNCHER)?;
    let managed = root
        .join("coral-bin")
        .join(if cfg!(windows) { "coral.exe" } else { "coral" });
    let effective = crate::runtime::effective_config_file(env)?;
    let db = crate::runtime::xdg_data_home(env)?.join("opencode/opencode.db");
    let args: Vec<String> = [uv.as_path(), &source, &managed, &effective, &db]
        .iter()
        .map(|p| p.to_string_lossy().into_owned())
        .chain([model.clone()])
        .collect();
    // CORAL supplies each agent's own XDG directories. Never overwrite them with Desktop's profile.
    let mut runtime_env = serde_json::Map::new();
    runtime_env.insert(
        "CORAL_PROFILE_ROOT".into(),
        json!(forward_path(&root.join("coral-profiles"))),
    );
    let catalog = crate::model_prices::catalog_path(&root);
    if catalog.is_file() {
        runtime_env.insert("OPENCODE_MODELS_PATH".into(), json!(forward_path(&catalog)));
    }
    #[cfg(unix)]
    {
        let mut agent = String::from("#!/usr/bin/env sh\n");
        agent.push_str("unset CRUX_GATEWAY_API_KEYS CRUX_GATEWAY_UPSTREAM_API_KEY CRUX_GATEWAY_UPSTREAM_PROVIDER CRUX_GATEWAY_UPSTREAM_BASE_URL CORAL_GATEWAY_API_KEYS CORAL_GATEWAY_UPSTREAM_API_KEY CORAL_GATEWAY_UPSTREAM_PROVIDER CORAL_GATEWAY_UPSTREAM_BASE_URL\n");
        // Legacy direct launches retain their profile; managed discovery agents always keep their own.
        agent.push_str("if [ -z \"${CRUX_RUN_DIR:-}${CORAL_DIR:-}\" ]; then\n");
        for (key, dir) in [
            ("XDG_CONFIG_HOME", "xdg-config"),
            ("XDG_DATA_HOME", "xdg-data"),
            ("XDG_CACHE_HOME", "xdg-cache"),
            ("XDG_STATE_HOME", "xdg-state"),
        ] {
            agent.push_str(&format!(
                "export {key}={}\n",
                shell_quote(&root.join(dir).to_string_lossy())
            ));
        }
        agent.push_str("else\n");
        for (key, dir) in [
            ("XDG_CONFIG_HOME", "xdg-config"),
            ("XDG_DATA_HOME", "xdg-data"),
            ("XDG_STATE_HOME", "xdg-state"),
        ] {
            agent.push_str(&format!("if [ -z \"${{{key}:-}}\" ] || [ \"${{{key}}}\" = {} ]; then echo 'Crux discovery requires an isolated agent profile' >&2; exit 1; fi\n", shell_quote(&root.join(dir).to_string_lossy())));
        }
        agent.push_str("fi\n");
        if catalog.is_file() {
            agent.push_str(&format!(
                "export OPENCODE_MODELS_PATH={}\n",
                shell_quote(&catalog.to_string_lossy())
            ));
        }
        agent.push_str(&format!(
            "exec {} \"$@\"\n",
            shell_quote(&opencode.to_string_lossy())
        ));
        write_wrapper(&bin.join("crux-opencode"), &agent)?;
        let wrapper = format!("#!/usr/bin/env sh\nexport CORAL_PROFILE_ROOT={}\nexport UV_TOOL_DIR={}\nexport UV_TOOL_BIN_DIR={}\nif [ -z \"${{CORAL_AGENTS_CONFIG:-}}\" ] && [ -n \"${{CRUX_AGENTS_CONFIG:-}}\" ]; then export CORAL_AGENTS_CONFIG=\"$CRUX_AGENTS_CONFIG\"; fi\nif [ -z \"${{CORAL_AGENTS_CONFIG:-}}\" ]; then export CORAL_AGENTS_CONFIG={}; fi\nif [ -z \"${{CRUX_AGENTS_CONFIG:-}}\" ]; then export CRUX_AGENTS_CONFIG=\"$CORAL_AGENTS_CONFIG\"; fi\nexec {} run --no-project python {} {} \"$@\"\n",
            shell_quote(&root.join("coral-profiles").to_string_lossy()), shell_quote(&root.join("coral-tools").to_string_lossy()), shell_quote(&root.join("coral-bin").to_string_lossy()), shell_quote(&config.to_string_lossy()), shell_quote(&uv.to_string_lossy()), shell_quote(&launcher.to_string_lossy()), args.iter().map(|s| shell_quote(s)).collect::<Vec<_>>().join(" "));
        write_wrapper(&bin.join("crux-engine"), &wrapper)?;
        write_wrapper(&bin.join("coral"), &wrapper)?;
    }
    #[cfg(windows)]
    {
        let mut agent = String::from("@echo off\r\nsetlocal DisableDelayedExpansion\r\n");
        agent.push_str("set \"CRUX_GATEWAY_API_KEYS=\"\r\nset \"CRUX_GATEWAY_UPSTREAM_API_KEY=\"\r\nset \"CRUX_GATEWAY_UPSTREAM_PROVIDER=\"\r\nset \"CRUX_GATEWAY_UPSTREAM_BASE_URL=\"\r\nset \"CORAL_GATEWAY_API_KEYS=\"\r\nset \"CORAL_GATEWAY_UPSTREAM_API_KEY=\"\r\nset \"CORAL_GATEWAY_UPSTREAM_PROVIDER=\"\r\nset \"CORAL_GATEWAY_UPSTREAM_BASE_URL=\"\r\n");
        // The discovery runtime owns the per-agent XDG profile on Windows as well.
        for (key, dir) in [
            ("XDG_CONFIG_HOME", "xdg-config"),
            ("XDG_DATA_HOME", "xdg-data"),
            ("XDG_STATE_HOME", "xdg-state"),
        ] {
            let desktop_dir = cmd_escape(&root.join(dir).to_string_lossy());
            agent.push_str(&format!(
                "if defined CRUX_RUN_DIR if not defined {key} exit /b 1\r\nif defined CRUX_RUN_DIR if /I \"%{key}%\"==\"{desktop_dir}\" exit /b 1\r\nif defined CORAL_DIR if not defined {key} exit /b 1\r\nif defined CORAL_DIR if /I \"%{key}%\"==\"{desktop_dir}\" exit /b 1\r\n"
            ));
        }
        agent.push_str(&format!(
            "\"{}\" %*\r\n",
            cmd_escape(&opencode.to_string_lossy())
        ));
        write_wrapper(&bin.join("crux-opencode.cmd"), &agent)?;
        let wrapper = format!("@echo off\r\nsetlocal DisableDelayedExpansion\r\nset \"CORAL_PROFILE_ROOT={}\"\r\nset \"UV_TOOL_DIR={}\"\r\nset \"UV_TOOL_BIN_DIR={}\"\r\nif not defined CORAL_AGENTS_CONFIG set \"CORAL_AGENTS_CONFIG={}\"\r\nif not defined CRUX_AGENTS_CONFIG set \"CRUX_AGENTS_CONFIG=%CORAL_AGENTS_CONFIG%\"\r\n\"{}\" run --no-project python \"{}\" {} %*\r\n",
            cmd_escape(&root.join("coral-profiles").to_string_lossy()), cmd_escape(&root.join("coral-tools").to_string_lossy()), cmd_escape(&root.join("coral-bin").to_string_lossy()), cmd_escape(&config.to_string_lossy()), cmd_escape(&uv.to_string_lossy()), cmd_escape(&launcher.to_string_lossy()), args.iter().map(|s| format!("\"{}\"", cmd_escape(s))).collect::<Vec<_>>().join(" "));
        write_wrapper(&bin.join("crux-engine.cmd"), &wrapper)?;
        write_wrapper(&bin.join("coral.cmd"), &wrapper)?;
    }
    let command = bin.join(if cfg!(windows) {
        "crux-opencode.cmd"
    } else {
        "crux-opencode"
    });
    let mut bindings = vec![(
        "crux-opencode",
        json!({"runtime": "opencode", "command": forward_path(&command), "model": model, "runtime_options": {"env": runtime_env}}),
    )];
    let path = crate::runtime::enriched_path();
    for (name, command, runtime, model) in [
        ("crux-claude", "claude", "claude_code", "sonnet"),
        ("crux-codex", "codex", "codex", "gpt-5"),
    ] {
        if let Some(command) = crate::which::find_on_path(command, Some(&path)) {
            bindings.push((
                name,
                json!({"runtime": runtime, "command": forward_path(&command), "model": model}),
            ));
        }
    }
    Ok(bindings)
}

fn forward_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

#[cfg(unix)]
fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}

#[cfg(windows)]
fn cmd_escape(value: &str) -> String {
    value.replace('%', "%%")
}

fn write_wrapper(path: &Path, contents: &str) -> Result<(), String> {
    crate::runtime::write_atomic(path, contents)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755))
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn sync_agents_file(path: &Path, bindings: &[(&str, Value)]) -> Result<(), String> {
    let existing = match std::fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(error) => return Err(error.to_string()),
    };
    let updated = merge_agents(&existing, bindings)?;
    crate::runtime::write_atomic(path, &updated)?;
    if let Some(parent) = path.parent() {
        crate::runtime::tighten_private(parent);
    }
    crate::runtime::tighten_private(path);
    Ok(())
}

fn yaml_entry(line: &str) -> Option<(usize, &str, &str)> {
    let text = line.trim_start();
    if text.starts_with('#') {
        return None;
    }
    let (key, value) = text.split_once(':')?;
    Some((
        line.len() - text.len(),
        key.trim().trim_matches(['\'', '"']),
        value.trim(),
    ))
}

fn merge_agents(existing: &str, bindings: &[(&str, Value)]) -> Result<String, String> {
    // JSON is valid YAML too; retain flow-style stores without a second parser.
    if let Ok(mut root) = serde_json::from_str::<Value>(existing) {
        let object = root
            .as_object_mut()
            .ok_or("agents config must be a mapping")?;
        if object
            .get("default")
            .is_none_or(|v| v.is_null() || v.as_str() == Some(""))
        {
            object.insert("default".into(), json!("crux-opencode"));
        }
        let agents = object.entry("agents").or_insert_with(|| json!({}));
        if agents.is_null() {
            *agents = json!({});
        }
        let agents = agents.as_object_mut().ok_or("agents must be a mapping")?;
        for (name, value) in bindings {
            agents.insert((*name).into(), value.clone());
        }
        return serde_json::to_string_pretty(&root)
            .map(|s| format!("{s}\n"))
            .map_err(|e| e.to_string());
    }
    // shortcut: merge block mappings; leave non-JSON flow mappings/anchors untouched until a YAML parser is needed.
    let mut lines: Vec<String> = existing.lines().map(String::from).collect();
    let mut agents_line = None;
    let mut default_line = None;
    for (index, line) in lines.iter().enumerate() {
        if line.starts_with(char::is_whitespace)
            || line.trim().is_empty()
            || line.starts_with('#')
            || line == "---"
        {
            continue;
        }
        let (_, key, value) =
            yaml_entry(line).ok_or("unsupported YAML mapping; file left untouched")?;
        if key == "agents" {
            if agents_line.replace(index).is_some() {
                return Err("duplicate agents key".into());
            }
            let value = value.split('#').next().unwrap_or_default().trim();
            if !["", "{}", "null", "~"].contains(&value) {
                return Err("unsupported agents mapping; file left untouched".into());
            }
        } else if key == "default" {
            if default_line.replace(index).is_some() {
                return Err("duplicate default key".into());
            }
        }
    }
    if let Some(index) = default_line {
        let (_, _, value) = yaml_entry(&lines[index]).ok_or("invalid default")?;
        let value = value.split('#').next().unwrap_or_default().trim();
        if [
            "",
            "''",
            "\"\"",
            "null",
            "~",
            "crux-opencode",
            "'crux-opencode'",
            "\"crux-opencode\"",
        ]
        .contains(&value)
        {
            lines[index] = "default: crux-opencode".into();
        }
    } else {
        lines.push("default: crux-opencode".into());
    }
    let start = agents_line.unwrap_or_else(|| {
        lines.push("agents:".into());
        lines.len() - 1
    });
    let end = (start + 1..lines.len())
        .find(|&i| {
            !lines[i].trim().is_empty()
                && !lines[i].starts_with('#')
                && !lines[i].starts_with(char::is_whitespace)
        })
        .unwrap_or(lines.len());
    let indent = lines[start + 1..end]
        .iter()
        .find_map(|line| yaml_entry(line).map(|e| e.0))
        .unwrap_or(2);
    let mut kept = Vec::new();
    let mut skip = false;
    for line in &lines[start + 1..end] {
        if let Some((depth, name, value)) = yaml_entry(line) {
            if depth == indent {
                skip = bindings.iter().any(|(managed, _)| *managed == name);
                if skip && value.contains('&') {
                    return Err("managed binding has a YAML anchor; file left untouched".into());
                }
            }
        } else if !line.trim().is_empty()
            && !line.trim_start().starts_with('#')
            && line.len() - line.trim_start().len() <= indent
        {
            return Err("invalid agents mapping; file left untouched".into());
        }
        if !skip {
            kept.push(line.clone());
        }
    }
    for (name, binding) in bindings {
        kept.push(format!("{}{name}:", " ".repeat(indent)));
        if let Some(fields) = binding.as_object() {
            for (key, value) in fields {
                kept.push(format!("{}{key}: {value}", " ".repeat(indent + 2)));
            }
        }
    }
    lines[start] = "agents:".into();
    lines.splice(start + 1..end, kept);
    Ok(format!("{}\n", lines.join("\n")))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[cfg(unix)]
    const FAKE_UV: &str = "#!/bin/sh\nif [ \"$1\" = run ] && [ \"$2\" = --no-project ]; then shift 3; exec python3 \"$@\"; fi\nfor arg do if [ \"$arg\" = --capabilities ]; then echo 'ledger:v1 board radio oracle'; exit 0; fi; done\nprintf '%s\\n' \"$@\"\n";

    struct Fixture {
        env: Env,
        dir: PathBuf,
    }

    impl Fixture {
        fn new() -> Self {
            let dir = std::env::temp_dir().join(format!(
                "crux-coral-{}-{}",
                std::process::id(),
                crate::runtime::random_hex(8)
            ));
            #[cfg(unix)]
            {
                executable(&dir.join(".local/bin/uv"), FAKE_UV);
                executable(
                    &dir.join(".local/bin/coral"),
                    "#!/bin/sh\nprintf 'ledger:v1 board radio oracle\\n'\n",
                );
            }
            #[cfg(windows)]
            {
                fs::create_dir_all(dir.join(".local/bin")).unwrap();
                fs::write(
                    dir.join(".local/bin/uv.cmd"),
                    "@echo off\r\necho ledger:v1 board radio oracle\r\n",
                )
                .unwrap();
            }
            let env = Env::new(dir.join("data"), dir.join("resources"), None, "test".into());
            Self { env, dir }
        }

        fn config(&self) -> String {
            fs::read_to_string(coral_agents_config_path(&self.env).unwrap()).unwrap()
        }
    }

    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.dir);
        }
    }

    // Run sync in a child so HOME/config overrides never race other tests or touch real user files.
    fn isolated(name: &str, test: impl FnOnce(Fixture)) {
        let f = Fixture::new();
        if std::env::var("CRUX_CORAL_TEST").ok().as_deref() == Some(name) {
            test(f);
            return;
        }
        let status = crate::runtime::quiet_command(std::env::current_exe().unwrap())
            .args([
                "--exact",
                &format!("crux_bridge::tests::{name}"),
                "--nocapture",
            ])
            .env("CRUX_CORAL_TEST", name)
            .env("CORAL_SOURCE_DIR", f.dir.join("missing-checkout"))
            .env(
                "PATH",
                std::env::join_paths(std::iter::once(f.dir.join(".local/bin")).chain(
                    std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default()),
                ))
                .unwrap(),
            )
            .env("CORAL_AGENTS_CONFIG", f.dir.join("user/coral/agents.yaml"))
            .env("CRUX_AGENTS_CONFIG", f.dir.join("user/coral/agents.yaml"))
            .env("HOME", &f.dir)
            .env("USERPROFILE", &f.dir)
            .status()
            .unwrap();
        assert!(status.success(), "isolated test {name} failed");
    }

    #[test]
    #[cfg(unix)]
    fn coral_capability_handshake_accepts_only_the_complete_contract() {
        let f = Fixture::new();
        let bin = f.dir.join("candidate");
        for output in [
            "ledger:v1 board radio oracle",
            "ledger:v1 board radio",
            "ledger:v10 board radio oracle",
        ] {
            executable(&bin, &format!("#!/bin/sh\necho '{output}'\n"));
            assert_eq!(
                verify_coral_capabilities(&bin).is_ok(),
                output == "ledger:v1 board radio oracle"
            );
        }
        executable(
            &bin,
            "#!/bin/sh\necho 'ledger:v1 board radio oracle'\nexit 1\n",
        );
        assert!(verify_coral_capabilities(&bin).is_err());
        assert!(verify_coral_capabilities(&f.dir.join("missing")).is_err());
    }

    #[test]
    #[cfg(unix)]
    fn coral_gateway_handoff_filters_oauth_and_keeps_secrets_out_of_bindings() {
        isolated(
            "coral_gateway_handoff_filters_oauth_and_keeps_secrets_out_of_bindings",
            |f| {
                let source = f.dir.join("source");
                fs::create_dir_all(&source).unwrap();
                fs::write(source.join("pyproject.toml"), "[project]\nname='coral'\n").unwrap();
                let uv = f.dir.join("fake-bin/uv");
                executable(&uv, "#!/bin/sh\nif [ \"$1\" = run ]; then shift 3; exec python3 \"$@\"; fi\nfor arg do if [ \"$arg\" = --capabilities ]; then echo 'ledger:v1 board radio oracle'; exit 0; fi; done\nprintf '%s\\n' \"$CORAL_GATEWAY_API_KEYS\" \"$CORAL_GATEWAY_UPSTREAM_API_KEY\"\n");
                let db = crate::runtime::xdg_data_home(&f.env)
                    .unwrap()
                    .join("opencode/opencode.db");
                fs::create_dir_all(db.parent().unwrap()).unwrap();
                let conn = rusqlite::Connection::open(db).unwrap();
                conn.execute_batch("CREATE TABLE credential (integration_id TEXT, value TEXT, active INTEGER, time_updated INTEGER);").unwrap();
                for (provider, value) in [
                    ("api", r#"{"type":"key","key":"sk-key"}"#),
                    (
                        "login",
                        r#"{"type":"oauth","access":"access-secret","refresh":"refresh-secret"}"#,
                    ),
                ] {
                    conn.execute(
                        "INSERT INTO credential VALUES (?1, ?2, 1, 0)",
                        [provider, value],
                    )
                    .unwrap();
                }
                let config = crate::runtime::effective_config_file(&f.env).unwrap();
                crate::runtime::write_atomic(&config, r#"{ // JSONC
                "model":"custom/model", "provider":{"custom":{"options":{"apiKey":"sk-config","baseURL":"https://example.test/v1"}},"login":{"options":{"apiKey":"{env:OAUTH}"}}}}
            "#).unwrap();
                sync(&f.env);
                assert!(!f.config().contains("sk-config"));
                assert!(!f.config().contains("sk-key"));
                let output = crate::runtime::quiet_command(bin_dir(&f.env).unwrap().join("coral"))
                    .arg("start")
                    .env("CORAL_SOURCE_DIR", source)
                    .env(
                        "PATH",
                        format!(
                            "{}:{}",
                            uv.parent().unwrap().display(),
                            std::env::var("PATH").unwrap()
                        ),
                    )
                    .output()
                    .unwrap();
                assert!(
                    output.status.success(),
                    "{}",
                    String::from_utf8_lossy(&output.stderr)
                );
                let text = String::from_utf8(output.stdout).unwrap();
                let lines: Vec<_> = text.lines().collect();
                let keys: Value = serde_json::from_str(lines[0]).unwrap();
                assert_eq!(keys, json!({"api":"sk-key", "custom":"sk-config"}));
                assert_eq!(lines[1], "sk-config");
                assert!(!text.contains("access-secret") && !text.contains("refresh-secret"));
                let output = crate::runtime::quiet_command(bin_dir(&f.env).unwrap().join("coral"))
                    .arg("board")
                    .env("CORAL_SOURCE_DIR", f.dir.join("source"))
                    .env("CORAL_GATEWAY_API_KEYS", "must-not-reach-agent")
                    .env("CORAL_GATEWAY_UPSTREAM_API_KEY", "must-not-reach-agent")
                    .env(
                        "PATH",
                        format!(
                            "{}:{}",
                            uv.parent().unwrap().display(),
                            std::env::var("PATH").unwrap()
                        ),
                    )
                    .output()
                    .unwrap();
                assert!(output.status.success());
                assert!(String::from_utf8(output.stdout).unwrap().trim().is_empty());
            },
        );
    }

    #[test]
    fn sync_installs_wrappers_and_binds_the_active_opencode_profile() {
        isolated(
            "sync_installs_wrappers_and_binds_the_active_opencode_profile",
            |f| {
                let root = crate::runtime::runtime_root(&f.env).unwrap();
                crate::runtime::write_atomic(
                    &root.join("xdg-config/opencode/opencode.json"),
                    r#"{"model":"test-provider/test-model"}"#,
                )
                .unwrap();
                sync(&f.env);
                let suffix = if cfg!(windows) { ".cmd" } else { "" };
                for name in ["crux-opencode", "crux-engine", "coral"] {
                    assert!(bin_dir(&f.env)
                        .unwrap()
                        .join(format!("{name}{suffix}"))
                        .is_file());
                }
                let config = f.config();
                assert!(config.contains("default: crux-opencode"));
                assert!(config.contains("model: \"test-provider/test-model\""));
                for name in [
                    "XDG_CONFIG_HOME",
                    "XDG_DATA_HOME",
                    "XDG_CACHE_HOME",
                    "XDG_STATE_HOME",
                ] {
                    assert!(
                        !config.contains(name),
                        "Desktop XDG must not be passed to CORAL agents"
                    );
                }
                assert_eq!(
                    fs::read_to_string(user_coral_agents_config_path().unwrap()).unwrap(),
                    config
                );
            },
        );
    }

    #[test]
    fn changing_the_default_model_immediately_refreshes_coral() {
        isolated(
            "changing_the_default_model_immediately_refreshes_coral",
            |f| {
                sync(&f.env);
                assert!(f
                    .config()
                    .contains("model: \"anthropic/claude-sonnet-4-5\""));
                crate::runtime::set_default_model(&f.env, "openai/gpt-5".into()).unwrap();
                let config = f.config();
                assert!(config.contains("model: \"openai/gpt-5\""));
                assert!(!config.contains("anthropic/claude-sonnet-4-5"));
                assert_eq!(
                    fs::read_to_string(user_coral_agents_config_path().unwrap()).unwrap(),
                    config
                );
            },
        );
    }

    #[test]
    fn provider_and_config_edits_also_refresh_the_binding_without_credentials() {
        isolated(
            "provider_and_config_edits_also_refresh_the_binding_without_credentials",
            |f| {
                crate::runtime::configure_opencode(
                    &f.env,
                    "openai".into(),
                    "secret-not-for-coral".into(),
                    "openai/gpt-5".into(),
                    None,
                    None,
                    &[],
                )
                .unwrap();
                assert!(f.config().contains("model: \"openai/gpt-5\""));
                assert!(!f.config().contains("secret-not-for-coral"));
                crate::runtime::patch_opencode_config(
                    &f.env,
                    json!({"model": "anthropic/claude-opus-4-5"}),
                )
                .unwrap();
                assert!(f.config().contains("model: \"anthropic/claude-opus-4-5\""));
            },
        );
    }

    #[test]
    fn sync_preserves_user_bindings_defaults_and_unrelated_settings_in_both_stores() {
        isolated(
            "sync_preserves_user_bindings_defaults_and_unrelated_settings_in_both_stores",
            |f| {
                let custom = "    my-agent:\n      runtime: codex\n      model: custom-model\n      runtime_options:\n        env: {CUSTOM: 'keep me'}\n";
                let initial = format!("# user config\ndefault: my-agent\nagents:\n{custom}    crux-opencode:\n      runtime: opencode\n      model: stale\nextra: preserved\n");
                let paths = [
                    coral_agents_config_path(&f.env).unwrap(),
                    user_coral_agents_config_path().unwrap(),
                ];
                for path in &paths {
                    crate::runtime::write_atomic(path, &initial).unwrap();
                }
                sync(&f.env);
                crate::runtime::set_default_model(&f.env, "custom/current-model".into()).unwrap();
                for path in paths {
                    let text = fs::read_to_string(path).unwrap();
                    assert!(text.contains(custom));
                    assert!(text.contains("default: my-agent"));
                    assert!(text.contains("extra: preserved"));
                    assert!(text.contains("model: \"custom/current-model\""));
                    assert!(!text.contains("stale"));
                    assert_eq!(text.matches("    crux-opencode:").count(), 1);
                }
            },
        );
    }

    #[test]
    fn json_stores_and_empty_yaml_defaults_are_supported() {
        isolated("json_stores_and_empty_yaml_defaults_are_supported", |f| {
            let path = coral_agents_config_path(&f.env).unwrap();
            let initial =
                r#"{"agents":{"mine":{"runtime":"codex","model":"custom"}},"default":"mine"}"#;
            crate::runtime::write_atomic(&path, initial).unwrap();
            sync(&f.env);
            let data: Value = serde_json::from_str(&f.config()).unwrap();
            assert_eq!(data["default"], "mine");
            assert_eq!(data["agents"]["mine"]["model"], "custom");
            assert_eq!(data["agents"]["crux-opencode"]["runtime"], "opencode");
            for empty in ["", "''", "\"\"", "null", "~"] {
                crate::runtime::write_atomic(&path, &format!("agents: {{}}\ndefault: {empty}\n"))
                    .unwrap();
                sync(&f.env);
                assert!(f.config().contains("default: crux-opencode"));
            }
            crate::runtime::write_atomic(
                &path,
                "default: 'null'\nagents:\n  'null':\n    runtime: codex\n",
            )
            .unwrap();
            sync(&f.env);
            assert!(f.config().contains("default: 'null'"));
        });
    }

    #[test]
    fn unsupported_or_unreadable_stores_are_untouched_and_do_not_block_the_other_store() {
        isolated(
            "unsupported_or_unreadable_stores_are_untouched_and_do_not_block_the_other_store",
            |f| {
                let path = coral_agents_config_path(&f.env).unwrap();
                let initial = "agents: {mine: {runtime: codex}}\ndefault: mine\n";
                crate::runtime::write_atomic(&path, initial).unwrap();
                sync(&f.env);
                assert_eq!(f.config(), initial);
                assert!(fs::read_to_string(user_coral_agents_config_path().unwrap())
                    .unwrap()
                    .contains("crux-opencode"));
                assert!(fs::read_to_string(f.env.data_dir().join("debug.log"))
                    .unwrap()
                    .contains("CORAL binding sync failed"));
                fs::write(&path, [0xff, 0xfe]).unwrap();
                sync(&f.env);
                assert_eq!(fs::read(&path).unwrap(), [0xff, 0xfe]);
            },
        );
    }

    fn copy_tree(src: &Path, dst: &Path) {
        fs::create_dir_all(dst).unwrap();
        for entry in fs::read_dir(src).unwrap() {
            let path = entry.unwrap().path();
            let target = dst.join(path.file_name().unwrap());
            if path.is_dir() {
                copy_tree(&path, &target);
            } else {
                fs::copy(path, target).unwrap();
            }
        }
    }

    #[test]
    fn bundled_coral_skills_and_experts_deploy_from_registered_resources() {
        let f = Fixture::new();
        let tauri_root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../apps/desktop/src-tauri");
        let manifest: Value = serde_json::from_str(include_str!(
            "../../../apps/desktop/src-tauri/tauri.conf.json"
        ))
        .unwrap();
        for (source, target) in manifest["bundle"]["resources"].as_object().unwrap() {
            let target = target.as_str().unwrap();
            if ["skills-crux/", "profile/agent/"].contains(&target) {
                copy_tree(
                    &tauri_root.join(source),
                    &f.dir.join("resources").join(target),
                );
            }
        }
        crate::runtime::deploy_bundled_skills(&f.env);
        crate::runtime::deploy_profile_prompts(&f.env);
        let profile = crate::runtime::xdg_config_home(&f.env)
            .unwrap()
            .join("opencode");
        for name in [
            "crux-quickstart",
            "setting-up-crux",
            "creating-a-crux-task",
            "running-crux-experiments",
        ] {
            assert!(profile.join("skills").join(name).join("SKILL.md").is_file());
        }
        for path in [
            "crux-quickstart/scripts/new-crux-workspace.sh",
            "creating-a-crux-task/references/cookbook.md",
            "creating-a-crux-task/references/grader-api.md",
            "creating-a-crux-task/references/rubric-judges.md",
            "creating-a-crux-task/references/task-yaml.md",
            "running-crux-experiments/references/scaling-and-ops.md",
            "running-crux-experiments/references/steering.md",
        ] {
            assert!(profile.join("skills").join(path).is_file());
        }
        for name in ["crux-task-author", "crux-run-doctor"] {
            let prompt =
                fs::read_to_string(profile.join("agent").join(format!("{name}.md"))).unwrap();
            let frontmatter = prompt.split("---").nth(1).unwrap();
            assert!(frontmatter.contains("mode: subagent"));
            assert!(!frontmatter.contains("name:") && !frontmatter.contains("tools:"));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_ne!(
                fs::metadata(
                    profile.join("skills/crux-quickstart/scripts/new-crux-workspace.sh")
                )
                .unwrap()
                .permissions()
                .mode()
                    & 0o111,
                0
            );
        }
    }

    #[test]
    fn bundled_executables_are_first_on_the_enriched_path() {
        let path = crate::runtime::enriched_path();
        assert_eq!(
            std::env::split_paths(&path).next().unwrap(),
            std::env::current_exe().unwrap().parent().unwrap()
        );
    }

    #[cfg(unix)]
    fn executable(path: &Path, script: &str) {
        use std::os::unix::fs::PermissionsExt;
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, script).unwrap();
        fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
    }

    #[test]
    #[cfg(unix)]
    fn wrappers_forward_arguments_profile_environment_and_coral_overrides() {
        isolated(
            "wrappers_forward_arguments_profile_environment_and_coral_overrides",
            |f| {
                use std::os::unix::fs::PermissionsExt;
                let env = Env::new(
                    f.dir.join("profile with ' $` spaces"),
                    f.dir.join("resources"),
                    None,
                    "test".into(),
                );
                let root = crate::runtime::runtime_root(&env).unwrap();
                let fake_bin = f.dir.join("fake-bin");
                executable(&fake_bin.join("opencode"), "#!/bin/sh\nprintf '%s\\n' \"$XDG_CONFIG_HOME\" \"$XDG_DATA_HOME\" \"$XDG_CACHE_HOME\" \"$XDG_STATE_HOME\" \"${OPENCODE_MODELS_PATH-unset}\" \"$@\"\n");
                executable(&fake_bin.join("uv"), FAKE_UV);
                executable(
                    &f.dir.join(".local/bin/coral"),
                    "#!/bin/sh\nif [ \"$1\" = --capabilities ]; then echo 'ledger:v1 board radio oracle'; exit; fi\nprintf '%s\\n' \"$CORAL_AGENTS_CONFIG\" \"$@\"\n",
                );
                sync(&env);
                let bin = bin_dir(&env).unwrap();
                let path = format!("{}:{}", fake_bin.display(), crate::runtime::enriched_path());
                let output = crate::runtime::quiet_command(bin.join("crux-opencode"))
                    .args(["run", "a 'quoted' $argument"])
                    .env("PATH", &path)
                    .env_remove("OPENCODE_MODELS_PATH")
                    .output()
                    .unwrap();
                assert!(
                    output.status.success(),
                    "{}",
                    String::from_utf8_lossy(&output.stderr)
                );
                let stdout = String::from_utf8(output.stdout).unwrap();
                assert_eq!(
                    stdout.lines().collect::<Vec<_>>(),
                    [
                        root.join("xdg-config").to_string_lossy(),
                        root.join("xdg-data").to_string_lossy(),
                        root.join("xdg-cache").to_string_lossy(),
                        root.join("xdg-state").to_string_lossy(),
                        "unset".into(),
                        "run".into(),
                        "a 'quoted' $argument".into(),
                    ]
                );
                let isolated = crate::runtime::quiet_command(bin.join("crux-opencode"))
                    .env("PATH", &path)
                    .env("CORAL_DIR", f.dir.join("run/.coral"))
                    .env("XDG_CONFIG_HOME", f.dir.join("agent/config"))
                    .env("XDG_DATA_HOME", f.dir.join("agent/data"))
                    .env("XDG_STATE_HOME", f.dir.join("agent/state"))
                    .output()
                    .unwrap();
                assert!(isolated.status.success());
                let own = String::from_utf8(isolated.stdout).unwrap();
                assert!(own.contains(f.dir.join("agent/config").to_str().unwrap()));
                assert!(!own.contains(root.join("xdg-data").to_str().unwrap()));
                assert!(!crate::runtime::quiet_command(bin.join("crux-opencode"))
                    .env("PATH", &path)
                    .env("CORAL_DIR", f.dir.join("run/.coral"))
                    .env("XDG_DATA_HOME", root.join("xdg-data"))
                    .output()
                    .unwrap()
                    .status
                    .success());
                let catalog = crate::model_prices::catalog_path(&root);
                crate::runtime::write_atomic(&catalog, "{}").unwrap();
                sync(&env);
                assert!(fs::read_to_string(coral_agents_config_path(&env).unwrap())
                    .unwrap()
                    .contains("OPENCODE_MODELS_PATH"));
                let output = crate::runtime::quiet_command(bin.join("crux-opencode"))
                    .env("PATH", &path)
                    .env_remove("OPENCODE_MODELS_PATH")
                    .output()
                    .unwrap();
                assert!(output.status.success());
                assert!(String::from_utf8(output.stdout)
                    .unwrap()
                    .contains(catalog.to_str().unwrap()));
                for override_path in [None, Some("/custom/coral config.yaml")] {
                    let mut cmd = crate::runtime::quiet_command(bin.join("coral"));
                    cmd.args(["show", "one argument"])
                        .env("HOME", &f.dir)
                        .env("PATH", &path);
                    match override_path {
                        Some(path) => {
                            cmd.env("CORAL_AGENTS_CONFIG", path);
                            cmd.env("CRUX_AGENTS_CONFIG", path);
                        }
                        None => {
                            cmd.env_remove("CORAL_AGENTS_CONFIG");
                            cmd.env_remove("CRUX_AGENTS_CONFIG");
                        }
                    }
                    let output = cmd.output().unwrap();
                    assert!(
                        output.status.success(),
                        "{}",
                        String::from_utf8_lossy(&output.stderr)
                    );
                    let stdout = String::from_utf8(output.stdout).unwrap();
                    assert_eq!(
                        stdout.lines().collect::<Vec<_>>(),
                        [
                            override_path.map(String::from).unwrap_or_else(|| {
                                coral_agents_config_path(&env)
                                    .unwrap()
                                    .to_string_lossy()
                                    .into_owned()
                            }),
                            "show".into(),
                            "one argument".into(),
                        ]
                    );
                }
                assert_eq!(
                    fs::metadata(&bin).unwrap().permissions().mode() & 0o777,
                    0o700
                );
                assert_eq!(
                    fs::metadata(coral_agents_config_path(&env).unwrap())
                        .unwrap()
                        .permissions()
                        .mode()
                        & 0o777,
                    0o600
                );
            },
        );
    }

    #[test]
    #[cfg(unix)]
    fn coral_wrapper_uses_uv_for_an_explicit_source_checkout() {
        isolated(
            "coral_wrapper_uses_uv_for_an_explicit_source_checkout",
            |f| {
                let source = f.dir.join("checkout with ' $` spaces");
                fs::create_dir_all(&source).unwrap();
                fs::write(source.join("pyproject.toml"), "[project]\nname='coral'\n").unwrap();
                let fake_bin = f.dir.join("fake-bin");
                executable(&fake_bin.join("uv"), FAKE_UV);
                sync(&f.env);
                fs::create_dir_all(f.dir.join(".local/bin")).unwrap();
                let _ = fs::remove_file(f.dir.join(".local/bin/coral"));
                std::os::unix::fs::symlink(
                    bin_dir(&f.env).unwrap().join("coral"),
                    f.dir.join(".local/bin/coral"),
                )
                .unwrap();
                let output = crate::runtime::quiet_command(bin_dir(&f.env).unwrap().join("coral"))
                    .args(["--help", "one argument"])
                    .env("HOME", &f.dir)
                    .env("CORAL_SOURCE_DIR", &source)
                    .env(
                        "PATH",
                        format!("{}:{}", fake_bin.display(), crate::runtime::enriched_path()),
                    )
                    .output()
                    .unwrap();
                assert!(output.status.success());
                assert_eq!(
                    String::from_utf8(output.stdout)
                        .unwrap()
                        .lines()
                        .collect::<Vec<_>>(),
                    [
                        "--directory",
                        source.to_str().unwrap(),
                        "run",
                        "coral",
                        "--help",
                        "one argument",
                    ]
                );
            },
        );
    }

    #[test]
    #[cfg(unix)]
    fn setup_script_prefers_bundled_uv_and_supports_local_and_remote_installs() {
        let f = Fixture::new();
        let script = f.dir.join("scripts/dev/setup-crux-engine.sh");
        fs::create_dir_all(script.parent().unwrap()).unwrap();
        fs::write(&script, include_str!("../../../scripts/dev/setup-crux-engine.sh")).unwrap();
        let fake_bin = f.dir.join("fake-bin");
        executable(
            &fake_bin.join("rustc"),
            "#!/bin/sh\nprintf 'host: fake-target\\n'\n",
        );
        executable(&fake_bin.join("uv"), "#!/bin/sh\nexit 99\n");
        let bundled_uv = f.dir.join("apps/desktop/src-tauri/binaries/uv-fake-target");
        executable(
            &bundled_uv,
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$UV_ARGS\"\n",
        );
        executable(
            &f.dir.join(".local/bin/coral"),
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$CORAL_ARGS\"\n",
        );
        let checkout = f.dir.join("CORAL");
        fs::create_dir_all(&checkout).unwrap();
        fs::write(checkout.join("pyproject.toml"), "[project]\nname='coral'\n").unwrap();
        for local in [true, false] {
            if !local {
                fs::remove_dir_all(&checkout).unwrap();
            }
            let status = crate::runtime::quiet_command("bash")
                .arg(&script)
                .env("HOME", &f.dir)
                .env_remove("CORAL_SOURCE_DIR")
                .env(
                    "PATH",
                    format!("{}:{}", fake_bin.display(), crate::runtime::enriched_path()),
                )
                .env("UV_ARGS", f.dir.join("uv-args"))
                .env("CORAL_ARGS", f.dir.join("coral-args"))
                .status()
                .unwrap();
            assert!(status.success());
            let args = fs::read_to_string(f.dir.join("uv-args")).unwrap();
            if local {
                assert_eq!(
                    args.lines().collect::<Vec<_>>(),
                    [
                        "tool",
                        "install",
                        "--force",
                        "--editable",
                        &format!("{}[ui]", checkout.display())
                    ]
                );
            } else {
                assert_eq!(
                    args.lines().collect::<Vec<_>>(),
                    [
                        "tool",
                        "install",
                        "--force",
                        "git+https://github.com/Human-Agent-Society/CORAL.git"
                    ]
                );
            }
            assert_eq!(
                fs::read_to_string(f.dir.join("coral-args")).unwrap(),
                "--help\n"
            );
        }
    }
}
