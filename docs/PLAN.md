# LarkNova 实施规划表

## 1. 项目定位

将现有 LarkNova MVP 从“飞书消息同步 + SQLite + HTTP API”升级为**企业内部飞书知识沉淀 Agent**：

- 数据层：稳定、幂等、可控权限地采集飞书群聊历史消息与话题上下文。
- 知识层：富文本归一化、话题切分、混合检索、时间衰减、上下文压缩。
- Agent 层：意图识别、工具调用、RAG 问答、引用溯源、拒答与降级。
- 业务层：面向人事、风控、财务、招采 4 类场景沉淀数据集与评测闭环。

## 2. 现状盘点

**已有基础（可直接复用）**

- lark-cli 封装：`subprocess` 调用、JSON 解析、网络抖动重试、user/bot 双身份参数。
- 数据表：`chats`、`messages`、`sync_state`、`summaries`（M3 已落地）。
- 同步能力：全量/增量同步、消息时间游标、upsert 兼容编辑与撤回、同步互斥锁。
- API：`/health`、`/api/chats`、`/api/messages`、`/api/stats`、`/api/sync`。
- 真实数据：2 个内部群、22 条消息（其中 12 条可索引），含 `text/system` 等类型。
- M1 核心代码：`normalize` 归一化、`message_versions` 审计、`sync_runs` 指标、
  单群失败隔离、DB 迁移（v2/v3，当前已扩展至 v6）与 `normalize --rebuild` 已实现。
- M2 核心代码：chunk、FTS5 BM25、稀疏 TF-IDF + RRF、规则知识图谱、
  重建/增量/一致性/搜索/图谱命令与 API、同步后自动增量索引。
- M3 核心代码：rule 确定性摘要 + LLM 可选模式、增量/一致性/状态 CLI 与 API、
  同步后自动增量摘要，39 项测试通过。
