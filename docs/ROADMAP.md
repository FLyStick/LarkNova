# LarkNova 全链路实施规划 V2

> 目标：在现有飞书历史消息 Agent MVP 基础上，迭代为企业 Agent 全链路：
> 开放平台接入 → 数据底座 → 知识图谱 → Agent/Harness 编排 → 可信评测 → 业务闭环。
> 本规划同时用于沉淀简历中的技术细节与可复现指标。
>
> 当前进度（2026-08-14）：M0 权限与数据边界代码完成，等待 bot 实跑；
> M1 数据管道生产化已完成 user 身份基线；M2 主题组织与索引已完成 user 基线；
> M3 AI 摘要与上下文已完成 user 基线，真实库验收为
> 2 群 / 22 条消息 / 12 条可索引 / 3 个 chunk / 4 实体 / 26 mentions / 17 边 /
> 2 条结构化摘要 / token 估算 491；
> M4 Agent + Harness 已完成 user 基线（rule 问答、trace 回放、鉴权限流）；
> M5 评测闭环已完成 user 基线：合成语料 7 chats / 115 messages、
> 黄金测试集 41 条，rule 评测 41/41（100%）；
> M6 交付已完成：scripts 启动脚本、运行手册/架构文档/演示文档、
> 53 项单元测试通过；bot 权限开通后补验，真实库重建后重跑评测。

## 一、规划原则

1. 每个阶段必须先完成验收，再进入下一阶段；验收不复现，不算完成。
2. 优先复用现有 `feishu_agent` 消息同步、SQLite 存储与 HTTP API，不推倒重来。
3. 知识图谱与检索先做轻量可运行版本（SQLite FTS5 + 稀疏 TF-IDF + 规则图谱），ChromaDB/NetworkX/Neo4j 作为可选升级。
4. 所有指标必须有对应命令或脚本可复现，最终写入 `resume_metrics.json`。

## 二、技术选型

| 模块 | 现状 | 目标方案 |
| --- | --- | --- |
| 服务框架 | Python 标准库 HTTP Server | FastAPI + Uvicorn（M4 可选迁移，当前保持标准库无第三方依赖） |
| 消息接入 | lark-cli 子进程封装 | lark-cli + 飞书事件订阅双通道 |
| 存储 | SQLite 事实源 + 版本/指标表 | SQLite + FTS5 + 稀疏向量表（已落地）；ChromaDB/Milvus 可选升级 |
| 图谱 | 无 | SQLite entities/edges + 规则抽取（已落地）；NetworkX/Neo4j 可选升级 |
| 检索 | LIKE 关键词 | BM25 + 稀疏 TF-IDF + RRF（已落地）；Query 改写 + Rerank 可选 |
| Agent 编排 | 无 | 标准库自研 Harness（Planner + 工具注册表 + 校验器）（M4 已落地）；LangGraph 可选 |
| Agent 工具 | 无 | 自研函数工具注册表 + OpenAI 兼容函数调用（M4 已落地）；FastMCP 可选 |
| 模型 | 无 | LLM / Embedding 均采用可配置 API（OpenAI 兼容端点） |
| 评测 | 无 | 自研 eval runner + 黄金测试集 + 结构化报告（M5 已落地：golden + rule runner） |
| 测试 | unittest（24 项） | unittest（53 项）；黄金测试集 + eval runner（M5 已落地）；故障注入可选 |

## 三、分阶段实施与验收

| 里程碑 | 周期 | 主题 | 核心任务 | 交付物 | 验收标准 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| M0 | 0.5-1 天 | 权限与数据边界 | 基线盘点；bot 最小权限；内部群白名单；外部群过滤；doctor 体检；本地边界审计/清理 | `.env.example`、doctor、边界测试 | bot 同步无 `230027`；外部群不入库；doctor/unittest 通过 | 代码完成/等待 bot 实测 |
| M1 | 3-5 天 | 数据管道生产化 | 富文本归一化；编辑/撤回一致性；同步指标；单群失败隔离；DB 迁移 | 消息解析器、`message_versions`、迁移工具、stats 扩展 | user 基线重建一致且幂等；主要消息类型有测试；bot 权限开通后复验 | 已完成（user 基线） |
| M2 | 3-5 天 | 主题组织与索引 | thread/时间窗口切分；chunk 生成；FTS5 + 稀疏向量；知识图谱 entities/edges；增量索引 | chunks/entities/edges、检索 API | 索引可重建、可溯源、与源库一致；增量只重建变更群；测试全绿 | 已完成（user 基线） |
| M3 | 3-5 天 | AI 摘要与上下文 | 结论 + 依据 + 待办结构化摘要；增量补充摘要；token 预算 | summaries worker、摘要 API | 摘要幂等；质量抽查 ≥ 85%；成本可控 | 已完成（user 基线） |
| M4 | 5-7 天 | Agent + Harness | 标准库自研 Harness；工具注册表；rule/llm/auto 降级、敏感词、引用校验；trace 持久化；API 鉴权限流 | `/api/agent/ask`、`agent_runs/agent_traces`、trace 回放 | 端到端成功率 ≥ 90%；P95 ≤ 3s；trace 可回放 | 已完成（user 基线） |
| M5 | 3-5 天 | 评测闭环与业务场景 | 41 条黄金测试集；eval runner；确定性合成语料；badcase 迭代；人事/风控/财务/招采场景 | 评测脚本与报告 | 黄金集 ≥ 30 条；rule 全量 41/41、准确率 100%；真实库重建后重跑 | 已完成（合成语料基线） |
| M6 | 2-3 天 | 交付与简历固化 | `.env` 模板、启动脚本、README/docs；`resume_metrics.json`；简历措辞校准 | 完整文档、Demo、测试套件 | 新环境一键跑通；所有指标可复现 | 已完成 |

