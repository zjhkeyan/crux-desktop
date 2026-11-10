#!/usr/bin/env bash
# Client-only sidecar from the pinned upstream release. Never installs sshd.
set -euo pipefail
version=v9.8.1.0p1-Preview
case "${1:-x86_64-pc-windows-msvc}" in
  x86_64*|Win64) asset=OpenSSH-Win64.zip; checksum=c7a1369cd73c8165be00c66e90291c4dd67784de7c3aa3af18c68ebedffa6ea9 ;;
  i686*|Win32) asset=OpenSSH-Win32.zip; checksum=6794ac43d806b6474f5bc501b819c723b96b07605ca3df99b67805c7b659be8e ;;
  aarch64*|ARM64) asset=OpenSSH-ARM64.zip; checksum=89587076e80b416c3810bf2005fea6f35d093fbfabd9e45c167d245c23801562 ;;
  --self-test)
    bash -n "$0"
    printf '%s\n' 'Pinned Win32-OpenSSH manifest syntax OK'
    exit 0 ;;
  *) printf '%s\n' 'usage: fetch-win32-openssh.sh [Windows target] [output-directory]' >&2; exit 2 ;;
esac
root=$(cd -- "$(dirname -- "$0")/../.." && pwd)
destination=${2:-"$root/apps/desktop/src-tauri/binaries/win32-openssh"}
staging=$(mktemp -d "${TMPDIR:-/tmp}/crux-openssh.XXXXXXXX")
trap 'rm -rf -- "$staging"' EXIT
curl --fail --location --retry 3 --proto '=https' --tlsv1.2 \
  "https://github.com/PowerShell/Win32-OpenSSH/releases/download/$version/$asset" -o "$staging/$asset"
if command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$staging/$asset"); actual=${actual%% *}
else
  actual=$(shasum -a 256 "$staging/$asset"); actual=${actual%% *}
fi
if [[ "$actual" != "$checksum" ]]; then
  printf '%s\n' 'Win32-OpenSSH SHA256 mismatch; refusing to stage binaries' >&2
  exit 1
fi
if command -v unzip >/dev/null 2>&1; then
  unzip -q "$staging/$asset" -d "$staging/extracted"
else
  python3 -m zipfile -e "$staging/$asset" "$staging/extracted"
fi
source_dir="$staging/extracted/${asset%.zip}"
for binary in ssh.exe ssh-keygen.exe ssh-keyscan.exe scp.exe sftp.exe; do
  test -f "$source_dir/$binary"
done
mkdir -p -- "$destination"
for binary in ssh.exe ssh-keygen.exe ssh-keyscan.exe scp.exe sftp.exe; do
  cp -- "$source_dir/$binary" "$destination/$binary"
done
for file in "$source_dir/"*.dll "$source_dir/"*LICENSE* "$source_dir/"*license*; do
  if [[ -f "$file" ]]; then cp -- "$file" "$destination/"; fi
done
printf 'Staged Win32-OpenSSH %s (%s) in %s\n' "$version" "$asset" "$destination"
