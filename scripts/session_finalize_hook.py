#!/usr/bin/env python3
"""
on_session_finalize hook：session 结束时触发增量索引
注册方式：在 ~/.hermes/cli-config.yaml 的 hooks 块里添加此脚本

stdin JSON 格式：{"hook_event_name": "on_session_finalize", "session_id": "...", ...}
"""
import json
import os
import sys
from pathlib import Path

_scripts_dir = str(Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")) / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

def main():
    try:
        payload = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    session_id = payload.get("session_id") or payload.get("extra", {}).get("session_id")
    if not session_id:
        sys.exit(0)

    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    session_file = hermes_home / "sessions" / f"{session_id}.jsonl"
    if not session_file.exists():
        sys.exit(0)

    try:
        from semantic_index import get_db, index_session
        conn = get_db()
        n = index_session(conn, session_file)
        conn.close()
        # 静默成功，不输出任何内容（hook 要求 stdout 为 JSON 或空）
    except Exception as e:
        # 不阻断 session finalize 流程
        pass

    sys.exit(0)

if __name__ == "__main__":
    main()
