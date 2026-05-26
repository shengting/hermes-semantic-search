"""
semantic-search plugin for Hermes Agent
Registers the `semantic_session_search` tool — BGE-M3 vector search over session history.

Depends on:
  - ~/.hermes/scripts/semantic_index.py  (core indexing + search logic)
  - sqlite-vec installed in Hermes venv: pip install sqlite-vec
  - bge-m3 running in local Ollama (127.0.0.1:11434)
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_SCRIPT = _HERMES_HOME / "scripts" / "semantic_index.py"
_VENV_PYTHON = Path(__file__).resolve().parents[3] / "hermes-agent" / "venv" / "bin" / "python"

_SCHEMA = {
    "name": "semantic_session_search",
    "description": (
        "Search past sessions using BGE-M3 semantic vector similarity. "
        "Complements session_search (keyword/FTS5) — use this when concept-level "
        "recall is needed: synonyms, paraphrases, topic clusters, or when keyword "
        "search returns nothing.\n\n"
        "WHEN TO USE:\n"
        "- Keyword search returned no results but the topic should exist in history\n"
        "- Query is conceptual ('how did we handle auth', 'deployment issues we had')\n"
        "- Looking for related discussions, not exact phrase matches\n"
        "- Cross-lingual recall (Chinese query → English session content)\n\n"
        "Returns top matching session chunks with distance scores (lower = more similar). "
        "Use session_search for full LLM-summarized context after finding the session_id."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language query. Semantic search — no special syntax needed. Can be in any language.",
            },
            "limit": {
                "type": "integer",
                "description": "Number of results to return (default: 5, max: 20).",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}


def _check_available() -> bool:
    return _SCRIPT.exists() and _VENV_PYTHON.exists()


def _handle(args: dict, **kwargs) -> str:
    query = args.get("query", "").strip()
    if not query:
        return json.dumps({"error": "query is required"}, ensure_ascii=False)

    limit = min(int(args.get("limit", 5)), 20)

    # Fire-and-forget incremental index (indexes new/changed sessions since last run)
    try:
        subprocess.Popen(
            [str(_VENV_PYTHON), str(_SCRIPT), "index", "--incremental"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass

    # Run search with JSON output
    try:
        result = subprocess.run(
            [str(_VENV_PYTHON), str(_SCRIPT), "search", query, str(limit), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "search timed out (>30s)"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    if result.returncode != 0:
        return json.dumps(
            {"error": result.stderr.strip() or "search subprocess failed"},
            ensure_ascii=False,
        )

    output = result.stdout.strip()
    if not output:
        return json.dumps({"results": [], "count": 0}, ensure_ascii=False)

    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return json.dumps({"error": "failed to parse search output", "raw": output[:500]}, ensure_ascii=False)

    results = data.get("results", [])
    formatted = [
        {
            "rank": i,
            "session_id": r.get("session_id", ""),
            "timestamp": r.get("ts", ""),
            "role": r.get("role", ""),
            "distance": round(r.get("distance", 0), 4),
            "snippet": r.get("text", "")[:500],
        }
        for i, r in enumerate(results, 1)
    ]

    return json.dumps(
        {"success": True, "query": query, "count": len(formatted), "results": formatted},
        ensure_ascii=False,
        indent=2,
    )


def register(ctx) -> None:
    """Called once by the Hermes plugin loader."""
    ctx.register_tool(
        name="semantic_session_search",
        toolset="session_search",
        schema=_SCHEMA,
        handler=_handle,
        check_fn=_check_available,
        emoji="🧠",
    )
