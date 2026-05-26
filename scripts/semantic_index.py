#!/usr/bin/env python3
"""
Hermes 语义搜索索引核心
- BGE-M3 via Ollama 生成 1024 维向量
- sqlite-vec 存储向量索引
- 三路触发：搜索时懒加载（当前会话实时）、session 结束 hook、cron 兜底

用法：
  python3 semantic_index.py search "query text"   # 搜索
  python3 semantic_index.py index                 # 全量/增量索引
  python3 semantic_index.py stats                 # 查看统计
"""

from __future__ import annotations
import json
import os
import sqlite3
import struct
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
SESSIONS_DIR = HERMES_HOME / "sessions"
DB_PATH = HERMES_HOME / "semantic_index.db"
OLLAMA_URL = "http://127.0.0.1:11434/api/embeddings"
EMBED_MODEL = "bge-m3"
EMBED_DIM = 1024
CHUNK_SIZE = 400       # 字符数，每个 chunk 的大小
CHUNK_OVERLAP = 80     # 相邻 chunk 重叠字符数
TOP_K = 5              # 默认返回条数


# ── 向量序列化 ──────────────────────────────────────────────────────────────

def encode_vec(vec: list[float]) -> bytes:
    import sqlite_vec
    return sqlite_vec.serialize_float32(vec)

