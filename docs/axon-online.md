# Axon Online Workflow

Axon works best on web and app projects when you treat the workspace, live page,
and Auto sandbox as one loop:

1. Track the repo as a workspace.
2. Start the live page for that workspace.
3. Let Axon inspect or change the sandboxed copy.
4. Apply changes back only after review.

This guide documents the current behavior in the app and codebase.

## What "Axon Online" means here

For this repo, "Axon Online" is the browser-first workflow for a tracked
workspace. It covers:

- frontend repo setup inside Axon
- live preview startup and browser attachment
- Auto mode in an isolated git worktree
- guarded apply and discard flows
- the most common failure cases

For phone access, HTTPS tunnel, and PWA setup, use the in-app manual section on
stable domain and mobile access.

## Quick path

1. Start Axon with `axon` or the legacy `devbrain` launcher.
2. Open `http://localhost:7734`.
3. Add the project folder as a workspace.
4. Select that workspace before using Console Auto mode.
5. Start the workspace Live Page from the Dashboard or right rail.
6. Run the task in Auto mode if you want Axon to work inside an isolated
   sandbox.
7. Review the Auto report, then choose `Apply` or `Discard`.

## Workspace setup

Axon keeps the repo itself as the source workspace. Auto mode never edits that
source tree directly.

Recommended setup:

- Add the repo folder through the workspace picker.
- Confirm the workspace path is the actual git checkout you want to protect.
- Make sure the workspace is inside a git repository before relying on Auto
  mode. Auto creates an isolated git worktree and will fail on a plain folder.
- Set `Settings -> Autonomy + Memory -> Autonomy profile` to
  `Workspace auto` unless you need stricter manual gating.
- Leave `Prefer workspace memory, snapshots, and cache before external tools`
  enabled if you want local evidence prioritized before live fetches.

The Console will reject Auto mode until a workspace is selected.

## Live Page behavior

The Live Page feature starts a workspace-scoped preview and attaches Axon's
browser surface to it when possible.

Axon currently detects these frontend cases automatically:

| Workspace shape | Launch behavior |
| --- | --- |
| `expo` dependency present | Runs Expo web preview on localhost |
| `next` dependency present | Runs the project script with explicit hostname and port |
| `vite` or `astro` dependency present | Runs the project script with explicit host and port |
| `nuxt` dependency present | Runs the project script with explicit host and port |
| Any other repo with `dev` or `start` script | Runs that script with the matching package manager |
| No package script but `index.html` exists | Falls back to `python3 -m http.server` |

Other important details:

- Preview sessions are workspace-scoped, not global.
- Axon binds previews to `127.0.0.1` and chooses a free local port.
- Workspace previews usually start around port `3000+`.
- Auto-session previews use a separate `3400+` range.
- If a preview already exists and is healthy, Axon reuses it instead of starting
  another one.
- Preview metadata and logs live under `~/.devbrain/live_preview_sessions`.

## Auto mode safety model

Auto mode creates an isolated git worktree sandbox under
`~/.devbrain/auto_sessions`.

That sandbox is the place where Axon:

- reads and edits files
- runs local verification commands
- builds the Auto report
- starts sandbox-specific previews when needed
- stores session metadata in the sandbox directory for later review

The source workspace stays untouched until you choose `Apply`.

Current contract:

- Auto mode is workspace-scoped.
- Routine edits and local shell work inside the sandbox are pre-approved.
- The agent is expected to keep working until it finishes or reaches a real
  blocker.
- The final handoff is recorded in the Auto session report.

## Apply and Discard

When you choose `Apply`, Axon copies the changed files from the sandbox back
into the source workspace.

Apply is intentionally conservative:

- it refuses to run if the source workspace has overlapping uncommitted changes
- it copies changed files back into the source workspace
- it removes deleted files and preserves renames

When you choose `Discard`, Axon removes the worktree sandbox and deletes the
session branch.

Recommended review loop:

1. Read the Auto session report first.
2. Check the preview or changed files.
3. Apply only when the source workspace is clean for those paths.
4. Discard stale or wrong-direction sessions instead of trying to salvage them.

## Browser control and approvals

Starting the Live Page gives Axon a controlled browser surface for inspection,
verification, and queued browser actions.

Guardrails that matter:

- read-only inspect actions can be auto-approved in inspect mode
- mutating browser actions stay guarded
- sensitive local machine actions still follow Axon's broader safety rules

This keeps the browser useful for verification without turning it into an
unbounded automation channel.

## Troubleshooting

### "Select a workspace before starting Auto mode."

Pick a workspace first. Auto mode is not available as a global console action.

### "Preview started, but no URL is available yet."

The dev server is still booting, or the command started without producing a
ready local URL yet. Refresh the workspace preview after a few seconds, then
check the matching log under `~/.devbrain/live_preview_sessions`.

### "No package.json dev/start script or static index.html found for this workspace."

Axon could not infer how to run the project. Add a `dev` or `start` script, or
make sure the repo has a directly servable `index.html`.

### Apply fails because of overlapping changes

The source workspace has local edits in the same paths that the sandbox wants to
apply. Commit, stash, or manually reconcile the source changes first, then
apply again.

### Expo preview behaves differently in Auto mode

Axon has special handling for Expo worktrees. It keeps the sandbox preview
rooted in the sandbox while linking dependency state back to the source repo so
Expo Router resolves correctly.

## Related docs

- [README](../README.md)
- [Engineering Guardrails](engineering/guardrails.md)
- [Module Map](architecture/module-map.md)
- [Manual](../ui/manual.html)
