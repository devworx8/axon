# Axon

Axon is a local-first AI operator console for code work. It runs on your machine, monitors workspaces, keeps missions and playbooks in context, and routes local model work through Ollama by default.

## Axon Online docs

If you are using Axon on a web or app workspace, start with:

- [`docs/axon-online.md`](docs/axon-online.md) for the tracked-workspace, Live Page, and Auto sandbox workflow
- [`ui/manual.html`](ui/manual.html) for mobile access, stable domain, PWA, and operator concepts

## Product language

- `Axon` — app name
- `Local AI Operator` — descriptor
- `Console` — chat and operator flow
- `Workspaces` — scanned projects
- `Missions` — tasks and suggested work
- `Playbooks` — reusable prompts/instructions
- `Timeline` — activity and morning brief
- `Secure Vault` — local secret storage

## Runtime architecture

Axon is local-first:

- `runtime_manager.py` builds the operator/runtime snapshot
- `model_router.py` maps roles like code, general, reasoning, embeddings, and vision
- `agent_registry.py` exposes planner/coder/scanner/reviewer/repair roles
- `permissions_guard.py` tracks approved local/network/system/vault scopes
- `mission_manager.py` prepares structured mission suggestions
- `gpu_guard.py` adds display-GPU safety checks for local Ollama models

Preferred local runtime:

- Ollama
- Code: `qwen2.5-coder`
- General: `qwen3` or smaller installed fallback
- Reasoning: `deepseek-r1` with hardware-aware safety fallback on low-VRAM display GPUs
- Embeddings: `nomic-embed-text`

Optional cloud adapters are scaffolded but disabled by default:

- OpenAI GPTs
- Gemini Gems
- Generic API models

## Quick start

Axon still keeps the legacy `devbrain` command for compatibility, but `axon` is the preferred launcher after install.

```bash
bash ~/.devbrain/install.sh
source ~/.zshrc
axon
```

Open `http://localhost:7734` and finish setup in `Settings -> Runtime`.

Typical web-workspace flow:

1. Add the repo as a workspace.
2. Select that workspace in Console.
3. Start the Live Page so Axon has a browser surface for preview and verification.
4. Use Auto mode when you want changes made in an isolated git worktree first.
5. Apply the Auto session only after review.

## Engineering guardrails

Axon is under active anti-monolith refactor. Start here before major changes:

- [`AGENTS.md`](AGENTS.md)
- [`docs/engineering/guardrails.md`](docs/engineering/guardrails.md)
- [`docs/architecture/refactor-roadmap.md`](docs/architecture/refactor-roadmap.md)
- [`docs/architecture/module-map.md`](docs/architecture/module-map.md)

Guardrail scripts:

```bash
python3 scripts/guardrails/check_file_sizes.py
python3 scripts/guardrails/check_boundaries.py
```

## Safety notes

- Runtime state lives locally in `~/.devbrain/devbrain.db` and is intentionally gitignored.
- Logs, pid files, and bundled binaries are excluded from version control in this repo.
- On display-attached 6GB NVIDIA GPUs, Axon guards large Ollama models to avoid desktop blanking or compositor resets.
