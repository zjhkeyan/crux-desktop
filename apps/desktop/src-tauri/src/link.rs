//! Desktop IPC for core Link operations; credentials and SSH policy stay in core.
use osd_core::{
    link::{
        artifacts::ArtifactEntry,
        openssh::{OpenSshConfig, OpenSshTransport},
        LinkTransport,
    },
    remote_hosts::{self, RemoteHostProfile},
};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};
use tauri::{AppHandle, Manager};

#[derive(Default)]
pub struct LinkState {
    links: Mutex<HashMap<String, OpenSshTransport>>,
    cancellations: Mutex<HashMap<String, osd_core::link::openssh::LinkCancellation>>,
    closing: AtomicBool,
}

fn cancel_host(app: &AppHandle, host_id: &str) -> Result<(), String> {
    let state = app.state::<LinkState>();
    let cancellation = state
        .cancellations
        .lock()
        .map_err(|e| e.to_string())?
        .remove(host_id);
    if let Some(cancellation) = cancellation {
        cancellation.cancel()?;
    }
    state
        .links
        .lock()
        .map_err(|e| e.to_string())?
        .remove(host_id);
    Ok(())
}

#[tauri::command]
pub fn crux_link_list_hosts(app: AppHandle) -> Result<Vec<RemoteHostProfile>, String> {
    remote_hosts::list_hosts(&crate::env_of(&app))
}

#[tauri::command]
pub fn crux_link_save_host(
    app: AppHandle,
    mut profile: RemoteHostProfile,
    host_key: Option<String>,
    verified_fingerprint: Option<String>,
) -> Result<RemoteHostProfile, String> {
    let env = crate::env_of(&app);
    match (host_key, verified_fingerprint) {
        (Some(key), Some(fingerprint)) => {
            remote_hosts::pin_host_key(&env, &mut profile, &key, &fingerprint)?
        }
        (None, None) => remote_hosts::save_host(&env, profile.clone())?,
        _ => return Err("host key and verified fingerprint are both required".into()),
    }
    cancel_host(&app, &profile.id)?;
    Ok(profile)
}

#[tauri::command]
pub fn crux_link_delete_host(app: AppHandle, host_id: String) -> Result<(), String> {
    remote_hosts::delete_host(&crate::env_of(&app), &host_id)?;
    cancel_host(&app, &host_id)?;
    Ok(())
}

#[tauri::command]
pub async fn crux_link_preflight(app: AppHandle, host_id: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let env = crate::env_of(&app);
        let mut profile = remote_hosts::find_host(&env, &host_id)?;
        let mut command = remote_hosts::ssh_command(&env, &profile, false)?;
        command.arg(format!(
            "sh -c {} crux-bootstrap probe",
            remote_hosts::shell_quote(osd_core::link::BOOTSTRAP)
        ));
        let output = crate::ssh_session::run_link_command(&app, &profile.id, &command)?;
        let mut info = output
            .split_inclusive('\n')
            .filter_map(osd_core::link::control::decode_line)
            .find_map(|frame| match frame {
                Ok(osd_core::link::control::ControlFrame::Hello { info, .. }) => Some(info),
                _ => None,
            })
            .ok_or("SSH preflight returned no information; reconnect to the server")?;
        let observed = remote_hosts::observed_host_key(&env, &profile)?;
        profile.pinned_node = info["pinned_node"].as_str().map(str::to_string);
        if let Some(key) = observed {
            let fingerprint = remote_hosts::host_key_fingerprint(&key)?;
            remote_hosts::pin_host_key(&env, &mut profile, &key, &fingerprint)?;
            info["host_key_fingerprint"] = json!(fingerprint);
        }
        if profile.scratch_root.is_none() {
            profile.scratch_root = info["scratch_root"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(str::to_string);
        }
        remote_hosts::save_host(&env, profile)?;
        Ok(info)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn crux_link_pair_key(app: AppHandle, host_id: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let env = crate::env_of(&app);
        let mut host = remote_hosts::find_host(&env, &host_id)?;
        let (path, public_key) = remote_hosts::generate_ed25519_key(&env)?;
        let mut command = remote_hosts::ssh_command(&env, &host, false)?;
        command.arg(remote_hosts::authorized_keys_install_script(&public_key)?);
        crate::ssh_session::run_link_command(&app, &host.id, &command)?;
        host.paired_key_path = Some(path.to_string_lossy().into_owned());
        remote_hosts::save_host(&env, host.clone())?;
        let batch = remote_hosts::ssh_command(&env, &host, true)?
            .arg("true")
            .output()
            .map_err(|e| e.to_string())?
            .status
            .success();
        Ok(json!({"host":host,"paired":true,"batch_mode":batch}))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn crux_link_unpair_key(
    app: AppHandle,
    host_id: String,
) -> Result<RemoteHostProfile, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let env = crate::env_of(&app);
        let mut host = remote_hosts::find_host(&env, &host_id)?;
        let mut command = remote_hosts::ssh_command(&env, &host, false)?;
        command.arg(remote_hosts::unpair_remote_key_script());
        crate::ssh_session::run_link_command(&app, &host.id, &command)?;
        host.paired_key_path = None;
        remote_hosts::save_host(&env, host.clone())?;
        cancel_host(&app, &host_id)?;
        Ok(host)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn crux_link_harvest(
    app: AppHandle,
    host_id: String,
    paths: Vec<String>,
    destination: String,
) -> Result<Vec<ArtifactEntry>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let env = crate::env_of(&app);
        let root = osd_core::runtime::workspace_dir(&env)?;
        if destination.is_empty()
            || std::path::Path::new(&destination)
                .components()
                .any(|c| !matches!(c, std::path::Component::Normal(_)))
        {
            return Err("harvest destination must stay inside the workspace".into());
        }
        let state = app.state::<LinkState>();
        if state.closing.load(Ordering::Acquire) {
            return Err("Crux Link is shutting down".into());
        }
        let mut links = state.links.lock().map_err(|e| e.to_string())?;
        if links
            .get(&host_id)
            .is_some_and(|link| link.status() == osd_core::link::LinkStatus::Disconnected)
        {
            links.remove(&host_id);
        }
        if !links.contains_key(&host_id) {
            let host = remote_hosts::find_host(&env, &host_id)?;
            let mut link = OpenSshTransport::new(OpenSshConfig::new(&env, host)?);
            let cancellation = link.cancellation();
            state
                .cancellations
                .lock()
                .map_err(|e| e.to_string())?
                .insert(host_id.clone(), cancellation.clone());
            if state.closing.load(Ordering::Acquire) {
                cancellation.cancel()?;
                return Err("Crux Link is shutting down".into());
            }
            link.connect()?;
            links.insert(host_id.clone(), link);
        }
        let link = links.get_mut(&host_id).unwrap();
        let mut manifest = Vec::new();
        for path in paths {
            let target = format!("{destination}/{path}");
            manifest.push(link.get(&path, &root, &target)?);
        }
        Ok(manifest)
    })
    .await
    .map_err(|e| e.to_string())?
}

pub fn shutdown(app: &AppHandle) {
    let state = app.state::<LinkState>();
    state.closing.store(true, Ordering::Release);
    let cancellations: Vec<_> = state
        .cancellations
        .lock()
        .unwrap()
        .drain()
        .map(|(_, handle)| handle)
        .collect();
    for handle in cancellations {
        let _ = handle.cancel();
    }
    if let Ok(mut links) = state.links.lock() {
        links.clear();
    };
}
