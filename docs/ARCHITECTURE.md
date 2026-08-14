# LarkNova 架构说明

## 1. 总体架构（M0-M6）

```text
飞书开放平台 / lark-cli
        |
        v
M0 权限与数据边界  doctor / boundary / 白名单 / 外部群策略
        |
        v
M1 数据底座        sync runner -> messages / message_versions
                  normalize -> content_normalized / content_hash
                  sync_runs / DB migrations (v2-v6)
        |
        v
M2 知识层          chunker -> chunks / chunk_messages
                  tokenizer + FTS5 -> BM25
                  稀疏 TF-IDF + RRF -> 混合检索
                  graph -> entities / entity_mentions / edges
        |
        v
M3 AI 摘要         rule/llm summarizer -> summaries / summary_runs
                  budget -> 输入/输出 token 预算
        |
        v
M4 Agent/Harness   AgentHarness -> tools(search) / steps / citations
                  guardrails / llm fallback / agent_runs / agent_traces
                  HTTP API -> /api/agent/*
        |
        v
M5 评测闭环        synthetic seed -> data/synth.db
                  golden cases -> eval runner -> resume_metrics.json
        |
        v
M6 交付能力        scripts / docs / unittest 回归 / 一键复现
```

## 2. 模块与阶段映射

| 阶段 | 模块 | 核心职责 |
| --- | --- | --- |
| M0 | `feishu_agent.doctor` / `boundary` | 权限检查、白名单、外部群过滤、历史越界清理 |
| M1 | `sync/runner.py`、`normalize.py`、`database/` | 全量/增量同步、归一化、审计版本、迁移 |
| M2 | `index/chunker.py`、`tokenizer.py`、`repository.py`、`graph.py` | chunk、FTS5、稀疏向量、RRF、规则图谱 |
| M3 | `summary/rule_summarizer.py`、`llm_summarizer.py`、`repository.py`、`budget.py` | 结构化摘要、增量、预算 |
| M4 | `agent/harness.py`、`tools.py`、`repository.py`、`api/server.py` | Harness、工具注册表、trace、鉴权限流 |
| M5 | `synthetic/seed.py`、`eval/golden.py`、`runner.py`、`metrics.py`、`report.py` | 合成语料、黄金集、评测、指标报告 |
| M6 | `scripts/`、`docs/`、`tests/` | 一键启动、运行手册、架构文档、回归 |

## 3. 数据流

```text
飞书群聊消息
   -> sync（全量/增量、幂等、失败隔离）
   -> messages（事实源，单条全量存储，保留 raw_json）
   -> message_versions（编辑/撤回审计）
   -> normalize（content_normalized / content_hash）
   -> chunks + FTS5（BM25）
   -> chunk_vectors（稀疏 TF-IDF）
   -> entities / edges（规则知识图谱）
   -> summaries（结论 + 依据 + 待办）
   -> AgentHarness（search 工具 + 证据校验）
   -> 回答 / 拒答 / trace
   -> eval runner（黄金集 + 结构化报告）
```

## 4. SQLite 存储分层

事实源与派生层分离，派生数据全部可由事实源重建：

```text
事实源层
  chats / messages / message_versions / sync_state / sync_runs

派生层
  chunks / chunk_messages / chunk_vectors / chunks_fts
  entities / entity_mentions / edges
  summaries / summary_runs
  agent_runs / agent_traces

指标层
  index_runs / summary_runs / sync_runs
  data/reports/resume_metrics.json
```

`messages` 按一条消息一行全量存储是事实源设计：`message_id` 主键保证幂等，
`raw_json` 保留事件原文，`content_normalized` 提供检索用文本，版本表负责审计。

## 5. 检索链路

```text
query -> 中文 bigram + ASCII token 编码
      -> FTS5 BM25 召回
      -> 稀疏 TF-IDF 召回
      -> RRF 融合排序
      -> 返回 chunk + 消息级证据（message_id / chat_id / create_time / sender）
```

图谱作为补充证据源，支持 `graph stats` 与 `graph entity` 查询；
实体覆盖 person/group/department/date/identifier/url/amount 等类型。

## 6. Agent 编排

```text
question
  -> 护栏（长度 / 敏感词 / 预算）
  -> 模式决策（rule / llm / auto）
  -> 工具注册表（search，schema + 错误处理）
  -> 证据校验（引用必须命中真实消息）
  -> 回答 / 无依据拒答
  -> agent_runs + agent_traces 持久化
```

`auto` 在 LLM 不可用或失败时自动降级到 `rule`，错误写入 trace。
API 侧 `/api/agent/*` 支持 Bearer / X-API-Token 与进程内限流。

## 7. API 面

```text
GET  /health
GET  /api/chats
GET  /api/messages
GET  /api/stats
POST /api/sync
GET  /api/metrics
GET  /api/sync-runs
GET  /api/message-versions
GET  /api/search
GET  /api/graph/entities
GET  /api/graph/entity
GET  /api/index/status
POST /api/index/rebuild
POST /api/index/incremental
GET  /api/summaries
GET  /api/summaries/status
POST /api/summaries/rebuild
POST /api/summaries/incremental
POST /api/agent/ask
GET  /api/agent/runs
GET  /api/agent/runs/<id>
GET  /api/agent/stats
```

## 8. 演进选项

- 编排层：`LangGraph` 替换自研状态循环，保留工具注册表协议。
- 工具生态：`FastMCP` 暴露本地工具，服务化后供外部 Agent 调用。
- 向量/图谱：`ChromaDB` / `Milvus` 强化 dense recall，`Neo4j` 承载跨群关系查询。
- 服务化：`FastAPI + Uvicorn` 承接现有 handler，补充 OpenAPI 与后台任务。
- 实时通道：飞书事件订阅替代轮询，配合公网 HTTPS 回调。
