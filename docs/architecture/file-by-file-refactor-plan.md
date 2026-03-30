# Axon File-by-File Refactor Plan

This is the executable split plan for the current Axon monoliths. It turns the
high-level roadmap into bounded slices with compatibility rules for each file.

## 1. `server.py`

Current role:

- FastAPI app bootstrap
- auth/session middleware
- route definitions for every feature
- UI shell serving
- PWA/static serving
- mobile/tunnel helpers
- terminal/browser/voice/system actions

Target end state:

- bootstrap + middleware registration + router registration only

Extraction order:

1. `axon_api/ui_renderer.py`
   - `/`
   - `/manual`
   - `/manual.html`
   - `/manifest.json`
   - `/styles.css`
   - `/js/{filename}`
   - `/icons/{filename}`
   - `/sw.js`
2. `axon_api/routes/auth.py`
3. `axon_api/routes/projects.py`
4. `axon_api/routes/prompts.py`
5. `axon_api/routes/tasks.py`
6. `axon_api/routes/resources.py`
7. `axon_api/routes/memory.py`
8. `axon_api/routes/chat.py`
9. `axon_api/routes/agent.py`
10. `axon_api/routes/runtime.py`
11. `axon_api/routes/mobile.py`
12. `axon_api/routes/browser.py`
13. `axon_api/routes/terminal.py`
14. `axon_api/routes/voice.py`
15. `axon_api/routes/system.py`

Compatibility rule:

- URL paths and payload shapes must stay stable until an explicit API versioning
  pass is approved.

## 2. `brain.py`

Current role:

- chat orchestration
- streaming
- agent loop
- tool registration and dispatch
- intent selection
- provider routing
- prompt policy

Target end state:

- compatibility facade over `axon_core/`

Extraction order:

1. `axon_core/providers.py`
2. `axon_core/prompts.py`
3. `axon_core/intent.py`
4. `axon_core/streaming.py`
5. `axon_core/chat.py`
6. `axon_core/tools/files.py`
7. `axon_core/tools/git.py`
8. `axon_core/tools/shell.py`
9. `axon_core/tools/browser.py`
10. `axon_core/tools/missions.py`
11. `axon_core/agent.py`
   - extracted and now wired through compatibility wrappers in `brain.py`
   - legacy in-file agent block removed from `brain.py`
12. `axon_core/safety.py`

Compatibility rule:

- exported functions from `brain.py` must continue to work for the current
  callers in `server.py`, `browser_bridge.py`, and feature modules.

## 3. `db.py`

Current state:

- extraction completed into `axon_data/`
- `db.py` is now a compatibility facade

Next step:

- keep repository additions out of `db.py`
- add tests per `axon_data` submodule

## 4. `ui/index.html`

Current role:

- full shell
- every tab
- every modal
- large inline Alpine state

Target end state:

- app shell only
- partial placeholders
- thin Alpine bootstrap

Extraction order:

1. `ui/partials/app-sidebar.html`
2. `ui/partials/app-topbar.html`
3. `ui/partials/app-dashboard.html`
4. `ui/partials/app-console.html`
5. `ui/partials/app-workspaces.html`
6. `ui/partials/app-missions.html`
7. `ui/partials/app-playbooks.html`
8. `ui/partials/app-timeline.html`
9. `ui/partials/app-resources.html`
10. `ui/partials/app-memory.html`
11. `ui/partials/app-vault.html`
12. `ui/partials/app-settings.html`
13. `ui/partials/app-mobile-nav.html`
14. `ui/partials/app-modals.html`
15. `ui/js/app-core.js`

Compatibility rule:

- keep `devbrain()` available as the Alpine root alias until the final cleanup
  pass.

## 5. `ui/manual.html`

Target end state:

- shell + chapter partials

Extraction order:

1. `ui/partials/manual-intro.html`
2. `ui/partials/manual-dashboard.html`
3. `ui/partials/manual-console.html`
4. `ui/partials/manual-memory.html`
5. `ui/partials/manual-mobile.html`
6. `ui/partials/manual-security.html`
7. `ui/partials/manual-power-user.html`

## 6. `ui/js/dashboard.js`

Target split:

- `ui/js/dashboard-stats.js`
- `ui/js/dashboard-live.js`
- `ui/js/dashboard-workspaces.js`
- `ui/js/dashboard-actions.js`

## 7. `ui/js/chat.js`

Target split:

- `ui/js/chat-stream.js`
- `ui/js/chat-composer.js`
- `ui/js/chat-agent.js`
- `ui/js/chat-terminal.js`
- `ui/js/chat-browser-actions.js`

## 8. `ui/js/voice.js`

Target split:

- `ui/js/voice-input.js`
- `ui/js/voice-output.js`
- `ui/js/voice-azure.js`

## 9. Secondary oversize files

These are not monolith-tier, but they should not grow further:

- `document_engine.py`
- `memory_engine.py`
- `pptx_engine.py`
- `resource_bank.py`
- `vault.py`
- `ui/js/resources.js`

Rule:

- if any of these are touched for feature work and exceed the soft limit, split
  them in the same change.