## 四、里程碑

| 里程碑 | 内容 | 完成标志 |
| --- | --- | --- |
| M0 | 权限与数据边界 | 无 `230027`、外部群不入库、基线测试通过 |
| M1 | 数据底座完整 | 内部白名单消息可重建、幂等、主要消息类型有测试 |
| M2 | 图谱与检索可用 | 索引可重建、检索可溯源、增量与源库一致（user 基线已完成；Recall 指标 M5 用黄金集补测） |
| M3 | AI 摘要可用 | 摘要幂等、质量抽查通过、成本可控（user 基线已完成） |
| M4 | Agent 全链路可用 | 成功率 ≥ 90%、P95 ≤ 3s、trace 可回放（user 基线已完成，真实库可回放） |
| M5 | 评测闭环成立 | 合成语料 115 条、黄金集 41 条、rule 全量 41/41（badcase 周闭环待真实数据） |
| M6 | 交付物完整 | 新环境跑通、简历指标可溯源；已交付 scripts/docs/全量回归，bot 补验与真实库重跑保留窗口 |

## 五、M2/M3/M4/M5 当前验收（2026-08-13，user 身份基线，含合成语料）

```text
index rebuild:      2 chats / 22 messages / 12 indexed / 3 chunks
                    4 entities / 26 mentions / 17 edges
index consistency:  consistent=true，索引覆盖与可索引源消息一致
index incremental:  rebuild 后返回 no_changes，version_cursor 精确增量
search "测试":      total=1，返回 chunk + message_id + create_time + sender
graph stats:        4 entities / 26 mentions / 17 edges（person/group 两类）
summary rebuild:    run_id=1，chats_checked=2，chats_summarized=2，
                    messages_covered=12，chunks_covered=3，summaries=2，errors=[]
summary incremental: rebuild 后返回 no_changes，增量幂等
summary consistency: consistent=true，摘要覆盖与索引消息一致
summary status:     runs_total=1，summaries=2，token_estimate=491，fresh=true

agent ask:          mode=rule，status=ok，7 条消息级引用，170 token，35ms
agent runs:         count=1，run 持久化于 agent_runs
agent trace:        1 条 tool(search) 步骤，输入/输出/耗时/错误可回放
agent stats:        runs_total=1，citations=7，latency avg=35ms
agent API:          /api/agent/ask、/api/agent/runs、/api/agent/stats 通过，
                    Bearer/X-API-Token 鉴权与限流有测试

synthetic seed:    7 chats / 115 messages / 71 chunks / 62 entities / 352 edges
summary:           6 summaries / 115 messages covered / 71 chunks covered
eval run:          41/41 黄金用例通过，mode=rule
                   accuracy=100.00%，refusal=100.00%，citation=90.00%，keyword=100.00%
                   latency mean 45.8ms / p95 76.0ms / max 105ms
                   token total 9847 / avg 240.2
eval report:       data/reports/resume_metrics.json 已生成
```

M6 交付摘要（2026-08-14）：

```text
scripts/bootstrap.ps1       data 目录与 .env 幂等初始化
scripts/demo.ps1            合成语料 + 41 条黄金评测 + 报告落盘
scripts/run_server.ps1      HTTP API 启动（db/port/interval/identity/sync-on-start）
docs/USER_GUIDE.md          环境准备、三种模式、常用命令、FAQ
docs/ARCHITECTURE.md        M0-M6 架构、数据流、检索/Agent 编排
docs/DEMO.md                演示步骤、41/41 指标、M0-M6 验收记录
unittest                    53 项全绿
resume_metrics.json         41/41，run_at=2026-08-14T10:07:16+08:00
```

小结：M2/M3/M4/M5/M6 核心链路可重建、可校验、可检索、可追溯；
rule 摘要为确定性验收基线，LLM 模式已预留 OpenAI 兼容端点；
rule 问答与 trace 为 M4 确定性验收基线，LLM 规划失败自动降级；
M5 已用合成语料补齐黄金集与 rule 评测基线（41/41），真实生产库重建后重跑；
M6 一键脚本与文档已补齐，`eval run` 必须显式带 `--db data/synth.db` 以保护固定报告；
`Recall@10`、badcase 周闭环与消融实验待真实业务数据补充。

## 六、风险与前置条件

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 飞书 bot 权限审批慢 | M0/M1 阻塞 | 先以 user 身份联调，权限开通后切 bot 验收 |
| 机器人无法入群/读消息 | bot 实跑延后 | 保留 bot 权限窗口；M1 验收拆分为 user 基线自动化验收 + bot 复验 |
| 事件订阅需要公网 HTTPS 回调 | 实时性实现受阻 | 备选方案：缩短轮询周期至 30s；或使用内网穿透临时验证 |
| LLM / Embedding API Key 与预算未定 | M3-M5 阻塞 | 接口未通前用规则/BM25 先行开发，P2 前确定可配置端点 |
| 依赖安装受网络限制 | 所有阶段 | 先验证可安装包清单，失败则评估离线 wheel 或降级组件 |
| 企业数据敏感 | 合规风险 | bot + 白名单 + 外部群过滤；后续完成脱敏与原始明文不外送 |
| 历史数据含外部群 | 数据边界污染 | M0 提供 doctor/boundary，同步时自动跳过，显式确认后可清理 |
| 拔高设计与实际进度差距 | 简历口径失真 | M5/M6 只采纳实测指标，优先保证可复现 |

## 七、当前执行顺序

```text
M0（权限与边界） ──> M1（数据底座） ──> M2（图谱与检索）
                          │
                          ├──> M3（摘要）
                          └──> M4（Agent）──> M5（评测）──> M6（交付）
```
