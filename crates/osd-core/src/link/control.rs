#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frames_round_trip_without_treating_banners_as_control() {
        let frame = ControlFrame::Heartbeat { epoch: 4 };
        assert_eq!(
            encode_frame(&frame),
            "\u{1e}CRUX1 {\"t\":\"heartbeat\",\"epoch\":4}\n"
        );
        assert_eq!(decode_line(&encode_frame(&frame)).unwrap().unwrap(), frame);
        assert!(decode_line("Welcome to the cluster\n").is_none());
        assert!(decode_line("  CRUX1 {}\n").is_none());
        assert!(decode_line("\u{1e}CRUX1 not-json\n").unwrap().is_err());
    }
}
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const PREFIX: &str = "\u{1e}CRUX1 ";
pub const MAX_FRAME: usize = 2 * 1024 * 1024;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "t", rename_all = "snake_case")]
pub enum ControlFrame {
    Hello {
        protocol: u32,
        info: Value,
    },
    Preflight {
        info: Value,
    },
    ViewDelta {
        view: String,
        value: Value,
    },
    ExecReq {
        id: String,
        argv: Vec<String>,
    },
    ExecResp {
        id: String,
        exit_code: i32,
        stdout: String,
        stderr: String,
    },
    Suspending,
    Resumed {
        epoch: u64,
    },
    Heartbeat {
        epoch: u64,
    },
    ArtifactManifest {
        id: String,
        transfer: super::artifacts::ArtifactTransfer,
    },
    ReverseProbeReq {
        id: String,
        endpoint: String,
        nonce: String,
        bearer: Option<String>,
    },
    ReverseProbeResp {
        id: String,
        forward_ok: bool,
        error: Option<String>,
    },
}

pub fn encode_frame(frame: &ControlFrame) -> String {
    format!(
        "{PREFIX}{}\n",
        serde_json::to_string(frame).expect("control frame is JSON")
    )
}

/// Banners and shell startup output are deliberately not protocol errors.
pub fn decode_line(line: &str) -> Option<Result<ControlFrame, String>> {
    let body = line.strip_prefix(PREFIX)?;
    Some(if line.len() > MAX_FRAME {
        Err("control frame exceeds 2 MiB".into())
    } else {
        serde_json::from_str(body.trim_end_matches(['\r', '\n'])).map_err(|e| e.to_string())
    })
}
