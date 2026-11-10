// Ported from Crux (github.com/ai4s-research/open-science, MIT): `src/main/git/worktrees/creation/worktree-add.ts`
// (lines 91-157) — records `branch.<branch>.base` and `push.autoSetupRemote` on created worktrees.
import { gitExecFileAsync, gitOptionsForWorktree, type GitRuntimeOptions } from './git-exec-file'

export async function persistWorktreeCreationBase(
  worktreePath: string,
  branch: string,
  effectiveBase: string,
  options: GitRuntimeOptions = {}
): Promise<void> {
  const configKey = `branch.${branch}.base`
  try {
    await gitExecFileAsync(['config', '--local', '--replace-all', configKey, effectiveBase], {
      ...gitOptionsForWorktree(worktreePath, options)
    })
  } catch (error) {
    console.warn(`addWorktree: failed to set ${configKey} for ${worktreePath}`, error)
    try {
      await gitExecFileAsync(['config', '--local', '--unset-all', configKey], {
        ...gitOptionsForWorktree(worktreePath, options)
      })
    } catch (unsetError) {
      console.warn(
        `addWorktree: failed to unset stale ${configKey} for ${worktreePath}`,
        unsetError
      )
    }
  }
}

export async function configurePushAutoSetupRemote(
  worktreePath: string,
  options: GitRuntimeOptions = {}
): Promise<void> {
  try {
    let alreadySet = false
    try {
      await gitExecFileAsync(['config', '--get', 'push.autoSetupRemote'], {
        ...gitOptionsForWorktree(worktreePath, options)
      })
      alreadySet = true
    } catch (readError) {
      const code = (readError as { code?: unknown })?.code
      if (code !== 1) {
        throw readError
      }
    }
    if (!alreadySet) {
      await gitExecFileAsync(['config', '--local', 'push.autoSetupRemote', 'true'], {
        ...gitOptionsForWorktree(worktreePath, options)
      })
    }
  } catch (error) {
    console.warn(`addWorktree: failed to set push.autoSetupRemote for ${worktreePath}`, error)
  }
}

export async function unsetWorktreeCreationBase(
  worktreePath: string,
  branch: string,
  options: GitRuntimeOptions = {}
): Promise<void> {
  try {
    await gitExecFileAsync(['config', '--local', '--unset-all', `branch.${branch}.base`], {
      ...gitOptionsForWorktree(worktreePath, options)
    })
  } catch {}
}
