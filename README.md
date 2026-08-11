# LarkNova 企业飞书知识 Agent

LarkNova 是在现有飞书消息同步 MVP 基础上迭代的**企业飞书知识 Agent**：

开放平台接入 → 数据底座 → 知识图谱 → Agent/Harness 编排 → 可信评测 → 业务闭环。

当前阶段：`M1 数据管道生产化`（进行中，user 身份基线）。
由于机器人暂无法加入测试群，项目按 `LARK_IDENTITY=user` 继续推进；
bot 权限窗口已预留，代码侧不依赖 bot 身份完成数据管道，权限开通后补验。

## 目标架构

```text
飞书开放平台（lark-cli / 事件订阅）
        │
        ▼
M1 数据底座：同步、清洗、编辑/撤回、迁移、失败隔离、数据边界
        │
        ▼
M2 知识层：thread/话题切分、FTS5 + 向量索引、实体与关系知识图谱
        │
        ▼
M3 AI 摘要：结论 + 依据 + 待办、增量摘要、token 预算
        │
        ▼
M4 Agent + Harness：LangGraph 编排、MCP 工具、降级与 trace
        │
        ▼
M5 评测闭环：黄金测试集、检索/问答指标、Badcase 迭代
        │
        ▼
M6 交付：文档、Demo、pytest、resume_metrics.json
```

## 当前现状

- 本地库：4 个会话、482 条消息（其中 2 个历史外部群共 467 条，M0 后不计入业务指标），消息类型含 `text/post/interactive/system` 等。
- 用户身份同步已打通：全量 + 增量双游标、`message_id` 幂等、单群失败隔离，同步结果写入 `sync_runs`。
- M1 已完成核心代码：富文本/交互/合并转发归一化、`content_hash`、编辑/撤回审计
  `message_versions`、DB 迁移机制（v2/v3）、同步指标与 `normalize --rebuild` 重建命令。
- 机器人身份可枚举群聊，读取消息因缺少 `im:message:readonly` 返回 `230027`。
- M0 已落地：`FEISHU_AGENT_ALLOWED_CHAT_IDS` 白名单、外部群默认排除、
  `python -m feishu_agent.main doctor` 可一键检测权限与数据边界，`boundary` 可审计/清理历史越界数据；
  M0 代码已完成，bot 实跑等待权限。

## 第一阶段 M0/M1 验收清单

```text
[x] 白名单外部群/非白名单群不入库
[x] doctor 可诊断权限、白名单缺失、外部群
[x] boundary 可审计/清理历史越界数据
[x] 富文本/交互/合并转发归一化，主要消息类型有测试
[x] message_versions 编辑/撤回审计，重建幂等
[x] sync_runs 指标与单群失败隔离
[x] DB 迁移机制与旧库回填
[x] 24 项单元测试全绿
[ ] 飞书后台开通 im:message:readonly（权限窗口）
[ ] LARK_IDENTITY=bot 后 sync 无 230027（权限窗口）
[ ] 入库会话集合与白名单一致，bot 实跑补验
```

## 数据存储原则

当前 `messages` 表按“一条消息一行”全量存储，作为事实源是合理的：`message_id`
主键保证幂等，`raw_json` 保留原文，`content` 提供查询用文本。

后续演进时会把派生数据从事实源拆出来，避免同表三层冗余：

```text
messages            事实源（单条全量，保留版本）
message_versions    编辑/撤回审计
chunks              检索语料单元
entities/edges      知识图谱
summaries           结构化摘要
FTS5 / 向量库        索引层，可重建
```

## 目录结构

```text
feishu_agent/
  config.py                     环境变量与运行参数（身份、白名单、外部群策略）
  feishu/client.py              lark-cli 封装（会话 + 消息）
  database/db.py                SQLite 表结构与查询
  database/migrations.py        幂等 DB 迁移（v2/v3）
  normalize.py                  富文本归一化与内容摘要
  sync/runner.py                全量/增量同步 + 数据边界过滤 + 失败隔离
  doctor.py                     bot 权限与数据边界体检
  boundary.py                   本地库边界审计与显式清理
  api/server.py                 标准库 HTTP API
  main.py                       CLI 入口（sync/doctor/boundary/stats/metrics/normalize/serve）
tests/             第一阶段自动化测试
docs/ROADMAP.md    分阶段规划与验收
docs/PLAN.md       详细任务拆解
data/agent.db      本地 SQLite 数据库（不入库）
```

## 环境变量

```text
LARK_IDENTITY=user                      # 权限开通后切换为 bot
FEISHU_AGENT_ALLOWED_CHAT_IDS=          # 内部群白名单，逗号分隔；空则放行全部内部群
FEISHU_AGENT_ALLOW_EXTERNAL_CHATS=0     # 默认排除外部群
FEISHU_AGENT_DB=data/agent.db
FEISHU_AGENT_SYNC_INTERVAL=60
LARK_NODE=node
LARK_CLI_JS=D:\App\nodejs\node_global\node_modules\@larksuite\cli\scripts\run.js
```

完整说明见 `.env.example`。

## 使用方法

Windows PowerShell：

```powershell
copy .env.example .env
# 程序启动时自动读取项目根目录 .env；真实环境变量优先。

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

# 启动 HTTP API，启动时同步一次，之后每 60 秒增量同步
python -m feishu_agent.main serve --port 8080 `
  --interval 60 --sync-on-start --identity user

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
归一化、编辑/撤回审计、DB 迁移回填、同步指标与单群失败隔离。

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
```

## 后续阶段

M2 主题组织与索引：thread/话题切分、chunk、FTS5 + 向量、知识图谱、增量索引。
 M4 Agent + Harness：LangGraph、MCP 工具、降级与 trace。
M5 评测闭环：黄金测试集、检索/问答指标、Badcase 迭代。
M6 交付与简历固化：README、Demo、可复现指标。

详细规划和验收标准见 `docs/ROADMAP.md`。
