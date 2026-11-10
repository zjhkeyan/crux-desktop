// Worktree & Multi-CLI Agent Orchestration seam: thin adapter over Crux's
// `tui-agent-config`, `tui-agent-detection-commands`, `tui-agent-selection`,
// `worktree-include-file`, `worktree-symlinks`, and `worktree-lineage` modules
// (ported from github.com/ai4s-research/open-science, MIT, just like `runtime/computer/`).
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { promisify } from 'node:util'
import { gitExecFileAsync } from './git-exec-file'
import type { TuiAgent } from './tui-agent'
import {
  getTuiAgentLaunchCommand,
  isTuiAgent,
  TUI_AGENT_CONFIG
} from './tui-agent-config'
import {
  getTuiAgentDetectionProbeCommands,
  KNOWN_TUI_AGENT_DETECTION_COMMANDS,
  resolveDetectedTuiAgentIds
} from './tui-agent-detection-commands'
import { TUI_AGENT_DISPLAY_NAMES, tuiAgentDisplayName } from './tui-agent-display-names'
import { pickTuiAgent } from './tui-agent-selection'
import { formatWorktreeIncludeCopyWarning } from './worktree-include-copy-budget'
import { resolveWorktreeIncludePaths } from './worktree-include-file'
import {
  configurePushAutoSetupRemote,
  persistWorktreeCreationBase
} from './worktree-lineage'
import {
  createWorktreeCopiedPaths,
  createWorktreeSharedPaths,
  removeWorktreeSymlinks
} from './worktree-symlinks'

const execFileAsync = promisify(execFile)

export const WORKTREE_VERBS = [
  'agents',
  'spawn',
  'create',
  'set',
  'current',
  'status',
  'ps',
  'diff',
  'merge',
  'rm'
] as const

export type WorktreeVerb = (typeof WORKTREE_VERBS)[number]

export type WorkspaceStatus = 'todo' | 'in-progress' | 'in-review' | 'completed' | 'blocked'

export type WorktreeCheckpoint = {
  timestamp: string
  workspaceStatus: WorkspaceStatus
  comment: string
}

export type WorktreeTaskRecord = {
  taskId: string
  agent: string
  displayName: string
  worktreePath: string
  branch: string
  baseBranch: string
  host: string
  accountDir?: string
  screenId?: string
  paneId?: string
  status: 'running' | 'merged' | 'failed'
  workspaceStatus?: WorkspaceStatus
  comment?: string
  parentWorktree?: string
  checkpoints?: WorktreeCheckpoint[]
  launchCommand: string
  includeWarning?: string
  updatedAt: string
}

