import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  buildCruxAgentLaunchCommand,
  detectInstalledCruxAgents,
  inspectCruxWorktreeDiff,
  listCruxWorktreeStatus,
  mergeCruxWorktreeTask,
  spawnCruxWorktreeTask
} from '../../../../../runtime/worktree/index'

describe('buildCruxAgentLaunchCommand (reusing Crux TUI_AGENT_CONFIG)', () => {
  it.each([
    ['claude', 'solve dft', '/tmp/c1', "CLAUDE_CONFIG_DIR=/tmp/c1 claude 'solve dft'"],
    ['codex', 'optimize ucb', '/tmp/x1', "CODEX_HOME=/tmp/x1 codex 'optimize ucb'"],
    ['opencode', 'fix bug', undefined, "opencode --prompt 'fix bug'"],
    ['grok', '--help', undefined, 'grok -- --help'],
    ['gemini', 'explain', undefined, 'gemini --prompt explain'],
    ['copilot', 'review', undefined, 'copilot -i review'],
    ['pi', 'hello', undefined, 'CRUX_PI_PREFILL=hello pi hello'],
    ['dsh', 'run', undefined, 'dsh-tui .']
  ])('formats %s launch command from Crux catalog', (agent, prompt, accountDir, expected) => {
    expect(buildCruxAgentLaunchCommand(agent, prompt, { accountDir })).toBe(expected)
  })
})

describe('Crux worktree lifecycle (spawn -> .worktreeinclude & shared symlinks -> diff -> verify -> merge)', () => {
  let repo: string

  beforeEach(() => {
    repo = mkdtempSync(join(tmpdir(), 'crux-crux-wt-'))
  })

  afterEach(() => {
    rmSync(repo, { recursive: true, force: true })
  })

  it('isolates parallel tasks, copies .worktreeinclude, links tools/, gates on verifyCmd, and merges cleanly', async () => {
    writeFileSync(join(repo, '.gitignore'), '.env\ntools/\n.worktrees/\n.crux/\n')
    writeFileSync(join(repo, '.worktreeinclude'), '.env\n')
    writeFileSync(join(repo, '.env'), 'API_KEY=secret\n')
    mkdirSync(join(repo, 'tools'), { recursive: true })
    writeFileSync(join(repo, 'tools', 'eval.sh'), '#!/bin/sh\nexit 0\n')

    const taskA = await spawnCruxWorktreeTask({
      repoRoot: repo,
      taskId: 'solver-a',
      agent: 'claude',
      prompt: 'Direction A'
    })
    const taskB = await spawnCruxWorktreeTask({
      repoRoot: repo,
      taskId: 'solver-b',
      agent: 'codex',
      prompt: 'Direction B'
    })

    // Both worktrees receive .worktreeinclude (.env copy) and shared tools/ symlink
    expect(readFileSync(join(taskA.worktreePath, '.env'), 'utf8')).toBe('API_KEY=secret\n')
    expect(existsSync(join(taskB.worktreePath, 'tools', 'eval.sh'))).toBe(true)

    // Parallel isolated writes in worktree A and worktree B never collide
    writeFileSync(join(taskA.worktreePath, 'solver.txt'), 'score=40\n')
    writeFileSync(join(taskB.worktreePath, 'solver.txt'), 'score=99\n')

    const status = await listCruxWorktreeStatus(repo)
    expect(status).toHaveLength(2)

    // Failing verification gate blocks merge and marks task failed
    await expect(
      mergeCruxWorktreeTask({
        repoRoot: repo,
        taskId: 'solver-a',
        verifyCmd: 'exit 1'
      })
    ).rejects.toThrow(/Pre-merge verification failed/)
    expect((await inspectCruxWorktreeDiff(repo, 'solver-a', false)).record.status).toBe('failed')

    // Passing verification gate unlinks shared symlinks, commits, merges --no-ff, and cleans up worktree
    const merged = await mergeCruxWorktreeTask({
      repoRoot: repo,
      taskId: 'solver-b',
      verifyCmd: 'grep -q "score=99" solver.txt',
      cleanup: true
    })
    expect(merged.record.status).toBe('merged')
    expect(readFileSync(join(repo, 'solver.txt'), 'utf8')).toBe('score=99\n')
    expect(existsSync(taskB.worktreePath)).toBe(false)

    const detected = await detectInstalledCruxAgents()
    expect(detected.catalog.length).toBeGreaterThan(40)
  })
})
