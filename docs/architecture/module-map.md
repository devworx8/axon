# Axon Module Map

## Critical hotspots

| File | Current size | Direction |
| --- | ---: | --- |
| `server.py` | 9702 lines | Extract to `axon_api/` |
| `brain.py` | 4772 lines | Extract to `axon_core/` |
| `db.py` | facade | Extraction completed into `axon_data/` |
| `ui/index.html` | 5731 lines | Shell + partials |
| `ui/manual.html` | 1046 lines | Shell + chapter partials |
| `ui/js/dashboard.js` | 3561 lines | Split by dashboard concerns |
| `ui/js/chat.js` | 2654 lines | Split by chat/composer/agent/terminal concerns |
| `ui/js/voice.js` | 913 lines | Split by voice input/output/provider concerns |

Additional oversized tracked files are ratcheted in
`scripts/guardrails/hotspot_budgets.json` and may not grow while they are being
split.

## Target package layout

### Backend API

```text
axon_api/
  app.py
  middleware.py
  ui_renderer.py
  routes/
  services/
```

### Core orchestration

```text
axon_core/
  chat.py
  streaming.py
  agent.py
  intent.py
  providers.py
  prompts.py
  safety.py
  tools/
```

### Data layer

```text
axon_data/
  core.py
  projects.py
  prompts.py
  tasks.py
  activity.py
  chat.py
  settings.py
  resources.py
  memory.py
  research_packs.py
  terminal.py
  webhooks.py
```

### Frontend

```text
ui/
  index.html
  manual.html
  partials/
  js/
```

## Ownership rule

Each module must answer a simple question:

“Why does this file exist?”

If the answer needs “and”, the module is probably too broad.
