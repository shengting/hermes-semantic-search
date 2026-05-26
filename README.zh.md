# hermes-semantic-search

[English](README.md) | 中文

[Hermes Agent](https://github.com/NousResearch/hermes-agent) 的 BGE-M3 语义搜索插件，为历史会话添加向量相似度搜索能力。

Hermes 内置的 `session_search` 使用 SQLite FTS5 关键词匹配。这个插件在此基础上增加了一条语义检索路径——用稠密向量嵌入来查找，不再依赖精确关键词。

## 能做什么

注册一个 `semantic_session_search` 工具，它会：
- 用 BGE-M3 对你的查询生成向量嵌入（通过本地 Ollama，不走任何云服务）
- 在本地 sqlite-vec 数据库中进行向量相似度检索
- 返回按相关性排序的历史会话片段（距离越小越相关）
- 每次搜索前自动对新会话做增量索引（懒加载）

### 和 `session_search` 怎么选

| | `session_search` | `semantic_session_search` |
|---|---|---|
| 原理 | FTS5 关键词匹配 | BGE-M3 向量相似度 |
| 能找到 | 精确/前缀匹配 | 概念相关、同义词、换了说法的表达 |
| 速度 | 极快 | ~0.2–0.5 秒 |
| 适合场景 | 知道确切词汇 | 按想法/概念搜索 |

## 环境要求

- 已安装 [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- 本地运行 [Ollama](https://ollama.com)，并拉取 `bge-m3` 模型：
  ```bash
  ollama pull bge-m3
  ```
- Python 3.11+（Hermes venv 自带）

## 安装

```bash
git clone https://github.com/shengting/hermes-semantic-search
cd hermes-semantic-search
bash install.sh
```

安装脚本会自动完成：
1. 在 Hermes venv 中安装 `sqlite-vec`
2. 将脚本复制到 `~/.hermes/scripts/`
3. 将插件安装到 `~/.hermes/plugins/semantic-search/`
4. 在 `~/.hermes/config.yaml` 中启用插件
5. 在 `~/.hermes/cli-config.yaml` 中注册 `on_session_finalize` Hook

然后运行初始索引：
```bash
~/.hermes/hermes-agent/venv/bin/python ~/.hermes/scripts/semantic_index.py index
```

重启 Hermes 即可使用。

## 可选：定时自动索引

让 Hermes 设置一个每小时的定时任务，保持索引持续更新：

> "帮我设置一个每小时运行 `~/.hermes/scripts/semantic_index_cron.sh` 的 cron 任务"

## 实现原理

### 架构

```
semantic_session_search 工具
  (~/.hermes/plugins/semantic-search/__init__.py)
        ↓ subprocess
~/.hermes/scripts/semantic_index.py   ← 核心库
        ↓
~/.hermes/semantic_index.db           ← sqlite-vec 向量库
        ↑
Ollama BGE-M3 (127.0.0.1:11434) → 1024 维嵌入向量
```

### 三层索引触发机制

| 层级 | 触发时机 | 覆盖范围 |
|------|----------|----------|
| 懒加载 | 工具被调用时 | 当前会话 + 所有变更文件 |
| Hook | `on_session_finalize` 触发 | 刚结束的会话 |
| Cron | 每小时（可选） | 兜底全量扫描 |

三层均复用同一个 `index_session()` 函数，基于文件 mtime 去重，开启 WAL 模式——幂等、并发安全。

### 会话分块

`~/.hermes/sessions/` 中的每个会话文件（`.jsonl`）会被切分成 400 字符的重叠块（80 字符重叠）。每个块经 BGE-M3 生成嵌入向量，以 float32 格式存入 sqlite-vec 的 `vec0` 虚拟表。

## 文件结构

```
hermes-semantic-search/
├── install.sh                        ← 一键安装脚本
├── plugin/
│   ├── plugin.yaml                   ← Hermes 插件清单
│   └── __init__.py                   ← register(ctx) → 注册工具
└── scripts/
    ├── semantic_index.py             ← 核心：嵌入、索引、搜索
    ├── session_finalize_hook.py      ← on_session_finalize Hook
    └── semantic_index_cron.sh        ← Cron 包装脚本
```

安装后，文件存放在：

```
~/.hermes/plugins/semantic-search/   ← 插件（升级安全）
~/.hermes/scripts/semantic_index*    ← 脚本
~/.hermes/semantic_index.db          ← 向量数据库
```

## 升级安全

所有文件安装在 `~/.hermes/`（用户目录），不在 `hermes-agent/` 内部。运行 `hermes update` 不会覆盖插件文件。

## License

MIT