- M4 核心代码：自研标准库 AgentHarness、工具注册表、rule/llm/auto 三模式、
  无依据拒答、LLM 引用校验、敏感词/预算护栏、agent_runs/agent_traces 持久化、
  agent CLI 与 /api/agent/* 鉴权限流，48 项测试通过。
- M5 核心代码：确定性合成语料生成器、黄金测试集、eval runner 与报告，
  `--db` 支持独立临时库隔离；合成库 115 条消息、41 条黄金用例全量通过，
  53 项测试全绿。

**主要缺口**

- 机器人读取消息权限 `im:message:readonly` 未开通，当前按 `LARK_IDENTITY=user` 运行；
  bot 权限窗口已预留，机器人入群后完成复验。
- 本地库存在 2 个历史外部群样本，M0 已提供 `boundary` 审计与显式确认清理命令。
- 富文本已归一化并保留原始 JSON；M2 派生索引、M3 结构化摘要、M4 Agent Harness、
  M5 评测闭环已完成核心链路。
- 生产库消息样本不足（当前 22 条），M5 先用合成语料完成 41/41 评测基线；
  生产数据重建后重跑 `eval run` 并更新 `resume_metrics.json`。
- M6 交付能力已补齐：`.env.example` 模板、`scripts/bootstrap/demo/run_server.ps1`、
  运行手册/架构文档/演示文档与 53 项 unittest 全量回归。
- 剩余窗口：bot 权限补验、真实库重跑评测、badcase 周闭环与消融实验。

## 3. 阶段总览

| 阶段 | 主题 | 核心任务 | 主要交付物 | 验收标准 | 优先级 | 建议周期 |
| --- | --- | --- | --- | --- | --- | --- |
| M0 | 权限与数据边界 | 开通机器人读消息权限；切换 bot 身份；圈定内部测试群；过滤外部群；审计/清理历史越界数据 | 权限清单、测试群配置、同步脚本、boundary 命令 | bot 身份拉取成功；无 `230027`；仅内部群入库；历史外部群可审计清理 | M0 | 0.5-1 天 |
| M1 | 数据管道生产化 | 富文本归一化；消息更新/撤回处理；索引与约束优化；错误隔离；迁移机制 | 消息解析器、清洗规则、同步指标、DB 迁移 | 边界清理后的内部群消息全量重建一致；重复执行幂等；主要消息类型可解析 | M0 | 3-5 天 |
| M2 | 主题组织与索引 | 会话/话题切分；thread 聚合；chunk 生成；关键词 + 稀疏向量索引；增量索引 | 语料切分模块、索引仓库、重建/增量命令 | 全量可重建；增量与源库一致；检索接口可上线 | M0 | 3-5 天 |
| M3 | AI 摘要与上下文 | LLM 时段/话题摘要；结论 + 依据 + 待办结构化输出；增量补充摘要；token 预算控制 | 摘要 Worker、`summaries` 写入、摘要查询 API | 摘要可生成；重复执行幂等；质量抽查通过；成本可控 | M1 | 3-5 天 |
| M4 | Agent 应用层 | 自研标准库 Harness；工具注册表；rule/llm/auto 降级；引用溯源、拒答、敏感词；trace 持久化；API 鉴权限流 | Agent API、工具注册表、trace 回放 | 端到端问答通过；回答可溯源；可拒答；trace 可回放 | M1 | 5-7 天 |
| M5 | 评测与业务闭环 | 人事/风控/财务/招采场景沉淀；黄金测试集；检索与问答评测；Badcase 闭环；参数调优 | 评测脚本、测试集、评测报告 | Recall/首条命中率提升；测试集 >= 30 条；Badcase 闭环率达标 | M1 | 3-5 天 |
| M6 | 部署与最终验收 | Docker/环境变量/权限安全；运行手册；架构文档；全量回归 | 部署包、README、验收报告 | 新环境可一键启动；全部测试通过；业务演示通过 | M2 | 2-3 天 |

M6 状态：已完成（user 身份基线 + 合成评测），bot/真实库复验保留为后续窗口。

## 4. 阶段明细与验收

### M0 权限与数据边界

当前状态：代码完成，等待 bot 实跑；项目以 user 身份基线继续推进。

依赖：

- 飞书开发者后台可操作该应用，或有管理员协助开通权限。
- 确认内部白名单群范围，历史外部群样本需清理或不再参与业务指标。

任务：

1. 开启 `im:message:readonly` 与机器人所需最小权限。
2. 将 `LARK_IDENTITY` 切换为 `bot`，验证机器人可枚举群聊并读取消息。
3. 建立受控内部测试群，写入真实业务样例消息。
4. 增加数据范围过滤：只同步白名单内部群或机器人所在内部群，明确排除外部群。
5. 审计本地库历史外部群/非白名单群，提供显式确认的清理命令。

验收：

- `python -m feishu_agent.main sync --identity bot` 成功，无 `230027`。
- 入库会话集合与白名单一致，外部群不进入 `chats/messages`。
- boundary 审计/清理命令可清除历史越界数据。
- `.env.example` 更新 bot 配置说明与最小权限清单。

### M1 数据管道生产化

任务：

1. 实现消息归一化：`post/interactive/merge_forward/image/file/system` 转统一文本/Markdown，保留原 JSON。
2. 补齐消息更新、撤回、删除的本地一致性处理，形成可审计的变更记录。
3. 增加必要索引、约束和校验，保证 `message_id`、`chat_id + create_time` 检索性能。
4. 拆分同步指标：每次同步新增数、更新数、失败群数、耗时、游标位置，写入日志或监控表。
5. 引入轻量 DB 迁移机制，后续表结构变更可增量执行。
6. 单群失败隔离，失败群不阻塞其余群同步。

验收：

- 对边界清理后的内部白名单消息执行全量重建，消息数一致、无重复；外部群历史样本不计入业务指标。
- 同一数据连续同步两次，增量计数为 0，消息内容不被破坏。
- 主要消息类型（post/text/interactive/system/merge_forward）均有单元测试覆盖。
- 人为制造单群失败时，其余群仍同步成功，`sync_state` 记录错误信息。

M1 当前进度（2026-08-11，user 身份基线）：

- [x] `normalize.py`：post/interactive/merge_forward/image/system 等归一化，保留 `raw_json`。
- [x] `messages` 增加 `content_normalized/content_hash/normalize_version/normalize_error`。
- [x] `message_versions`：created/content_updated/recalled/restored/metadata_updated 审计。
- [x] `sync_runs`：每次同步的计数、耗时、失败群与错误落库；`metrics` 可查询。
- [x] 单群失败隔离，失败群不阻塞其他群；`sync_state` 记录错误。
- [x] DB 迁移 v2/v3，旧消息自动回填归一化字段与 initial 版本（后续 v4/v5/v6 已扩展）。
- [x] 新增 API：`/api/metrics`、`/api/sync-runs`、`/api/message-versions`。
- [ ] bot 权限开通且机器人加入白名单群后，用 `--identity bot` 复验同步。

### M2 主题组织与索引

当前状态：已完成 user 身份基线（2026-08-12），bot 权限开通后复验。

任务：

1. 将消息按 thread、会话窗口、话题边界聚合成“语料单元”。
2. 实现 chunk 策略：按时间窗口、发言轮次、语义段落切分并生成 chunk 记录。
3. 建立关键词索引（SQLite FTS5 BM25）与稀疏 TF-IDF 向量，RRF 融合；
   dense vector / ChromaDB / Milvus 作为可选升级。
4. 支持全量重建索引与增量索引，保证索引与 `messages` 数据一致。
5. 输出检索 API：输入问题与群范围，返回含时间、消息 ID、发送者的候选结果。

验收：

- 测试数据全量重建后，索引覆盖数与消息数对得上。
- 新消息同步后触发增量索引，检索立即可见。
- 检索返回结果带可追溯字段（`message_id/chat_id/create_time/sender`）。
- 索引重建与检索接口通过自动化测试。

M2 当前进度（2026-08-12，user 身份基线）：

- [x] `index/chunker.py`：thread + 时间窗口 + 消息数/字符上限生成 chunk。
- [x] `index/tokenizer.py`：中文 bigram + ASCII token，FTS5 安全编码。
- [x] `index/repository.py`：rebuild/incremental/consistency/search/graph，
  FTS5 BM25 + 稀疏 TF-IDF + RRF，`index_runs.version_cursor` 精确增量。
- [x] `index/graph.py`：person/group/department/date/identifier/url/amount
  规则实体、共现边与 replied_to 边。
- [x] DB 迁移 v4：chunks/chunk_messages/chunk_vectors/entities/entity_mentions/
  edges/chunks_fts/index_runs。
- [x] `sync/runner.py` 同步后自动增量索引，索引失败不影响同步结果。
- [x] 新增 API：`/api/search`、`/api/graph/entities`、`/api/graph/entity`、
  `/api/index/status`、`/api/index/rebuild`、`/api/index/incremental`。
- [x] 真实库验收：rebuild 为 2 群 / 22 消息 / 12 可索引 / 3 chunks；
  consistency=true；中文检索可溯源；graph stats 为 4 实体 / 26 mentions / 17 边。
- [x] M2 阶段 34 项单元测试全绿。
- [ ] bot 权限开通后，用 bot 身份同步并复跑 index consistency/search。

### M3 AI 摘要与上下文

任务：

1. 设计摘要模型：按群 + 时间窗口/话题生成“结论 + 依据 + 待办 + 关键人/日期”。
2. 增量摘要：已有摘要后只对新增消息做补充，避免重复消耗 token。
3. 将结果写入 `summaries`，支持按群、时间范围查询。
4. 增加 token 预算、超时、重试与失败重生成机制。
5. 人工抽查摘要质量，维护低质量 Badcase 清单。

验收：

- 对测试群可生成可读摘要，结构字段完整。
- 同一时间段重复生成结果幂等，不重复追加。
- 摘要 API 返回数据与 `summaries` 表一致。
- 摘要质量抽查通过率 >= [待定：80%]，单次成本在预算内（LLM 实跑质量抽查随 M5 业务闭环补齐）。

当前状态：已完成 user 身份基线（2026-08-12），bot 权限开通后复验。

M3 当前进度（2026-08-12，user 身份基线）：

- [x] `summary/protocol.py`：摘要结构字段与覆盖范围协议。
- [x] `summary/budget.py`：上下文构建、`SUMMARY_MAX_CHARS` 与输入/输出 token 预算。
- [x] `summary/rule_summarizer.py`：确定性规则摘要，
  输出 conclusion/evidence/todo/key_people/key_dates/entities。
- [x] `summary/llm_summarizer.py`：OpenAI 兼容 LLM 摘要，
  未配置端点时报 `SummaryConfigError`（有测试覆盖）。
- [x] `summary/repository.py`：rebuild/incremental/consistency/status/list，
  `summary_runs` 记录每次运行。
- [x] DB 迁移 v5：`summaries`、`summary_runs` 重建；db stats/metrics 增加摘要统计。
- [x] CLI：`summary rebuild/incremental/list/get/consistency/status`；
  API：`/api/summaries`、`/api/summaries/status`、
  `/api/summaries/rebuild`、`/api/summaries/incremental`。
- [x] `sync/runner.py` 同步后自动增量摘要，摘要失败不影响同步结果。
- [x] 真实库验收：rebuild 为 2 群 / 22 消息 / 12 可索引 / 3 chunks，
  生成 2 条摘要；incremental 返回 no_changes；
  consistency=true；status 为 runs=1、summaries=2、token_estimate=491、fresh=true；
  metrics 同步显示。
- [x] M3 阶段累计 39 项单元测试全绿；当前全量 48 项全绿。
- [ ] bot 权限开通后，用 bot 身份同步并复跑 summary consistency/status。

### M4 Agent 应用层

任务：

1. 基于 Python 标准库实现 AgentHarness，保留现有同步命令与 API 兼容，不新增第三方依赖。
2. 编排链路：问题护栏 → 计划/规则决策 → 工具调用（检索）→ 生成 → 引用校验。
3. 将本地能力封装为工具注册表，工具输入输出有 schema 与错误处理，后续可扩展新工具。
4. 回答必须返回引用（消息 ID/群/时间），无依据时拒答。
5. 支持 rule/llm/auto 三模式：LLM 失败或未配置时自动降级到规则链路，落盘错误 trace。
6. 增加鉴权（本地 token/白名单）与限流，防止内部服务裸奔。

验收：

- 端到端问答用例通过：事实类、时间敏感类、无答案类各 >= 5 条。
- 回答引用可追踪到原始消息；无答案场景正确拒答率 >= [待定：95%]。
- 每次问答落盘 run + 完整步骤 trace，可回放输入/输出/工具/耗时/引用。
- 原有 `/api/messages`、`/api/stats`、`/api/sync` 回归通过。

当前状态：已完成 user 身份基线（2026-08-12），bot 权限开通后复验。

M4 当前进度（2026-08-12，user 身份基线）：

- [x] `agent/protocol.py`：question/citation/step/trace 协议，输入输出 JSON 可序列化。
- [x] `agent/tools.py`：工具注册表 + `search` 工具，调用索引检索并返回消息级证据。
- [x] `agent/harness.py`：rule/llm/auto 三模式，Planner 失败自动降级，
  LLM 引用必须命中真实消息，无依据拒答，错误 trace 落盘。
- [x] 护栏：问题/回答长度、证据条数、最大步骤、敏感词拦截。
- [x] `agent/repository.py` + DB 迁移 v6：`agent_runs`、`agent_traces`，stats/metrics 扩展。
- [x] CLI：`agent ask/runs/trace/stats`；API：`/api/agent/ask`、`/api/agent/runs[/<id>]`、`/api/agent/stats`。
- [x] API 鉴权（Bearer / X-API-Token）与进程内限流。
- [x] 真实库验收：rule 问答返回 7 条消息级引用、170 token、35ms；runs/trace/stats 可回放。
- [x] 48 项单元测试全绿。
- [ ] bot 权限开通后，用 bot 身份同步并复跑 agent ask/runs/trace。

### M5 评测与业务闭环

任务：

1. 面向人事、风控、财务、招采分别沉淀高频问题清单。
2. 构建黄金测试集：问题、预期检索结果、预期答案、依据消息 ID。
3. 实现自动化评测：Recall@5、首条命中率、答案准确性、拒答准确率。
4. Badcase 闭环：周抽样、归因、参数调整、回归验证。
5. 做消融实验：chunk 大小、Top-K、相似度阈值、时间衰减权重、是否 Rerank。

验收：

- 黄金测试集 >= 30 条，覆盖 4 个部门。
- 评测脚本可一键运行并生成报告。
- 相比基线，Recall@5 或首条命中率有可量化提升。
- 每周 Badcase 有记录、有归因、有验证结果。

当前状态：已完成 user 身份基线（2026-08-13），真实库重跑待数据补充。

M5 当前进度（2026-08-13，user 身份基线 + 合成语料）：

- [x] `synthetic/seed.py`：确定性生成 7 chats / 115 条消息，覆盖人事/风控/财务/招采场景，
  `--reset-derived` 可重建索引与摘要，全量重建幂等有测试。
- [x] `eval/golden.py`：41 条黄金用例，含 graph/recent/refusal/search/summary 五类及
  `_ref(chat, topic, index)` 引用协议。
- [x] `eval/runner.py` + `eval/metrics.py`：rule 评测一键运行，输出总准确率、引用命中、
  关键词命中、拒答准确率、延迟与 token；报告写入 `data/reports/resume_metrics.json`。
- [x] CLI：`synthetic seed/status`、`eval run/report/samples`，`--db` 全局覆盖临时库。
- [x] 实测：`eval run --mode rule --limit 0` 为 41/41、总准确率 100%、引用命中 90%、
  关键词命中 100%、拒答准确率 100%、mean 45.8ms / p95 76.0ms / max 105ms。
- [x] 53 项单元测试全绿（新增 `tests/test_synthetic.py`、`tests/test_eval.py`）。
- [ ] 真实生产库消息充足后，用 `--db data/agent.db eval run` 重跑并更新指标。
- [ ] badcase 周闭环与消融实验（chunk 大小/Top-K/阈值/Rerank）随真实数据补充。

### M6 部署与最终验收

任务：

1. 整理环境变量、权限配置、LLM 配置与向量库配置模板。
2. 提供 Dockerfile / 启动脚本，支持一次性同步、周期同步、API/Agent 服务三种模式。
3. 编写架构图、使用手册、验收演示脚本。
4. 全量自动化测试 + 手工业务演示。

验收：

- 新环境按文档执行后能完成同步、索引、摘要、问答全链路。
- 全量测试通过，README 与实现一致。
- 完成一次面向业务场景的演示，包含问答、引用、拒答和摘要展示。

M6 当前进度（2026-08-14，user 身份基线 + 合成评测）：

- [x] `.env.example`：身份、白名单、外部群、数据库、摘要预算、LLM、Agent 护栏、
  API Token 与限流模板齐全。
- [x] `scripts/bootstrap.ps1`：创建 `data/` 与 `data/reports/`，`.env` 幂等初始化。
- [x] `scripts/demo.ps1`：合成语料重建 + 41 条黄金用例评测 + 报告落盘一键执行。
- [x] `scripts/run_server.ps1`：HTTP API 启动脚本，支持 `Interval`/`Identity`/
  `SyncOnStart` 参数，鉴权与限流从 `.env` 读取。
- [x] `docs/USER_GUIDE.md`：环境准备、三种运行模式、常用命令、数据恢复、
  报告覆盖注意事项与 FAQ。
- [x] `docs/ARCHITECTURE.md`：M0-M6 架构图、模块映射、数据流、存储分层、
  检索链路、Agent 编排、API 面与演进选项。
- [x] `docs/DEMO.md`：一键/分步演示、最新 41/41 指标、M0-M6 验收记录。
- [x] 全量回归：53 项 unittest 全绿。
- [x] 报告复验：`data/reports/resume_metrics.json` 为 41/41（run_at
  `2026-08-14T10:07:16+08:00`），累计 9847 token。
- [ ] bot 权限开通后补验；真实库消息充足后重跑 eval 并更新报告。

## 6. 横切事项

- 安全：最小权限、内部群白名单、密钥不入库、日志脱敏、鉴权与限流。
- 数据一致性：同步幂等、索引可重建、摘要幂等、失败可重试。
- 成本：摘要增量计算、检索结果限制、Rerank 按需启用、token 用量统计。
- 可维护：统一日志、同步指标、错误码、迁移脚本、README。

## 7. 风险与应对

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 机器人 `im:message:readonly` 无法开通 | M0 阻塞，只能继续用 user 身份 | 以白名单 + 最小群数控制风险，同时保留机器人方案 |
| 历史外部群误入库 | 信息泄漏 | M0 提供 `boundary` 审计，同步自动跳过，显式确认后可清理 |
| 富文本/文件类消息解析困难 | 语料质量差、召回低 | 归一化失败降级为原始 JSON，并纳入 Badcase 治理 |
| LLM 成本与响应波动 | 摘要/问答不稳定 | 增量摘要、缓存、超时重试、双模式降级 |
| lark-cli 依赖本机 Node | 部署受限 | 抽象 FeishuClient 接口，生产环境可替换为官方 SDK |
| 大群历史数据量增长 | 同步与索引变慢 | 分页限流、增量同步、批量索引、失败隔离 |

## 8. 执行顺序建议

```text
M0 ──> M1 ──> M2 ──> M3 ──> M4 ──> M5 ──> M6
       │                      │
       └── M2/M3 可并行推进    └── M5 与 M4 复用评测接口
```

M0 必须最先完成；M1 完成后再进入 M2；M3 与 M2 可并行（当前已随 M2 完成 user 基线）；
M5 可在 M4 跑通后立即开始，避免评测滞后。
