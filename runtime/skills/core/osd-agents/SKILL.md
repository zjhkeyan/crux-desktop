---
name: osd-agents
description: Use ONLY for inspecting or messaging an existing workbench session/terminal (`[OSD session]`, `[OSD terminal]`, `[OSD screen]`) or changing app settings (`crux settings`). For multi-agent scientific discovery, parallel experiments, creating Git worktrees, adding projects, or updating progress checkpoints, ALWAYS use `multi-agent-orchestration` (and the `worktree` / `crux_discovery` tools) instead.
---

# The workbench: sessions, Screens, terminals

`crux` is on your PATH and already connected to this workbench. Three things
are reachable through it:

- **Sessions**: conversations, each with its own folder.
- **Screens**: the tabs at the top of the app. Each one is split into panes,
  and each pane shows a session or a terminal.
- **Terminals**: shells, some running Claude Code or Codex.

`crux screen ls` shows all of it at once, with the ids every other command
takes. `crux session find <words>` finds a conversation by what was said in it.

## Screens

```
crux screen new --sessions 6 --name "Six"          # a new Screen, split evenly among 6 new conversations
crux screen new --sessions 2 --discovery work/run   # 2 agent panes + live Crux Discovery Evolution Tree & Leaderboard tile
crux screen new ses_a ses_b --terminals 1          # existing conversations and a terminal, side by side
crux screen new --terminals 3 --run claude          # three terminals, each starting Claude Code
crux screen add g12 --new                           # one more pane: a new conversation (or a SESSION_ID, or --terminal)
crux screen add g12 --discovery work/run            # attach the live Crux Discovery Evolution Tree & Leaderboard tile
crux screen add --here --new                        # a new conversation right of you, on the Screen you are on
crux screen show g12                                # bring it up in the user's window
crux screen close g12                               # close it; the conversations are kept
```

New conversations and terminals start in your folder unless you pass
`--directory DIR` or `--project NAME`. A new Screen appears in the user's
tab bar right away, and the user stays on the Screen they were looking at.

## Reading and messaging

| You have | Read it | Send to it |
|---|---|---|
| a session `ses_…` | `crux session show <id> --last 2` (its last two turns) | `crux session send <id> "<message>" --wait` |
| a terminal running Claude Code or Codex | `crux term read <id>` (`--turns 3` for more) | `crux term send <id> "<message>" --wait` |
| a terminal running a plain shell | `crux term read <id>` (last 40 lines; `--lines N`) | `crux term send <id> "<command>"`. **This runs the command.** |

`crux session wait <id>` waits for a turn someone else started and prints its
answer; `crux session status <id>` says whether one is running.

Read before you write: a message lands in the middle of someone else's work.
`crux term read` on an agent says whether it is `working`; a message sent then
waits in its queue and does not interrupt.

The other agent does not know who you are. Write every message so it stands
alone: who you are, what you need, what to send back.

> I'm the agent in the "Fold proteins" session. I need the path of the
> AlphaFold outputs you produced today. Reply with the path only.

When you tell the user about another conversation's files, give full paths.
Their folder is not yours.

## Limits

- One conversation may send five messages in ten minutes. Past that, `crux`
  says to stop and ask the user. Tell the user what you have done and ask
  whether to go on.
- A plain shell runs what you send as the user, outside your workspace and
  your approvals. Send it only commands the user asked for.
- `terminals are off` means "Allow terminals" is off: ask for
  `remote.terminal=on` (see Settings below).

## Settings

`crux settings` lists the app's settings and their values. You change none
yourself: you ask the user, once, for everything the task needs, with why.

```
crux settings set remote.terminal=on --reason "To run Claude Code in a terminal next to me."
```

The user sees each change in a dialog and approves all, some or none; the
command waits and prints what was applied. A decline is final: do not ask
again unless the user brings it up. Ask only for what the task needs. API
keys and sign-ins are not settings here; the user enters them in Settings.
