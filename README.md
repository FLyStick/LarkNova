# LarkNova 企业飞书知识 Agent

LarkNova 是在现有飞书消息同步 MVP 基础上迭代的**企业飞书知识 Agent**：

开放平台接入 → 数据底座 → 知识图谱 → Agent/Harness 编排 → 可信评测 → 业务闭环。

当前阶段：`M6 交付完成`（user 身份基线，核心已完成）。
由于机器人暂无法加入测试群，项目按 `LARK_IDENTITY=user` 继续推进；
bot 权限窗口已预留，代码侧不依赖 bot 身份完成数据管道、索引、摘要、Agent 与评测链路，
权限开通后补验。

## 目标架构

```text
飞书开放平台（lark-cli / 事件订阅）
        │
        ▼
M1 数据底座：同步、清洗、编辑/撤回、迁移、失败隔离、数据边界
        │
        ▼
M2 知识层：thread/话题切分、FTS5 + 稀疏向量索引、实体与关系知识图谱
        │
        ▼
M3 AI 摘要：结论 + 依据 + 待办、增量摘要、token 预算
        │
        ▼
M4 Agent + Harness：自研 Harness 编排、工具注册表、降级与 trace
        │
        ▼
M5 评测闭环：黄金测试集、检索/问答指标、Badcase 迭代
        │
        ▼
M6 交付：.env 模板、启动脚本、运行手册、架构文档、演示文档、全量回归、resume_metrics.json
```

## 当前现状

- 本地库：2 个内部群、22 条消息（其中可索引 12 条，其余为系统提示/低信号系统消息），消息类型含 `text/system` 等。
- 用户身份同步已打通：全量 + 增量双游标、`message_id` 幂等、单群失败隔离，同步结果写入 `sync_runs`。
- M1 已完成核心代码：富文本/交互/合并转发归一化、`content_hash`、编辑/撤回审计
  `message_versions`、DB 迁移机制（v2/v3/v4/v5/v6）、同步指标与 `normalize --rebuild` 重建命令。
- M2 已完成核心代码：thread/时间窗口 chunk、中文 bigram + FTS5 BM25、
  稀疏 TF-IDF 与 RRF 融合检索、SQLite 规则知识图谱（entities/edges）、
  重建/增量/一致性/搜索/图谱 CLI、同步后自动增量索引。
- M3 已完成核心代码：rule 确定性摘要 + LLM 可选模式、结论/依据/待办结构化输出、
  重建/增量/一致性/状态 CLI 与 API、同步后自动增量摘要、token 预算统计。
- M4 已完成核心代码：自研标准库 AgentHarness（search 工具 + 步骤 trace）、
  rule/llm/auto 三模式、无依据拒答、LLM 引用校验、敏感词与预算护栏、
  `agent_runs/agent_traces` 持久化、`agent ask/runs/trace/stats` CLI、
  `/api/agent/*` 鉴权与限流。
- M5 已完成核心代码：确定性合成语料生成器 + 黄金测试集 + 自动化评测闭环，
  `--db` 支持独立临时库，rule 评测可一键复现；当前 115 条合成消息、
  41 条黄金用例全量通过，报告自动写入 `data/reports/resume_metrics.json`。
- M6 已交付：`.env.example` 模板、`scripts/bootstrap.ps1`、`scripts/demo.ps1`、
  `scripts/run_server.ps1`、运行手册/架构文档/演示文档，53 项单元测试全绿，
  合成评测基线 41/41 可一键复现。
- 机器人身份可枚举群聊，读取消息因缺少 `im:message:readonly` 返回 `230027`。
- M0 已落地：`FEISHU_AGENT_ALLOWED_CHAT_IDS` 白名单、外部群默认排除、
  `python -m feishu_agent.main doctor` 可一键检测权限与数据边界，`boundary` 可审计/清理历史越界数据；
  M0 代码已完成，bot 实跑等待权限。

## M0-M6 验收清单

