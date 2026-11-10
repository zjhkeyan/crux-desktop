#!/usr/bin/env bash
# Install the Crux discovery engine with Crux's bundled uv, preferring a local editable checkout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
target="$(rustc -vV 2>/dev/null | sed -n 's/^host: //p' || true)"
UV_BIN="$ROOT/apps/desktop/src-tauri/binaries/uv-$target"
if [ ! -x "$UV_BIN" ] && [ -x "$UV_BIN.exe" ]; then
  UV_BIN="$UV_BIN.exe"
elif [ ! -x "$UV_BIN" ]; then
  UV_BIN="$(command -v uv || true)"
fi
if [ -z "$UV_BIN" ]; then
  echo "uv was not found; fetch Crux's uv sidecar or install uv first." >&2
  exit 1
fi

mkdir -p "$HOME/.local/bin"
if ! command -v uv >/dev/null 2>&1 && [ ! -e "$HOME/.local/bin/uv" ]; then
  ln -s "$UV_BIN" "$HOME/.local/bin/uv"
fi

ENGINE_DIR="${CRUX_ENGINE_SOURCE_DIR:-${CORAL_SOURCE_DIR:-$ROOT/CORAL}}"
if [ -f "$ENGINE_DIR/pyproject.toml" ]; then
  "$UV_BIN" tool install --force --editable "$ENGINE_DIR[ui]"
elif [ -f "$ROOT/CORAL/pyproject.toml" ]; then
  "$UV_BIN" tool install --force --editable "$ROOT/CORAL[ui]"
else
  "$UV_BIN" tool install --force "git+https://github.com/Human-Agent-Society/CORAL.git"
fi

if [ -x "$HOME/.local/bin/crux-engine" ]; then
  "$HOME/.local/bin/crux-engine" --help
else
  "$HOME/.local/bin/coral" --help
fi
