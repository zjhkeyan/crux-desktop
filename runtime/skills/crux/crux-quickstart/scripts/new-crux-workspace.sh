#!/usr/bin/env bash
# Scaffold a Crux workspace for optimizing code you already have.
#
# Does the mechanical boilerplate so only the thinking step (writing the
# grader) is left to you: gitignores .crux_workspace/, runs `crux discovery init`
# inside it, and (optionally) copies the code to optimize into seed/.
#
# Usage:
#   new-crux-workspace.sh [task-name] [path/to/code-to-optimize]
#
#   task-name              defaults to "optimize"
#   path/to/code           optional; copied to <task>/seed/solution.py
#
# Run it from the root of the project whose code you want to optimize.
set -euo pipefail

TASK="${1:-optimize}"
SRC="${2:-}"

command -v crux >/dev/null 2>&1 || {
  echo "error: 'crux' is not on PATH. Install it first (see the crux-quickstart skill)." >&2
  exit 1
}

# Resolve the source path to absolute BEFORE we cd, so a relative arg still works.
SRC_ABS=""
if [ -n "$SRC" ]; then
  if [ -f "$SRC" ]; then
    SRC_ABS="$(cd "$(dirname "$SRC")" && pwd)/$(basename "$SRC")"
  else
    echo "warning: source file '$SRC' not found — leaving the generated seed in place." >&2
  fi
fi

# Keep Crux scaffolding out of the user's source tree: gitignore the workspace.
if git rev-parse --show-toplevel >/dev/null 2>&1; then
  ROOT="$(git rev-parse --show-toplevel)"
  if ! grep -qxF ".crux_workspace/" "$ROOT/.gitignore" 2>/dev/null; then
    echo ".crux_workspace/" >> "$ROOT/.gitignore"
    echo "Added .crux_workspace/ to $ROOT/.gitignore"
  fi
fi

mkdir -p .crux_workspace
cd .crux_workspace
crux discovery init "$TASK"

if [ -n "$SRC_ABS" ]; then
  cp "$SRC_ABS" "$TASK/seed/solution.py"
  echo "Copied $SRC_ABS -> .crux_workspace/$TASK/seed/solution.py"
fi

cat <<EOF

Workspace ready: .crux_workspace/$TASK

Next (the parts only you can decide):
  1. cd .crux_workspace/$TASK
  2. Edit task.yaml -> task.description: the goal + the program-file contract
     (what solution.py must define/print, and what "better" means).
  3. Write the grader (grader/src/.../grader.py) to score your metric.
     -> see the 'creating-a-crux-task' skill for grader patterns + the TaskGrader API.
  4. crux discovery validate .          # confirm the grader scores the seed (the key checkpoint)
  5. crux discovery start -c task.yaml  # launch agents; results stay under .crux_workspace/
EOF