```text
[x] 白名单外部群/非白名单群不入库
[x] doctor 可诊断权限、白名单缺失、外部群
[x] boundary 可审计/清理历史越界数据
[x] 富文本/交互/合并转发归一化，主要消息类型有测试
[x] message_versions 编辑/撤回审计，重建幂等
[x] sync_runs 指标与单群失败隔离
[x] DB 迁移机制与旧库回填
[x] 24 项单元测试全绿（M0/M1）
[x] 34 项单元测试全绿（M2 加入 chunk/检索/图谱/增量/同步钩子）
[x] M2 索引全量重建：2 群、22 条消息、12 条可索引、3 个 chunk
[x] M2 consistency 通过：索引覆盖与可索引源消息一致
[x] 中文/英文混合检索可溯源：返回 chunk、消息 ID、时间、发送者
[x] graph stats/entity 可查询（4 实体 / 26 mentions / 17 边）
[x] M3 阶段累计 39 项单元测试全绿
[x] M3 摘要重建：2 群、12 条索引消息、3 个 chunk、生成 2 条摘要
[x] M3 summary consistency 通过：摘要覆盖与索引消息一致
[x] M3 summary incremental 幂等：rebuild 后返回 no_changes
[x] M3 摘要可溯源：结构字段 + source_message_ids + hash 可查询
[x] 48 项单元测试全绿（M4 加入 AgentHarness/API/鉴权/限流）
[x] M4 rule 问答：真实库可回答、可拒答、结果带消息级引用
[x] M4 trace 可回放：agent runs/trace 返回完整输入/输出/耗时/引用
[x] M4 API：/api/agent/ask、runs、stats 可用，token/限流有测试
[x] 53 项单元测试全绿（M5 加入合成语料与评测闭环）
[x] synthetic seed：7 chats / 115 messages / 71 chunks / 62 entities / 352 edges
[x] 合成摘要：6 summaries / 115 messages covered / 71 chunks covered，全量重建可幂等
[x] eval run：41/41 黄金用例全量通过，总准确率 100%
[x] 拒答准确率 100%、关键词命中 100%、引用命中 90%，报告写入 resume_metrics.json
[x] 真实库消息不足时可用合成库完成指标，生产数据重建后重跑 eval run
[x] M6 scripts：bootstrap / demo / run_server 可一键启动、一键演示、一键服务化
[x] M6 docs：运行手册、架构说明、演示验收文档与现状一致
[x] M6 全量回归：53 项 unittest 全绿
[ ] 飞书后台开通 im:message:readonly（权限窗口）
[ ] LARK_IDENTITY=bot 后 sync 无 230027（权限窗口）
[ ] 入库会话集合与白名单一致，bot 实跑补验
```

## 数据存储原则

当前 `messages` 表按“一条消息一行”全量存储，作为事实源是合理的：`message_id`
主键保证幂等，`raw_json` 保留原文，`content` 提供查询用文本。

派生数据已按独立表拆分，避免同表三层冗余：

```text
messages            事实源（单条全量，保留版本）
message_versions    编辑/撤回审计
chunks              检索语料单元
entities/edges      知识图谱
summaries           结构化摘要
FTS5 / 稀疏向量表   索引层，可重建
```

## 目录结构

```text
feishu_agent/
  config.py                     环境变量与运行参数（身份、白名单、外部群策略）
  feishu/client.py              lark-cli 封装（会话 + 消息）
  database/db.py                SQLite 表结构与查询
  database/migrations.py        幂等 DB 迁移（v2/v3/v4/v5/v6）
  normalize.py                  富文本归一化与内容摘要
  sync/runner.py                全量/增量同步 + 数据边界过滤 + 失败隔离
  agent/protocol.py             Agent 问题/引用/步骤/回答协议
  agent/repository.py           agent_runs/agent_traces 持久化
  agent/tools.py                工具注册表（search 等可扩展工具）
  agent/harness.py              自研 AgentHarness：rule/llm/auto + 降级 + trace
  index/chunker.py              thread/时间窗口 chunk 生成
  index/tokenizer.py            中文 bigram + ASCII token、FTS5 安全编码
  index/repository.py           重建/增量/一致性/混合检索/图谱仓库
  index/graph.py                规则实体抽取与回复关系图谱
  summary/repository.py         摘要持久化：rebuild/incremental/consistency/status
  summary/rule_summarizer.py    确定性规则摘要（结构字段 + token 估算）
  summary/llm_summarizer.py     OpenAI 兼容 LLM 摘要
  summary/budget.py             上下文构建与 token 预算
  summary/factory.py            摘要模式工厂
  synthetic/seed.py             确定性合成语料生成（人事/风控/财务/招采场景）
  eval/golden.py                黄金测试集定义与序列化
  eval/runner.py                自动化评测 runner（rule/llm/auto）
  eval/metrics.py               指标计算（准确率/引用/关键词/延迟/token）
  eval/report.py                评测报告格式化与写盘
  doctor.py                     bot 权限与数据边界体检
  boundary.py                   本地库边界审计与显式清理
  api/server.py                 标准库 HTTP API
  main.py                       CLI（sync/doctor/boundary/stats/metrics/normalize/index/search/graph/summary/agent/synthetic/eval/serve）
tests/             M0-M6 自动化测试（53 项）
scripts/bootstrap.ps1   本地环境初始化
scripts/demo.ps1        合成语料 + 黄金评测一键演示
scripts/run_server.ps1  HTTP API 启动脚本
docs/ROADMAP.md    分阶段规划与验收
docs/PLAN.md       详细任务拆解
docs/USER_GUIDE.md 运行手册
docs/ARCHITECTURE.md 架构说明
docs/DEMO.md       演示与验收文档
data/agent.db      本地 SQLite 数据库（不入库）
data/synth.db      M5 合成语料库（不入库）
data/reports/      评测报告（resume_metrics.json，不入库）
```

