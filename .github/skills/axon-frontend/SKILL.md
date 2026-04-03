---
name: axon-frontend
description: "**DOMAIN SKILL** — Axon frontend UI development. USE FOR: modifying Alpine.js components, editing ui/js/ modules, changing ui/partials/ HTML, updating ui/styles.css, working with ui/index.html shell, adding slash commands, modifying chat/dashboard/voice/terminal/settings UI. USE WHEN: touching any .js or .html file in ~/.devbrain/ui/, changing the SPA layout, adding UI features, modifying CSS variables or theme. DO NOT USE FOR: Python backend changes (use axon-backend), agent loop changes (use axon-agent), database changes (use axon-data)."
argument-hint: "Describe the UI change or feature"
---

# Axon Frontend Development

You are working on Axon's single-page application — an Alpine.js + Tailwind CSS
SPA served from `~/.devbrain/ui/`. All JavaScript is vanilla ES6 loaded from
individual module files. There is no build pipeline — all dependencies are CDN-loaded.

## Architecture Overview

```
ui/
  index.html           — SPA shell (6089L, FROZEN — extract to partials)
  manual.html          — Standalone documentation (1046L, FROZEN)
  styles.css           — Glassmorphism dark theme, CSS variables, animations
  partials/
    dashboard.html     — Dashboard view markup
    settings.html      — Settings panel markup
    voice.html         — Voice command center
    sidebar.html       — Navigation sidebar
    modals.html        — Modal dialogs
  js/
    chat.js            — Chat module (999L, FROZEN — split by concern)
    dashboard.js       — Dashboard module (2287L, FROZEN — split by concern)
    voice.js           — Voice module (913L, FROZEN — split by concern)
    terminal.js        — Terminal enhancement (sessions, history, xterm)
    settings.js        — Settings management
    helpers.js         — Shared utilities (formatting, API, DOM)
    notifications.js   — Sticky notification system
    vault.js           — Vault UI operations
    projects.js        — Workspace management
    models.js          — Model selection UI
    resources.js       — Resource bank UI
    files.js           — File management UI
    codeblocks.js      — Code block rendering
    enhanced-code-blocks.js — Enhanced code block features
    mobile.js          — Mobile/touch adaptations
    tasks.js           — Mission/task UI
    auth.js            — Authentication UI
```

## CDN Dependencies (loaded in index.html)

- **Tailwind CSS** — utility-first CSS framework
- **Alpine.js** — reactive UI framework (`x-data`, `x-show`, `x-bind`, etc.)
- **marked.js** — Markdown rendering
- **highlight.js** — Syntax highlighting
- **xterm.js** — Terminal emulator
- **Azure Speech SDK** — Voice recognition/synthesis

## Module Pattern (MUST follow)

Every JS module uses a mixin pattern that Alpine.js merges into the global store:

```javascript
/* ═══════════════════════════════════════════════════
   Axon — Module Name
   ═══════════════════════════════════════════════════ */

function axonModuleNameMixin() {
  return {
    // Reactive data properties
    someProperty: false,
    items: [],

    // Methods
    async loadItems() {
      try {
        this.items = await this.api('GET', '/api/items');
      } catch(e) {
        this.showToast('Failed to load items');
      }
    },

    async saveItem(item) {
      try {
        await this.api('POST', '/api/items', item);
        this.showToast('Item saved');
      } catch(e) {
        this.showToast('Save failed: ' + e.message);
      }
    },
  };
}

// REQUIRED: expose on window for Alpine.js to merge
window.axonModuleNameMixin = axonModuleNameMixin;
```

## Core Helpers (from helpers.js / index.html)

Always available on `this` inside any mixin:

| Helper | Usage |
|--------|-------|
| `this.api(method, path, body?)` | Fetch wrapper, returns parsed JSON |
| `this.showToast(message)` | Show notification toast |
| `this.formatTime(isoString)` | Human-readable time |
| `this.scrollChat(force?)` | Scroll chat to bottom |
| `this.activeTab` | Current tab: `'chat'`, `'projects'`, `'missions'`, etc. |
| `this.chatProjectId` | Currently selected workspace ID |
| `this.chatProject` | Currently selected workspace object |

## Partial System

HTML partials are included in `index.html` via server-side rendering:

```html
<!-- In index.html -->
<div x-show="activeTab === 'dashboard'">
  @include('partials/dashboard.html')
</div>
```

New partials must be added to `ui/partials/` and included in `index.html`.

## CSS Variables (from styles.css)

```css
/* Key variables for theming */
--bg-primary    — main background
--bg-secondary  — card/panel background
--text-primary  — main text color
--text-muted    — secondary text
--accent        — primary accent (sky-400)
--accent-hover  — accent hover state
```

## Slash Commands (in chat.js)

```javascript
const _SLASH_COMMANDS = [
  { cmd: '/help',    desc: 'Show available commands' },
  { cmd: '/clear',   desc: 'Clear chat history' },
  { cmd: '/agent',   desc: 'Switch to agent mode' },
  // ... more commands
];
```

To add a new slash command: add to `_SLASH_COMMANDS` array and handle in the
command dispatch logic below it.

## File Size Rules (from AGENTS.md)

### Frozen files (must NOT grow):
- `ui/index.html` — extract markup to `ui/partials/`
- `ui/js/dashboard.js` — split by dashboard concern
- `ui/js/chat.js` — split by chat/composer/agent concern
- `ui/js/voice.js` — split by voice input/output concern

### New modules:
- Soft limit: 350 lines
- Hard limit: 500 lines
- Must have a single bounded context

## Verification

```bash
# Syntax check touched JS files
node --check ui/js/<file>.js

# Verify no unclosed braces/brackets (quick sanity)
node -e "require('fs').readFileSync('ui/js/<file>.js','utf8')" && echo "OK"
```

## Anti-Patterns to Avoid

- Adding inline `<script>` blocks to HTML files (use `ui/js/`)
- Adding new features to frozen JS files (create a new module or split first)
- Growing `index.html` with new markup (create a partial)
- Using jQuery or other frameworks (Alpine.js + vanilla JS only)
- Direct DOM manipulation when Alpine.js reactivity suffices
- Hardcoding API URLs (use `this.api()` which handles the base path)
- Adding global variables without the mixin pattern
