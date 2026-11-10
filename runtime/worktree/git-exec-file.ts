// Thin `git` child_process seam for Crux's worktree modules (`check-ignored-paths.ts`,
// `worktree-add.ts`), matching the signature of Crux's `src/main/git/command-runner/git-exec-file.ts`.
import { spawn } from 'node:child_process'

export type GitRuntimeOptions = {
  cwd?: string
  stdin?: string
  timeout?: number
  env?: NodeJS.ProcessEnv
}

export function gitOptionsForWorktree(
  worktreePath: string,
  options: GitRuntimeOptions = {}
): GitRuntimeOptions {
  return { ...options, cwd: worktreePath }
}

export async function gitExecFileAsync(
  args: readonly string[],
  options: GitRuntimeOptions = {}
): Promise<{ stdout: string; stderr: string }> {
  return await new Promise((resolve, reject) => {
    const child = spawn('git', [...args], {
      cwd: options.cwd,
      env: options.env ?? process.env,
      stdio: ['pipe', 'pipe', 'pipe']
    })
    let stdout = ''
    let stderr = ''
    const timer =
      options.timeout && options.timeout > 0
        ? setTimeout(() => {
            child.kill('SIGKILL')
          }, options.timeout)
        : undefined
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => {
      stdout += chunk
    })
    child.stderr.on('data', (chunk: string) => {
      stderr += chunk
    })
    child.on('error', (err) => {
      if (timer) clearTimeout(timer)
      reject(err)
    })
    child.on('close', (code) => {
      if (timer) clearTimeout(timer)
      if (code === 0) {
        resolve({ stdout, stderr })
        return
      }
      const error = Object.assign(
        new Error(`git ${args.join(' ')} exited with code ${code}: ${stderr.trim() || stdout.trim()}`),
        { code: code ?? 1, stdout, stderr }
      )
      reject(error)
    })
    if (options.stdin !== undefined) {
      child.stdin.write(options.stdin)
    }
    child.stdin.end()
  })
}
