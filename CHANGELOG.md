# Changelog

## v2.0.0 (2026-05-26)

### Breaking changes
- Tool renamed: `semantic_search` → `semantic_session_search`
- Plugin now installs to `~/.hermes/plugins/` (user directory) instead of `hermes-agent/tools/` — upgrade-safe

### Changes
- `semantic_index.py`: added `--json` flag for structured output, fixed `score` → `distance` field name in CLI output, added `[limit]` argument to `search` command
- Plugin `__init__.py`: rewritten to use subprocess isolation (consistent with tool file approach), updated tool name and description
- `plugin.yaml`: bumped to v2.0.0

## v1.0.0 (2026-05-25)

Initial implementation:
- BGE-M3 embeddings via local Ollama
- sqlite-vec vector store
- Three-tier indexing: lazy-load, session-end hook, nightly cron
- 304 sessions indexed, 11,431 chunks
