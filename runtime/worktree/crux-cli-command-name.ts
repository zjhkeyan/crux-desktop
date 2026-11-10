// Ported from Crux (github.com/ai4s-research/open-science, MIT): `src/shared/crux-cli-command-name.ts`,
// minus Electron's `app-environment` singleton.
export function getCruxCliCommandNameForPlatform(platform: NodeJS.Platform): string {
  if (platform === 'linux') {
    return 'crux-ide'
  }
  if (platform === 'win32') {
    return 'crux.cmd'
  }
  return 'crux'
}

/** The GNOME-conflict `crux-ide` rename is desktop-only: SSH relays and headless servers put plain `crux` on PATH. */
export function skipsLinuxCruxCliRename(isRemote: boolean | undefined): boolean {
  return Boolean(isRemote)
}
