# Running the Agent Loop

The agent loop automates the implement → review → resolve → PR cycle for issues in the `issues/` directory. It uses `agent-loop.ps1` from the skills repo and requires `pwsh` (PowerShell for macOS).

## Prerequisites

1. **PowerShell**: `brew install --cask powershell`
2. **gh CLI**: `brew install gh` and `gh auth login`
3. **Agent prompts**: run `/setup-agent-loop` once in Claude Code to generate configured prompts in `!workfiles/agent-prompts/`

## Run the full loop

```bash
pwsh ~/Documents/repos/skills/tools/agent-loop.ps1 \
  -Phase issue-loop \
  -TargetRepo "/Users/rasmus/Documents/repos/ayla-usage-dashboard" \
  -PromptDir "!workfiles/agent-prompts" \
  -WorkAgent claude \
  -PermissionMode bypassPermissions \
  -AutoBranch
```

This will:
1. Find all issues in `issues/` with `Status: ready-for-agent`
2. Process them in filename order on a single task branch
3. Commit each issue as it completes
4. Push and create a PR
5. Run an internal Claude review
6. Resolve any review findings

## Run a single phase

```bash
# Implement only (no review)
pwsh ~/Documents/repos/skills/tools/agent-loop.ps1 \
  -Phase implement \
  -IssuePath "issues/01-median-prepare-mode.md" \
  -TargetRepo "/Users/rasmus/Documents/repos/ayla-usage-dashboard" \
  -PromptDir "!workfiles/agent-prompts" \
  -WorkAgent claude \
  -AutoBranch

# Review the current branch
pwsh ~/Documents/repos/skills/tools/agent-loop.ps1 \
  -Phase review \
  -TargetRepo "/Users/rasmus/Documents/repos/ayla-usage-dashboard" \
  -PromptDir "!workfiles/agent-prompts"

# Resolve review findings
pwsh ~/Documents/repos/skills/tools/agent-loop.ps1 \
  -Phase resolve \
  -TargetRepo "/Users/rasmus/Documents/repos/ayla-usage-dashboard" \
  -PromptDir "!workfiles/agent-prompts" \
  -WorkAgent claude
```

## Issue file format

Issues live in `issues/` as markdown files named `NN-slug.md`. They are processed in alphabetical order. The agent loop picks up files that contain:

```
Status: ready-for-agent
```

When an issue is completed the loop updates the status to `done`. If an issue depends on another, put the dependent issue later in the filename order (e.g. `05-` after `04-`).

## First-time setup

Run `/setup-agent-loop` in Claude Code. It reads `CLAUDE.md` and `CONTEXT.md` and generates configured prompt files in `!workfiles/agent-prompts/`. You only need to do this once per machine.
