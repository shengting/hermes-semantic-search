# hermes-semantic-search

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin that adds **BGE-M3 semantic search** over your session history.

Hermes's built-in `session_search` uses SQLite FTS5 (keyword matching). This plugin adds a second search path using dense vector embeddings — so you can find past conversations by concept, not just exact words.

## What it does

Registers a `semantic_session_search` tool that:
- Embeds your query with BGE-M3 (via local Ollama, no cloud calls)
- Searches 1024-dim vectors stored in a local sqlite-vec database
- Returns ranked session chunks (lower distance = more relevant)
- Automatically indexes new sessions before each search (lazy-load)

### When to use it vs `session_search`

| | `session_search` | `semantic_session_search` |
|---|---|---|
| Method | FTS5 keyword | BGE-M3 vector similarity |
| Finds | Exact/prefix matches | Conceptual matches, synonyms, paraphrases |
| Speed | Instant | ~0.2–0.5s |
| Use when | You know the exact terms | You're searching by idea |

## Requirements

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed
- [Ollama](https://ollama.com) running locally with `bge-m3` pulled:
  ```bash
  ollama pull bge-m3
  ```
- Python 3.11+ (comes with Hermes venv)

## Installation

```bash
git clone https://github.com/yayu/hermes-semantic-search
cd hermes-semantic-search
bash install.sh
```

The installer:
1. Installs `sqlite-vec` into your Hermes venv
2. Copies scripts to `~/.hermes/scripts/`
3. Installs the plugin to `~/.hermes/plugins/semantic-search/`
4. Enables it in `~/.hermes/config.yaml`
5. Registers a `on_session_finalize` hook in `~/.hermes/cli-config.yaml`

Then run the initial index:
```bash
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/scripts/semantic_index.py index
```

And restart Hermes.

## Optional: hourly cron

To keep the index up-to-date automatically, ask Hermes to set up an hourly cron:

> "Set up an hourly cron job that runs `~/.hermes/scripts/semantic_index_cron.sh`"

## How it works

### Architecture

```
semantic_session_search tool
  (~/.hermes/plugins/semantic-search/__init__.py)
        ↓ subprocess
~/.hermes/scripts/semantic_index.py   ← core library
        ↓
~/.hermes/semantic_index.db           ← sqlite-vec vector store
        ↑
Ollama BGE-M3 (127.0.0.1:11434) → 1024-dim embeddings
```

### Three-tier indexing

| Tier | Trigger | What it covers |
|------|---------|----------------|
| Lazy-load | Tool called | Current session + any changed files |
| Hook | `on_session_finalize` | Session just ended |
| Cron | Hourly (optional) | Full sweep / any gaps |

All tiers use the same `index_session()` function with mtime-based dedup and WAL mode — idempotent and concurrent-safe.

### Session chunking

Each session (`.jsonl` file in `~/.hermes/sessions/`) is split into 400-char overlapping chunks (80-char overlap). Each chunk gets a BGE-M3 embedding stored as a float32 vector in sqlite-vec's `vec0` virtual table.

## File structure

```
hermes-semantic-search/
├── install.sh                        ← one-shot installer
├── plugin/
│   ├── plugin.yaml                   ← Hermes plugin manifest
│   └── __init__.py                   ← register(ctx) → registers tool
└── scripts/
    ├── semantic_index.py             ← core: embed, index, search
    ├── session_finalize_hook.py      ← on_session_finalize hook
    └── semantic_index_cron.sh        ← cron wrapper
```

After install, files live at:

```
~/.hermes/plugins/semantic-search/   ← plugin (upgrade-safe)
~/.hermes/scripts/semantic_index*    ← scripts
~/.hermes/semantic_index.db          ← vector database
```

## Upgrade safety

All files install to `~/.hermes/` (user directory), not inside `hermes-agent/`. Running `hermes update` will not overwrite them.

## License

MIT