## 环境变量

```text
LARK_IDENTITY=user                      # 权限开通后切换为 bot
FEISHU_AGENT_ALLOWED_CHAT_IDS=          # 内部群白名单，逗号分隔；空则放行全部内部群
FEISHU_AGENT_ALLOW_EXTERNAL_CHATS=0     # 默认排除外部群
FEISHU_AGENT_DB=data/agent.db
FEISHU_AGENT_SYNC_INTERVAL=60
FEISHU_AGENT_SUMMARY_MAX_CHARS=4000
FEISHU_AGENT_SUMMARY_INPUT_TOKEN_BUDGET=6000
FEISHU_AGENT_SUMMARY_OUTPUT_TOKEN_BUDGET=1200
FEISHU_AGENT_SUMMARY_MIN_NEW_MESSAGES=1
FEISHU_AGENT_LLM_API_URL=
FEISHU_AGENT_LLM_API_KEY=
FEISHU_AGENT_LLM_MODEL=
FEISHU_AGENT_MAX_QUESTION_CHARS=2000
FEISHU_AGENT_MAX_ANSWER_CHARS=2000
FEISHU_AGENT_MAX_EVIDENCE_ITEMS=10
FEISHU_AGENT_MAX_STEPS=5
FEISHU_AGENT_SENSITIVE_WORDS=password,secret,api_key,access_token,密钥,密码,身份证号,银行卡号
FEISHU_AGENT_API_TOKEN=
FEISHU_AGENT_RATE_LIMIT_PER_MIN=0
LARK_NODE=node
LARK_CLI_JS=D:\App\nodejs\node_global\node_modules\@larksuite\cli\scripts\run.js
```

完整说明见 `.env.example`。

## 使用方法

Windows PowerShell：

```powershell
scripts\bootstrap.ps1
# 参考 docs\USER_GUIDE.md 完成 .env 配置

# 合成演示：无网络重建语料、跑 41 条黄金用例并生成报告
scripts\demo.ps1

# HTTP API：默认 data/agent.db，鉴权/限流从 .env 读取
scripts\run_server.ps1 -Port 8080 -Interval 60 -Identity user -SyncOnStart

# 体检：身份能否枚举群聊、机器人能否读消息、白名单/外部群是否生效
python -m feishu_agent.main doctor --identity user

# 审计本地库中的历史越界数据（默认不删除）
python -m feishu_agent.main boundary

# 确认后清理本地库中的外部群/非白名单群
python -m feishu_agent.main boundary --prune --yes

# 首次/增量同步（当前以 user 身份为基线）
python -m feishu_agent.main sync --identity user

# 只同步指定群（仍受白名单约束）
python -m feishu_agent.main sync --identity user `
  --chat-id oc_11404e974de3daf54122b117e907d177

# 查看本地库统计
python -m feishu_agent.main stats

# 查看同步指标与最近运行记录
python -m feishu_agent.main metrics

# 检查/重建消息归一化结果（旧库迁移后也可执行）
python -m feishu_agent.main normalize
python -m feishu_agent.main normalize --rebuild

# 全量重建主题 / 检索 / 图谱派生索引
python -m feishu_agent.main index rebuild

# 增量索引已随 sync 自动触发，也可以手动执行并查看状态/一致性
python -m feishu_agent.main index incremental
python -m feishu_agent.main index status
python -m feishu_agent.main index consistency

# 中文/英文混合检索（BM25 + 稀疏 TF-IDF + RRF）
python -m feishu_agent.main search "测试" --chat-id oc_11404e974de3daf54122b117e907d177

