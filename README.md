# Axon

Axon is a local-first AI operator console for code work. It runs on your machine, monitors workspaces, keeps missions and playbooks in context, and routes local model work through Ollama by default.

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

## Safety notes

- Runtime state lives locally in `~/.devbrain/devbrain.db` and is intentionally gitignored.
- Logs, pid files, and bundled binaries are excluded from version control in this repo.
- On display-attached 6GB NVIDIA GPUs, Axon guards large Ollama models to avoid desktop blanking or compositor resets.

## Self-edit verification

Axon can modify its own codebase when a real tool-backed file write succeeds. This section was added as a tiny local proof edit and should appear in `git diff` immediately after the change.