function shellQuote(value: string): string {
  if (/^[A-Za-z0-9_./:@=-]+$/.test(value)) {
    return value
  }
  return `'${value.replace(/'/g, `'\\''`)}'`
}

/** Build the terminal launch command directly from Crux's `TUI_AGENT_CONFIG` and `promptInjectionMode`. */
export function buildCruxAgentLaunchCommand(
  agent: string,
  prompt = '',
  opts: {
    platform?: NodeJS.Platform
    isRemote?: boolean
    accountDir?: string
  } = {}
): string {
  const platform = opts.platform ?? process.platform
  const envParts: string[] = []
  if (opts.accountDir) {
    if (agent === 'claude' || agent === 'claude-agent-teams' || agent === 'openclaude') {
      envParts.push(`CLAUDE_CONFIG_DIR=${shellQuote(opts.accountDir)}`)
    } else if (agent === 'codex') {
      envParts.push(`CODEX_HOME=${shellQuote(opts.accountDir)}`)
    }
  }
  if (!isTuiAgent(agent)) {
    const base = shellQuote(agent)
    const cmd = prompt ? `${base} ${shellQuote(prompt)}` : base
    return envParts.length > 0 ? `${envParts.join(' ')} ${cmd}` : cmd
  }
  const config = TUI_AGENT_CONFIG[agent]
  if (prompt && config.draftPromptEnvVar) {
    envParts.push(`${config.draftPromptEnvVar}=${shellQuote(prompt)}`)
  }
  const launchCmd = getTuiAgentLaunchCommand(config, platform, { isRemote: opts.isRemote })
  const prefix = envParts.length > 0 ? `${envParts.join(' ')} ` : ''
  if (!prompt) {
    return `${prefix}${launchCmd}`
  }
  const qPrompt = shellQuote(prompt)
  switch (config.promptInjectionMode) {
    case 'argv': {
      const sep = config.argvPromptSeparator ? ` ${config.argvPromptSeparator}` : ''
      return `${prefix}${launchCmd}${sep} ${qPrompt}`
    }
    case 'flag-prompt':
    case 'flag-prompt-interactive':
      return `${prefix}${launchCmd} --prompt ${qPrompt}`
    case 'flag-interactive':
      return `${prefix}${launchCmd} -i ${qPrompt}`
    default:
      return `${prefix}${launchCmd}`
  }
}

/** Probe PATH using Crux's `KNOWN_TUI_AGENT_DETECTION_COMMANDS` and `resolveDetectedTuiAgentIds`. */
export async function detectInstalledCruxAgents(
  platform: NodeJS.Platform = process.platform
): Promise<{
  detectedIds: TuiAgent[]
  preferredDefault: TuiAgent | null
  catalog: Array<{
    id: TuiAgent
    displayName: string
    detectCmd: string
    launchCmd: string
    promptInjectionMode: string
    installed: boolean
  }>
}> {
  const probes = getTuiAgentDetectionProbeCommands(KNOWN_TUI_AGENT_DETECTION_COMMANDS, platform)
  const found = new Set<string>()
  await Promise.all(
    probes.map(async (cmd) => {
      try {
        await execFileAsync('which', [cmd])
        found.add(cmd)
      } catch {}
    })
  )
  const detectedIds = resolveDetectedTuiAgentIds(
    KNOWN_TUI_AGENT_DETECTION_COMMANDS,
    found,
    platform
  )
  const detectedSet = new Set(detectedIds)
  const preferredDefault = pickTuiAgent(null, detectedIds)
  const catalog = (Object.keys(TUI_AGENT_CONFIG) as TuiAgent[]).map((id) => {
    const cfg = TUI_AGENT_CONFIG[id]
    return {
      id,
      displayName: TUI_AGENT_DISPLAY_NAMES[id],
      detectCmd: cfg.detectCmd,
      launchCmd: getTuiAgentLaunchCommand(cfg, platform),
      promptInjectionMode: cfg.promptInjectionMode,
      installed: detectedSet.has(id)
    }
  })
  return { detectedIds, preferredDefault, catalog }
}

async function ensureGitRepository(repoRoot: string): Promise<string> {
  await mkdir(repoRoot, { recursive: true })
  try {
    await gitExecFileAsync(['rev-parse', '--is-inside-work-tree'], { cwd: repoRoot })
  } catch {
    await gitExecFileAsync(['init', '-b', 'main'], { cwd: repoRoot })
  }
  try {
    await gitExecFileAsync(['rev-parse', '--verify', 'HEAD'], { cwd: repoRoot })
  } catch {
    await gitExecFileAsync(['commit', '--allow-empty', '-m', 'chore: initialize repository'], {
      cwd: repoRoot
    })
  }
  try {
    const { stdout } = await gitExecFileAsync(['symbolic-ref', '--short', 'HEAD'], {
      cwd: repoRoot
    })
    return stdout.trim() || 'HEAD'
  } catch {
    return 'HEAD'
  }
}

function registryPath(repoRoot: string): string {
  return join(repoRoot, '.crux', 'crux-worktrees.json')
}

async function loadRegistry(repoRoot: string): Promise<Record<string, WorktreeTaskRecord>> {
  const file = registryPath(repoRoot)
  if (!existsSync(file)) {
    return {}
  }
  const raw = JSON.parse(await readFile(file, 'utf8')) as {
    tasks?: Record<string, WorktreeTaskRecord>
  }
  return raw.tasks ?? {}
}

async function saveRegistry(
  repoRoot: string,
  tasks: Record<string, WorktreeTaskRecord>
): Promise<void> {
  const file = registryPath(repoRoot)
  await mkdir(join(repoRoot, '.crux'), { recursive: true })
  await writeFile(
    file,
    `${JSON.stringify({ schemaVersion: 1, tasks }, null, 2)}\n`,
    'utf8'
  )
}

export const DEFAULT_SHARED_DIRS = ['tools', 'MEMORY.md', '.openscience/memory'] as const

/** Create an isolated Git worktree using Crux's `.worktreeinclude` copy budget, shared symlinks, and lineage config. */
export async function spawnCruxWorktreeTask(args: {
  repoRoot: string
  taskId: string
  agent?: string
  prompt?: string
  baseBranch?: string
  host?: string
  accountDir?: string
  sharedDirs?: readonly string[]
  openPane?: boolean
  workspaceStatus?: WorkspaceStatus
  comment?: string
  parentWorktree?: string
}): Promise<WorktreeTaskRecord> {
  const repoRoot = resolve(args.repoRoot)
  const taskId = args.taskId.trim()
  if (!taskId || taskId.includes('/') || taskId.includes('..')) {
    throw new Error(`Invalid taskId: ${args.taskId}`)
  }
  const detectedBase = await ensureGitRepository(repoRoot)
  const baseBranch = args.baseBranch || detectedBase
  const branch = `crux/${taskId}`
  const worktreePath = join(repoRoot, '.worktrees', taskId)
  await mkdir(join(repoRoot, '.worktrees'), { recursive: true })

  if (!existsSync(worktreePath)) {
    let branchExists = false
    try {
      await gitExecFileAsync(['show-ref', '--verify', `refs/heads/${branch}`], { cwd: repoRoot })
      branchExists = true
    } catch {}
    if (branchExists) {
      await gitExecFileAsync(['worktree', 'add', worktreePath, branch], { cwd: repoRoot })
    } else {
      await gitExecFileAsync(['worktree', 'add', '-b', branch, worktreePath, baseBranch], {
        cwd: repoRoot
      })
    }
  }

  // Directly invoke Crux's lineage persistence (`branch.<branch>.base` + `push.autoSetupRemote`)
  await persistWorktreeCreationBase(worktreePath, branch, baseBranch)
  await configurePushAutoSetupRemote(worktreePath)

  // Directly invoke Crux's `.worktreeinclude` resolver and copy-budget materializer
  const includePaths = await resolveWorktreeIncludePaths(repoRoot)
  const skipped =
    includePaths.length > 0
      ? await createWorktreeCopiedPaths(repoRoot, worktreePath, includePaths)
      : []
  const includeWarning = formatWorktreeIncludeCopyWarning(skipped)

  // Directly invoke Crux's shared symlink materializer (`createWorktreeSharedPaths`)
  const sharedPaths = args.sharedDirs ?? DEFAULT_SHARED_DIRS
  await createWorktreeSharedPaths(repoRoot, worktreePath, sharedPaths)

  const agent = args.agent ?? 'claude'
  const host = args.host ?? 'local'
  const launchCommand = buildCruxAgentLaunchCommand(agent, args.prompt ?? '', {
    isRemote: host !== 'local',
    accountDir: args.accountDir
  })

  let screenId: string | undefined
  let paneId: string | undefined
  if (host !== 'local') {
    const rRoot = `/tmp/crux-remote-${ taskId }`
    await execFileAsync('crux', [
      'remote',
      'exec',
      host,
      '--',
      'bash',
      '-lc',
      `mkdir -p ${shellQuote(rRoot)}`
    ]).catch(() => undefined)
  } else if (args.openPane) {
    const fullCmd = `cd ${shellQuote(worktreePath)} && ${launchCommand}`
    const res = await execFileAsync('crux', [
      'screen',
      'new',
      '--terminals',
      '1',
      '--run',
      fullCmd,
      '--name',
      `Crux · ${taskId} (${tuiAgentDisplayName(agent) ?? agent})`,
      '--directory',
      worktreePath,
      '--json'
    ]).catch(() => null)
    if (res?.stdout) {
      try {
        const parsed = JSON.parse(res.stdout) as { id?: string; pane?: string }
        screenId = parsed.id
        paneId = parsed.pane
      } catch {}
    }
  }

  const nowIso = new Date().toISOString()
  const initialStatus: WorkspaceStatus = args.workspaceStatus ?? 'in-progress'
  const initialComment = args.comment?.trim() ?? ''
  const record: WorktreeTaskRecord = {
    taskId,
    agent,
    displayName: tuiAgentDisplayName(agent) ?? agent,
    worktreePath,
    branch,
    baseBranch,
    host,
    ...(args.accountDir ? { accountDir: args.accountDir } : {}),
    ...(screenId ? { screenId } : {}),
    ...(paneId ? { paneId } : {}),
    status: 'running',
    workspaceStatus: initialStatus,
    ...(initialComment ? { comment: initialComment } : {}),
    ...(args.parentWorktree ? { parentWorktree: args.parentWorktree } : {}),
    checkpoints: initialComment
      ? [{ timestamp: nowIso, workspaceStatus: initialStatus, comment: initialComment }]
      : [],
    launchCommand,
    ...(includeWarning ? { includeWarning } : {}),
    updatedAt: nowIso
  }
  const tasks = await loadRegistry(repoRoot)
  tasks[taskId] = record
  await saveRegistry(repoRoot, tasks)
  return record
}

/** Resolve an enclosing Crux-managed worktree from `cwd` (`crux worktree current`). */
export async function resolveCurrentCruxWorktree(
  repoRoot: string,
  cwd: string = process.cwd()
): Promise<WorktreeTaskRecord | null> {
  const root = resolve(repoRoot)
  const target = resolve(cwd)
  const tasks = await loadRegistry(root)
  for (const rec of Object.values(tasks)) {
    const wt = resolve(rec.worktreePath)
    if (target === wt || target.startsWith(`${wt}/`)) {
      return rec
    }
  }
  return null
}

/** Update Crux metadata and progress checkpoints for a worktree (`crux worktree set`). */
export async function setCruxWorktreeMetadata(args: {
  repoRoot: string
  taskId?: string
  cwd?: string
  displayName?: string
  workspaceStatus?: WorkspaceStatus
  comment?: string
  parentWorktree?: string | null
}): Promise<WorktreeTaskRecord> {
  const root = resolve(args.repoRoot)
  const tasks = await loadRegistry(root)
  let resolvedId = args.taskId?.trim()
  if (!resolvedId || resolvedId === 'current' || resolvedId === 'active') {
    const current = await resolveCurrentCruxWorktree(root, args.cwd ?? root)
    if (!current) {
      throw new Error(
        'Could not infer worktree from current directory. Pass taskId explicitly.'
      )
    }
    resolvedId = current.taskId
  }
  const record = tasks[resolvedId]
  if (!record) {
    throw new Error(`Unknown worktree taskId: ${resolvedId}`)
  }
  const nowIso = new Date().toISOString()
  if (typeof args.displayName === 'string' && args.displayName.trim()) {
    record.displayName = args.displayName.trim()
  }
  if (typeof args.workspaceStatus === 'string') {
    record.workspaceStatus = args.workspaceStatus
    if (args.workspaceStatus === 'completed' && record.status === 'running') {
      record.status = 'running'
    }
  }
  if (args.parentWorktree !== undefined) {
    if (args.parentWorktree === null || args.parentWorktree === 'null' || args.parentWorktree === '') {
      delete record.parentWorktree
    } else if (typeof args.parentWorktree === 'string') {
      record.parentWorktree = args.parentWorktree
    }
  }
  if (typeof args.comment === 'string') {
    const trimmed = args.comment.trim()
    if (!trimmed) {
      delete record.comment
    } else {
      record.comment = trimmed
      const checkpoints = record.checkpoints ?? []
      checkpoints.push({
        timestamp: nowIso,
        workspaceStatus: record.workspaceStatus ?? 'in-progress',
        comment: trimmed
      })
      record.checkpoints = checkpoints
    }
  }
  record.updatedAt = nowIso
  tasks[resolvedId] = record
  await saveRegistry(root, tasks)
  return record
}

/** Remove an Crux-managed worktree and unlink shared paths safely (`crux worktree rm`). */
export async function removeCruxWorktreeTask(args: {
  repoRoot: string
  taskId: string
  deleteBranch?: boolean
  sharedDirs?: readonly string[]
}): Promise<{ removed: string; branchDeleted: boolean }> {
  const root = resolve(args.repoRoot)
  const tasks = await loadRegistry(root)
  const record = tasks[args.taskId]
  if (!record) {
    throw new Error(`Unknown worktree taskId: ${args.taskId}`)
  }
  const sharedPaths = args.sharedDirs ?? DEFAULT_SHARED_DIRS
  if (existsSync(record.worktreePath)) {
    await removeWorktreeSymlinks(record.worktreePath, sharedPaths).catch(() => undefined)
    await gitExecFileAsync(['worktree', 'remove', '--force', record.worktreePath], {
      cwd: root
    }).catch(() => undefined)
  }
  let branchDeleted = false
  if (args.deleteBranch) {
    await gitExecFileAsync(['branch', '-D', record.branch], { cwd: root })
      .then(() => {
        branchDeleted = true
      })
      .catch(() => undefined)
  }
  delete tasks[args.taskId]
  await saveRegistry(root, tasks)
  return { removed: args.taskId, branchDeleted }
}

export async function inspectCruxWorktreeDiff(
  repoRoot: string,
  taskId: string,
  includePatch = true
): Promise<{
  record: WorktreeTaskRecord
  dirtyFiles: string[]
  commitsAhead: number
  diffStat: string
  patch: string
}> {
  const tasks = await loadRegistry(resolve(repoRoot))
  const record = tasks[taskId]
  if (!record) {
    throw new Error(`Unknown worktree taskId: ${taskId}`)
  }
  if (!existsSync(record.worktreePath)) {
    return { record, dirtyFiles: [], commitsAhead: 0, diffStat: '', patch: '' }
  }
  const { stdout: statusOut } = await gitExecFileAsync(['status', '--porcelain'], {
    cwd: record.worktreePath
  })
  const dirtyFiles = statusOut
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  const { stdout: aheadOut } = await gitExecFileAsync(
    ['rev-list', '--count', `${record.baseBranch}..HEAD`],
    { cwd: record.worktreePath }
  ).catch(() => ({ stdout: '0' }))
  const commitsAhead = Number.parseInt(aheadOut.trim(), 10) || 0
  const { stdout: diffStat } = await gitExecFileAsync(['diff', '--stat', record.baseBranch], {
    cwd: record.worktreePath
  }).catch(() => ({ stdout: '' }))
  const { stdout: patch } = includePatch
    ? await gitExecFileAsync(['diff', record.baseBranch], { cwd: record.worktreePath }).catch(
        () => ({ stdout: '' })
      )
    : { stdout: '' }
  return {
    record,
    dirtyFiles,
    commitsAhead,
    diffStat: diffStat.trim(),
    patch
  }
}

export async function mergeCruxWorktreeTask(args: {
  repoRoot: string
  taskId: string
  verifyCmd?: string
  cleanup?: boolean
  sharedDirs?: readonly string[]
}): Promise<{
  record: WorktreeTaskRecord
  mergedCommit: string
  diffStat: string
}> {
  const repoRoot = resolve(args.repoRoot)
  const tasks = await loadRegistry(repoRoot)
  const record = tasks[args.taskId]
  if (!record) {
    throw new Error(`Unknown worktree taskId: ${args.taskId}`)
  }
  const sharedPaths = args.sharedDirs ?? DEFAULT_SHARED_DIRS

  // Use Crux's `removeWorktreeSymlinks` before staging so shared symlinks are never committed into the branch
  await removeWorktreeSymlinks(record.worktreePath, sharedPaths)
  try {
    const { stdout: porcelain } = await gitExecFileAsync(['status', '--porcelain'], {
      cwd: record.worktreePath
    })
    if (porcelain.trim()) {
      await gitExecFileAsync(['add', '-A'], { cwd: record.worktreePath })
      await gitExecFileAsync(
        ['commit', '-m', `feat(${record.taskId}): finalize work from ${record.agent}`],
        { cwd: record.worktreePath }
      )
    }
    await createWorktreeSharedPaths(repoRoot, record.worktreePath, sharedPaths)

    if (args.verifyCmd) {
      try {
        await execFileAsync('bash', ['-lc', args.verifyCmd], { cwd: record.worktreePath })
      } catch (error) {
        record.status = 'failed'
        record.updatedAt = new Date().toISOString()
        tasks[record.taskId] = record
        await saveRegistry(repoRoot, tasks)
        const msg = error instanceof Error ? error.message : String(error)
        throw new Error(`Pre-merge verification failed (${args.verifyCmd}): ${msg}`)
      }
    }
  } finally {
    if (existsSync(record.worktreePath)) {
      await removeWorktreeSymlinks(record.worktreePath, sharedPaths)
    }
  }

  const diffInfo = await inspectCruxWorktreeDiff(repoRoot, record.taskId, false)
  await gitExecFileAsync(
    [
      'merge',
      '--no-ff',
      record.branch,
      '-m',
      `Merge Crux worktree ${record.branch} (${record.displayName})`
    ],
    { cwd: repoRoot }
  )
  const { stdout: headOut } = await gitExecFileAsync(['rev-parse', '--short', 'HEAD'], {
    cwd: repoRoot
  })

  if (args.cleanup) {
    await gitExecFileAsync(['worktree', 'remove', '--force', record.worktreePath], {
      cwd: repoRoot
    }).catch(() => undefined)
  } else if (existsSync(record.worktreePath)) {
    await createWorktreeSharedPaths(repoRoot, record.worktreePath, sharedPaths)
  }

  record.status = 'merged'
  record.updatedAt = new Date().toISOString()
  tasks[record.taskId] = record
  await saveRegistry(repoRoot, tasks)

  return {
    record,
    mergedCommit: headOut.trim(),
    diffStat: diffInfo.diffStat
  }
}

export async function listCruxWorktreeStatus(repoRoot: string): Promise<
  Array<
    WorktreeTaskRecord & {
      dirtyCount: number
      commitsAhead: number
      diffStat: string
    }
  >
> {
  const root = resolve(repoRoot)
  const tasks = await loadRegistry(root)
  const out = []
  for (const taskId of Object.keys(tasks)) {
    const info = await inspectCruxWorktreeDiff(root, taskId, false)
    out.push({
      ...info.record,
      dirtyCount: info.dirtyFiles.length,
      commitsAhead: info.commitsAhead,
      diffStat: info.diffStat
    })
  }
  return out
}
