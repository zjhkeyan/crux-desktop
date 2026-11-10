// CLI runner for `crux worktree <verb>` — directly reuses `runtime/worktree/index.ts`
// (Crux's worktree isolation, TUI agent catalog, metadata/checkpoint state, and merge gate).
import {
  detectInstalledCruxAgents,
  inspectCruxWorktreeDiff,
  listCruxWorktreeStatus,
  mergeCruxWorktreeTask,
  removeCruxWorktreeTask,
  resolveCurrentCruxWorktree,
  setCruxWorktreeMetadata,
  spawnCruxWorktreeTask,
  type WorkspaceStatus
} from './index'

async function main(): Promise<void> {
  const raw = process.argv[2]
  if (!raw) {
    throw new Error('Usage: node cli.mjs <json-payload>')
  }
  const payload = JSON.parse(raw) as {
    sub: string
    repoRoot: string
    cwd?: string
    taskId?: string
    agent?: string
    prompt?: string
    baseBranch?: string
    host?: string
    accountDir?: string
    openPane?: boolean
    workspaceStatus?: WorkspaceStatus
    comment?: string
    displayName?: string
    parentWorktree?: string
    verifyCmd?: string
    cleanup?: boolean
    json?: boolean
  }

  const repoRoot = payload.repoRoot || process.cwd()
  switch (payload.sub) {
    case 'agents': {
      const res = await detectInstalledCruxAgents()
      console.log(JSON.stringify(res, null, 2))
      return
    }
    case 'create':
    case 'spawn': {
      const taskId = payload.taskId || payload.displayName
      if (!taskId) {
        throw new Error('usage: crux worktree create <task-id|--name N> [--agent A] [--prompt P] [--status S] [--comment C]')
      }
      const rec = await spawnCruxWorktreeTask({
        repoRoot,
        taskId,
        agent: payload.agent ?? undefined,
        prompt: payload.prompt ?? undefined,
        baseBranch: payload.baseBranch ?? undefined,
        host: payload.host ?? undefined,
        accountDir: payload.accountDir ?? undefined,
        openPane: payload.openPane ?? undefined,
        workspaceStatus: payload.workspaceStatus ?? undefined,
        comment: payload.comment ?? undefined,
        parentWorktree: payload.parentWorktree ?? undefined
      })
      console.log(JSON.stringify(rec, null, 2))
      return
    }
    case 'set': {
      const rec = await setCruxWorktreeMetadata({
        repoRoot,
        taskId: payload.taskId ?? undefined,
        cwd: payload.cwd ?? process.cwd(),
        displayName: payload.displayName ?? undefined,
        workspaceStatus: payload.workspaceStatus ?? undefined,
        comment: payload.comment ?? undefined,
        parentWorktree: payload.parentWorktree === null ? undefined : payload.parentWorktree
      })
      console.log(JSON.stringify(rec, null, 2))
      return
    }
    case 'current': {
      const rec = await resolveCurrentCruxWorktree(repoRoot, payload.cwd ?? process.cwd())
      console.log(JSON.stringify({ current: rec }, null, 2))
      return
    }
    case 'ps':
    case 'ls':
    case 'list':
    case 'status': {
      const rows = await listCruxWorktreeStatus(repoRoot)
      console.log(JSON.stringify(rows, null, 2))
      return
    }
    case 'diff': {
      let tid = payload.taskId
      if (!tid || tid === 'current' || tid === 'active') {
        const cur = await resolveCurrentCruxWorktree(repoRoot, payload.cwd ?? process.cwd())
        tid = cur?.taskId
      }
      if (!tid) {
        throw new Error('usage: crux worktree diff <task-id|current>')
      }
      const diff = await inspectCruxWorktreeDiff(repoRoot, tid, true)
      console.log(JSON.stringify(diff, null, 2))
      return
    }
    case 'merge': {
      let tid = payload.taskId
      if (!tid || tid === 'current' || tid === 'active') {
        const cur = await resolveCurrentCruxWorktree(repoRoot, payload.cwd ?? process.cwd())
        tid = cur?.taskId
      }
      if (!tid) {
        throw new Error('usage: crux worktree merge <task-id|current> [--verify CMD] [--cleanup]')
      }
      const res = await mergeCruxWorktreeTask({
        repoRoot,
        taskId: tid,
        verifyCmd: payload.verifyCmd,
        cleanup: payload.cleanup
      })
      console.log(JSON.stringify(res, null, 2))
      return
    }
    case 'rm':
    case 'remove': {
      if (!payload.taskId) {
        throw new Error('usage: crux worktree rm <task-id> [--cleanup]')
      }
      const res = await removeCruxWorktreeTask({
        repoRoot,
        taskId: payload.taskId,
        deleteBranch: payload.cleanup
      })
      console.log(JSON.stringify(res, null, 2))
      return
    }
    default:
      throw new Error(
        `unknown worktree verb ${JSON.stringify(payload.sub)} — try create, set, current, ps, diff, merge, rm, or agents`
      )
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err))
  process.exit(1)
})