# 知识图谱统计与实体查询
python -m feishu_agent.main graph stats
python -m feishu_agent.main graph entity 蒋林

# 生成/重建 M5 合成语料（真实库消息不足时用于评测基线；重置派生索引/摘要）
python -m feishu_agent.main --db data/synth.db synthetic seed --messages 0 --reset-derived
python -m feishu_agent.main --db data/synth.db synthetic status

# 生成/刷新结构化摘要（rule 为确定性基线；LLM 需配置 OpenAI 兼容端点）
python -m feishu_agent.main summary rebuild --mode rule
python -m feishu_agent.main summary incremental --mode rule
python -m feishu_agent.main summary list --limit 10
python -m feishu_agent.main summary consistency
python -m feishu_agent.main summary status

# M4 Agent：rule 是确定性基线；llm/auto 需要配置 OpenAI 兼容端点
python -m feishu_agent.main agent ask "项目预算怎么安排的？" --mode rule
python -m feishu_agent.main agent runs --limit 10
python -m feishu_agent.main agent trace 977b3545a0b14eeb9fc942987a10c12e
python -m feishu_agent.main agent stats

# M5 评测：一键跑黄金用例并生成报告（--limit 0 表示全量）
python -m feishu_agent.main --db data/synth.db eval run --mode rule --limit 0
python -m feishu_agent.main --db data/synth.db eval report
python -m feishu_agent.main --db data/synth.db eval samples --limit 10

# 启动 HTTP API，启动时同步一次，之后每 60 秒增量同步
python -m feishu_agent.main --db data/agent.db serve --port 8080 `
  --interval 60 --sync-on-start --identity user `
  --api-token your-token --rate-limit-per-min 60

# bot 权限开通且机器人加入白名单群后，再做一次复验
python -m feishu_agent.main doctor --identity bot
python -m feishu_agent.main sync --identity bot
```

## 测试

第一阶段测试使用标准库 `unittest`，无需安装第三方依赖：

```powershell
python -m unittest discover -s tests -v
```

覆盖内容：白名单过滤、外部群排除、显式 `--chat-id` 仍受白名单约束、
`doctor` 对 `230027` 的识别与修复提示、`boundary` 本地审计/清理、消息幂等写入、
归一化、编辑/撤回审计、DB 迁移回填、同步指标与单群失败隔离、
索引重建/增量/一致性/图谱、摘要重建/增量幂等/LLM 配置校验、
Agent rule/llm/auto 链路、无依据拒答、敏感词、引用校验、API 鉴权与限流、
合成语料确定性与全量重建、黄金集序列化与 41 条全量评测。

## API 接口

```text
GET  /health
GET  /api/chats
GET  /api/messages?chat_id=oc_xxx&q=关键词&msg_type=text&limit=50
GET  /api/stats
POST /api/sync   {"full": false}
GET  /api/metrics?limit=10
GET  /api/sync-runs?limit=20
GET  /api/message-versions?message_id=om_xxx&limit=100
GET  /api/search?q=测试&chat_id=oc_xxx&limit=10
GET  /api/graph/entities?type=person&q=蒋林
GET  /api/graph/entity?q=蒋林
GET  /api/index/status
POST /api/index/rebuild     {"allow_external": false, "chat_ids": []}
POST /api/index/incremental {"chat_ids": []}
GET  /api/summaries?chat_id=oc_xxx&limit=10
GET  /api/summaries/status
POST /api/summaries/rebuild     {"mode": "rule", "chat_ids": []}
POST /api/summaries/incremental {"mode": "rule", "chat_ids": []}
POST /api/agent/ask             {"question": "...", "mode": "rule"}
GET  /api/agent/runs?limit=10
GET  /api/agent/runs/<id>
GET  /api/agent/stats
# /api/agent/* 支持 Bearer / X-API-Token 鉴权，可通过环境变量开启限流
```

## 后续窗口

M6 已交付后剩余窗口：

- bot 权限补验：开通 `im:message:readonly`、机器人加入白名单群后，
  执行 `doctor --identity bot` 与 `sync --identity bot` 复验。
- 真实库重跑：生产群消息充足后重建索引/摘要，再以
  `--db data/agent.db eval run` 重跑黄金评测与 `resume_metrics.json`。
- badcase 周闭环与消融实验：chunk 大小、Top-K、相似度阈值、
  时间衰减权重与 Rerank 调优，随真实数据补充。

详细规划和验收标准见 `docs/ROADMAP.md`。
