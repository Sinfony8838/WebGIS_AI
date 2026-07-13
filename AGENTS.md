# WebGIS-AI multi-agent collaboration rules

These rules apply to Claude Code, OpenCode, Codex, and any other coding agent
working in this repository.

## Source of truth

- `main` is the protected integration branch. A tested commit on `main`, not an
  agent chat or an old feature branch, is the project source of truth.
- Never replace a dirty local workspace with a remote branch. If local files are
  believed to be newer, create a recovery branch and commit a reviewed snapshot
  before fetching changes into the worktree.
- Runtime state, generated output, dependency folders, caches, local environment
  files, and private presentation assets are not source code. Follow `.gitignore`.

## One agent, one branch, one worktree

- Every task uses a dedicated worktree. Do not run two write-capable agents in
  the same directory.
- Use these branch prefixes:
  - Codex: `codex/<task>`
  - Claude Code: `claude/<task>`
  - OpenCode: `opencode/<task>`
- Create new worktrees from the latest `origin/main`. A typical setup is:

  ```powershell
  git fetch origin
  git worktree add ..\WebGIS-AI-worktrees\codex-<task> -b codex/<task> origin/main
  ```

- An agent may edit only the worktree assigned to it. The primary checkout is
  reserved for the integration owner.

## Task ownership

- Each task must declare its objective, allowed paths, forbidden paths,
  acceptance checks, and dependencies before editing begins.
- Assign overlapping files to one agent only. Shared integration files such as
  `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`,
  `backend/app/main.py`, `backend/app/models.py`, and `backend/app/runtime.py`
  belong to the integration owner unless explicitly delegated.
- Parallel agents should work on separable modules, tests, data preparation, or
  read-only review. If two tasks need the same file, run them sequentially.
- Agents must not reformat, rename, or clean up files outside their declared
  scope.

## Git safety

- Before editing, record `git status -sb`, the current branch, and the starting
  commit. Stop if the assigned worktree is unexpectedly dirty.
- Do not use `git reset --hard`, `git clean`, forced checkout, or blanket stash
  operations to handle another agent's changes.
- Stage explicit paths. Review `git diff --cached --stat` and
  `git diff --cached` before every commit.
- Never commit `.env` files, credentials, `node_modules`, build output,
  `*.tsbuildinfo`, backend runtime state, or download caches.
- Never force-push `main`. Force-pushing an agent branch requires explicit human
  approval and `--force-with-lease`.

## Validation gates

Run the checks relevant to the changed area before requesting integration:

```powershell
# Backend (the system default Python may be too old)
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest backend/tests -q

# Frontend
Push-Location frontend
& "C:\Program Files\nodejs\npm.cmd" test
& "C:\Program Files\nodejs\npm.cmd" run build
Pop-Location

# Coding agent service
Push-Location agent\agent
& "C:\Program Files\nodejs\npm.cmd" test
& "C:\Program Files\nodejs\npm.cmd" run build
Pop-Location

git diff --check
```

For classroom and map changes, also verify that the 3D globe/UI shell,
lesson-session-report flow, TOP20 visual query, and startup health endpoints are
still present. Do not restore `generic_classroom_pack` or stale runtime state.

## Pull requests and integration

- Open one PR per task and list the exact scope, changed paths, validation
  results, and any known limitations.
- The integration owner reviews PRs in dependency order and is the only actor
  who resolves conflicts in shared integration files.
- Update a task branch with current `main` inside its own worktree, rerun its
  checks, and then merge. Do not resolve a conflict by choosing an entire side
  without comparing the intended behavior.
- Prefer squash merge for independent task branches. Preserve merge commits only
  when branch ancestry is intentionally meaningful.
- Delete or archive superseded branches only after the replacement is on
  `main`, tests pass, and a recovery tag or commit SHA has been recorded.

## Handoff format

Every agent handoff must include:

1. branch and starting commit;
2. files changed;
3. behavior added or preserved;
4. commands run and exact results;
5. unresolved risks or required follow-up;
6. explicit confirmation that no unrelated workspace changes were modified.