def decode_vec(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


# ── 数据库 ──────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    import sqlite_vec
    conn = sqlite3.connect(str(DB_PATH))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn

def _ensure_schema(conn: sqlite3.Connection):
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            chunk_idx   INTEGER NOT NULL,
            role        TEXT,
            ts          TEXT,
            text        TEXT NOT NULL,
            UNIQUE(session_id, chunk_idx)
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_session ON chunks(session_id);

        CREATE TABLE IF NOT EXISTS index_state (
            session_id   TEXT PRIMARY KEY,
            indexed_at   REAL,
            chunk_count  INTEGER
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
            embedding float[{EMBED_DIM}]
        );
    """)
    conn.commit()


# ── Ollama embedding ────────────────────────────────────────────────────────

def embed(text: str) -> list[float]:
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data["embedding"]


# ── Session 解析 ────────────────────────────────────────────────────────────

def parse_session(path: Path) -> list[dict]:
    """读取 .jsonl session 文件，提取 user/assistant 消息。"""
    messages = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                role = obj.get("role", "")
                if role not in ("user", "assistant"):
                    continue
                content = obj.get("content", "")
                if isinstance(content, list):
                    # 多模态 content blocks
                    texts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(block.get("text", ""))
                    content = " ".join(texts)
                if not content or not content.strip():
                    continue
                messages.append({
                    "role": role,
                    "ts": obj.get("timestamp", ""),
                    "text": content.strip(),
                })
    except Exception:
        pass
    return messages


def chunk_messages(messages: list[dict]) -> list[dict]:
    """把消息列表切成固定大小 chunk，保留 role/ts 元信息。"""
    chunks = []
    for msg in messages:
        text = f"[{msg['role']}] {msg['text']}"
        # 短消息直接作为一个 chunk
        if len(text) <= CHUNK_SIZE:
            chunks.append({"text": text, "role": msg["role"], "ts": msg["ts"]})
            continue
        # 长消息滑窗切分
        start = 0
        while start < len(text):
            end = start + CHUNK_SIZE
            chunks.append({
                "text": text[start:end],
                "role": msg["role"],
                "ts": msg["ts"],
            })
            start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ── 索引 ────────────────────────────────────────────────────────────────────

def index_session(conn: sqlite3.Connection, session_file: Path, force: bool = False) -> int:
    """索引单个 session，返回新增 chunk 数量。"""
    session_id = session_file.stem
    file_mtime = session_file.stat().st_mtime

    # 检查是否需要重新索引
    if not force:
        row = conn.execute(
            "SELECT indexed_at FROM index_state WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row and row[0] >= file_mtime:
            return 0  # 文件未变化，跳过

    messages = parse_session(session_file)
    if not messages:
        return 0

    chunks = chunk_messages(messages)
    new_count = 0

    for idx, chunk in enumerate(chunks):
        # 检查 chunk 是否已存在
        existing = conn.execute(
            "SELECT id FROM chunks WHERE session_id=? AND chunk_idx=?",
            (session_id, idx)
        ).fetchone()
        if existing:
            continue

        # 生成向量
        try:
            vec = embed(chunk["text"])
        except Exception as e:
            print(f"  embed error chunk {idx}: {e}", file=sys.stderr)
            continue

        # 插入 chunk 文本
        cur = conn.execute(
            "INSERT OR IGNORE INTO chunks(session_id, chunk_idx, role, ts, text) VALUES(?,?,?,?,?)",
            (session_id, idx, chunk["role"], chunk["ts"], chunk["text"])
        )
        chunk_row_id = cur.lastrowid
        if not chunk_row_id:
            # chunk 已存在，查出其 id
            row = conn.execute(
                "SELECT id FROM chunks WHERE session_id=? AND chunk_idx=?",
                (session_id, idx)
            ).fetchone()
            if not row:
                continue
            chunk_row_id = row[0]

        # 检查向量是否已存在（避免 UNIQUE 冲突）
        already = conn.execute(
            "SELECT rowid FROM vec_chunks WHERE rowid = ?", (chunk_row_id,)
        ).fetchone()
        if already:
            continue

        # 插入向量（rowid 与 chunks.id 对应）
        conn.execute(
            "INSERT INTO vec_chunks(rowid, embedding) VALUES(?, ?)",
            (chunk_row_id, encode_vec(vec))
        )
        new_count += 1

    if new_count > 0 or True:
        conn.execute(
            "INSERT OR REPLACE INTO index_state(session_id, indexed_at, chunk_count) VALUES(?,?,?)",
            (session_id, file_mtime, len(chunks))
        )
        conn.commit()

    return new_count


def index_all(verbose: bool = False) -> dict:
    """增量索引所有 session 文件。"""
    conn = get_db()
    session_files = sorted(SESSIONS_DIR.glob("*.jsonl"))
    total_new = 0
    processed = 0

    for sf in session_files:
        n = index_session(conn, sf)
        if n > 0:
            total_new += n
            processed += 1
            if verbose:
                print(f"  indexed {sf.name}: +{n} chunks")

    conn.close()
    return {"files": len(session_files), "updated": processed, "new_chunks": total_new}


def index_incremental(verbose: bool = False) -> dict:
    """只索引有变化（mtime 比 indexed_at 新）的 session 文件。"""
    return index_all(verbose=verbose)  # index_session 内部已做 mtime 比较


# ── 搜索 ────────────────────────────────────────────────────────────────────

def search(query: str, top_k: int = TOP_K) -> list[dict]:
    """语义搜索，先做懒加载增量索引，再做向量检索。"""
    # 懒加载：索引所有有变化的 session（含当前 session 新消息）
    index_incremental()

    conn = get_db()
    try:
        query_vec = embed(query)
        rows = conn.execute(
            """
            SELECT
                c.session_id,
                c.role,
                c.ts,
                c.text,
                v.distance
            FROM vec_chunks v
            JOIN chunks c ON c.id = v.rowid
            WHERE v.embedding MATCH ?
              AND k = ?
            ORDER BY v.distance
            """,
            (encode_vec(query_vec), top_k * 4)  # oversample then trim
        ).fetchall()[:top_k]
    finally:
        conn.close()

    results = []
    for row in rows:
        results.append({
            "session_id": row[0],
            "role": row[1],
            "ts": row[2],
            "text": row[3],
            "distance": round(float(row[4]), 4),  # lower = more similar
        })
    return results


# ── 统计 ────────────────────────────────────────────────────────────────────

def stats() -> dict:
    conn = get_db()
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    session_count = conn.execute("SELECT COUNT(*) FROM index_state").fetchone()[0]
    vec_count = conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
    conn.close()
    return {
        "indexed_sessions": session_count,
        "total_sessions": len(list(SESSIONS_DIR.glob("*.jsonl"))),
        "chunks": chunk_count,
        "vectors": vec_count,
        "db_path": str(DB_PATH),
    }


# ── CLI 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "search":
        # Parse args: search <query> [limit] [--json]
        args_rest = sys.argv[2:]
        json_mode = "--json" in args_rest
        args_rest = [a for a in args_rest if a != "--json"]
        # Last arg may be an integer limit
        limit = TOP_K
        if args_rest and args_rest[-1].isdigit():
            limit = int(args_rest[-1])
            args_rest = args_rest[:-1]
        query = " ".join(args_rest)
        if not query:
            print("usage: semantic_index.py search <query> [limit] [--json]")
            sys.exit(1)
        t0 = time.time()
        results = search(query, top_k=limit)
        elapsed = time.time() - t0
        if json_mode:
            print(json.dumps({"results": results, "elapsed": round(elapsed, 3)}, ensure_ascii=False))
        else:
            print(f"Searching: {query!r}")
            print(f"Found {len(results)} results in {elapsed:.2f}s\n")
            for i, r in enumerate(results, 1):
                print(f"[{i}] distance={r['distance']} session={r['session_id']} ts={r['ts']}")
                print(f"    {r['text'][:200]}")
                print()

    elif cmd == "index":
        verbose = "--verbose" in sys.argv or "-v" in sys.argv
        print("Running incremental index...")
        t0 = time.time()
        result = index_all(verbose=verbose)
        elapsed = time.time() - t0
        print(f"Done in {elapsed:.1f}s: {result}")

    elif cmd == "stats":
        s = stats()
        for k, v in s.items():
            print(f"  {k}: {v}")

    else:
        print(__doc__)
