#!/bin/sh
# The script is passed as argv, leaving stdin available for the binary stream.
set -eu
mode=${1:-connect}
version=${2:-}
expected=${3:-}
compressed_size=${4:-0}
arch=$(uname -m)
os=$(uname -s)
pinned_node=$(hostname -f 2>/dev/null || hostname)
scratch=${SCRATCH:-${TMPDIR:-}}
json_string() {
    # json encoder without requiring Python on a first-contact host.
    printf '%s' "$1" | LC_ALL=C awk 'BEGIN {printf "\""} {if (NR > 1) printf "\\n"; gsub(/\\/,"\\\\"); gsub(/\"/,"\\\""); gsub(/\r/,"\\r"); gsub(/\t/,"\\t"); printf "%s",$0} END {printf "\""}'
}
sha256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d ' ' -f1; else shasum -a 256 "$1" | cut -d ' ' -f1; fi; }
gpu=$(nvidia-smi -L 2>/dev/null || :)
slurm=false
if command -v sinfo >/dev/null 2>&1 && command -v squeue >/dev/null 2>&1; then slurm=true; fi
uv=false; command -v uv >/dev/null 2>&1 && uv=true
python=false; command -v python3 >/dev/null 2>&1 && python=true
outbound=false
if command -v curl >/dev/null 2>&1; then curl --silent --head --connect-timeout 2 --max-time 3 https://api.openai.com >/dev/null 2>&1 && outbound=true; fi
glibc=$(ldd --version 2>/dev/null | head -n1 || :)
binary="$HOME/.crux/bin/crux-$version-$arch"
installed=false
if test -n "$version" && test -f "$binary"; then
    cached_expected=$expected
    if test -z "$cached_expected" && test -f "$binary.sha256"; then cached_expected=$(cat "$binary.sha256"); fi
    if test -n "$cached_expected" && test "$(sha256 "$binary")" = "$cached_expected"; then installed=true; fi
fi
if test "$installed" = false && test -z "$expected" && command -v crux >/dev/null 2>&1; then binary=$(command -v crux); installed=true; fi
printf '\036CRUX1 {"t":"hello","protocol":1,"info":{"os":%s,"arch":%s,"pinned_node":%s,"home":%s,"scratch_root":%s,"gpu":%s,"slurm":%s,"uv":%s,"python3":%s,"outbound_https":%s,"glibc":%s,"installed":%s}}\n' "$(json_string "$os")" "$(json_string "$arch")" "$(json_string "$pinned_node")" "$(json_string "$HOME")" "$(json_string "$scratch")" "$(json_string "$gpu")" "$slurm" "$uv" "$python" "$outbound" "$(json_string "$glibc")" "$installed"
if test "$mode" = probe; then exit 0; fi
if test "$installed" = false; then
    case "$version" in ''|*[!a-zA-Z0-9._-]*) echo 'A verified Linux Crux binary is required' >&2; exit 1;; esac
    case "$expected" in *[!a-fA-F0-9]*|'') exit 1;; esac
    test "${#expected}" = 64 || exit 1
    case "$compressed_size" in ''|*[!0-9]*) exit 1;; esac
    test "$compressed_size" -gt 0 || exit 1
    umask 077
    mkdir -p "$HOME/.crux/bin"
    tmp="$HOME/.crux/bin/.tmp.$$"
    trap 'rm -f "$tmp" "$tmp.gz"' EXIT HUP INT TERM
    # Read exactly the blob bytes; later control frames remain in stdin.
    head -c "$compressed_size" > "$tmp.gz"
    test "$(wc -c < "$tmp.gz" | tr -d ' ')" = "$compressed_size" || exit 1
    gzip -dc "$tmp.gz" > "$tmp"
    test "$(sha256 "$tmp")" = "$expected" || { echo 'Crux binary SHA256 mismatch' >&2; exit 1; }
    chmod 0755 "$tmp"
    mv -f "$tmp" "$binary"
    printf '%s\n' "$expected" > "$binary.sha256"
    rm -f "$tmp.gz"
    trap - EXIT HUP INT TERM
fi
exec "$binary" link-agent --stdio
