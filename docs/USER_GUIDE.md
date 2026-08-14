# LarkNova 使用手册

## 1. 适用范围

LarkNova 是本地优先的企业飞书知识 Agent，包含消息同步、数据归一化、
话题索引、知识图谱、结构化摘要、Agent/Harness 问答、自动评测与 HTTP API。

当前身份基线为 `LARK_IDENTITY=user`。机器人读消息权限
`im:message:readonly` 开通并加入白名单群后，可切换到 `bot` 复验。

## 2. 环境准备

```powershell
cd D:\实习记录\组内项目\LarkNova
scripts\bootstrap.ps1
```

`bootstrap.ps1` 会：

- 创建 `data\` 与 `data\reports\` 目录。
- `.env` 不存在时从 `.env.example` 复制，已存在则保留当前配置。

首次使用还需在 `.env` 中确认：

- `LARK_IDENTITY=user`（当前基线）或 `bot`（权限窗口复验）。
- `LARK_CLI_JS` 指向本机 lark-cli 入口。
- 内部群白名单 `FEISHU_AGENT_ALLOWED_CHAT_IDS`。
- 可选 LLM 端点与 API Token。

## 3. 三种运行模式

### 3.1 合成演示（无需网络）

```powershell
scripts\demo.ps1
```

该命令依次执行：

```powershell
python -m feishu_agent.main --db data/synth.db synthetic seed --messages 0 --reset-derived
python -m feishu_agent.main --db data/synth.db eval run --mode rule --limit 0
python -m feishu_agent.main --db data/synth.db eval report
```

结果写入 `data/reports/resume_metrics.json`。该模式不依赖飞书网络与真实库，
适合新环境验收与简历指标复现。

### 3.2 真实库单次处理

```powershell
# 数据边界与权限体检
python -m feishu_agent.main doctor --identity user

# 同步、归一化、索引、摘要、问答
python -m feishu_agent.main sync --identity user
python -m feishu_agent.main normalize --rebuild
python -m feishu_agent.main index rebuild
python -m feishu_agent.main summary rebuild --mode rule
python -m feishu_agent.main agent ask "项目预算怎么安排的？" --mode rule
```

每步均可独立重建并校验：

```powershell
python -m feishu_agent.main index consistency
python -m feishu_agent.main summary consistency
python -m feishu_agent.main graph stats
python -m feishu_agent.main search "测试"
```

### 3.3 HTTP API 服务

```powershell
scripts\run_server.ps1 -Port 8080 -Interval 60 -Identity user -SyncOnStart
```

等价命令：

```powershell
python -m feishu_agent.main --db data/agent.db serve `
  --host 127.0.0.1 --port 8080 --interval 60 `
  --identity user --sync-on-start
```

`--interval 0` 关闭周期同步，只提供查询与 Agent API。
`FEISHU_AGENT_API_TOKEN` 与 `FEISHU_AGENT_RATE_LIMIT_PER_MIN` 从 `.env` 读取。

## 4. 常用命令

| 用途 | 命令 |
| --- | --- |
| 权限与边界体检 | `python -m feishu_agent.main doctor --identity user` |
| 边界审计/清理 | `python -m feishu_agent.main boundary` / `boundary --prune --yes` |
| 全量/单群同步 | `python -m feishu_agent.main sync` / `sync --chat-id oc_xxx` |
| 同步指标 | `python -m feishu_agent.main metrics` |
| 归一化复核 | `python -m feishu_agent.main normalize --rebuild` |
| 索引重建/增量/一致性 | `index rebuild` / `index incremental` / `index consistency` |
| 混合检索 | `search "关键词" --chat-id oc_xxx` |
| 图谱统计/实体 | `graph stats` / `graph entity 蒋林` |
| 摘要重建/增量/状态 | `summary rebuild --mode rule` / `summary incremental` / `summary status` |
| Agent 问答/回放 | `agent ask "..." --mode rule` / `agent trace <run_id>` / `agent stats` |
| 合成语料 | `--db data/synth.db synthetic seed --messages 0 --reset-derived` |
| 黄金评测 | `--db data/synth.db eval run --mode rule --limit 0` |
| 报告查看 | `--db data/synth.db eval report` |

## 5. 身份与数据边界

- 当前默认 `LARK_IDENTITY=user`，可枚举当前账号可见的群并同步历史消息。
- 机器人读取消息需在飞书后台开通 `im:message:readonly`，并加入白名单内部群。
- 机器人可枚举群聊但读消息返回 `230027` 时，`doctor` 会给出权限补验提示。
- `FEISHU_AGENT_ALLOWED_CHAT_IDS` 为逗号分隔的内部群白名单；留空放行所有内部群。
- `FEISHU_AGENT_ALLOW_EXTERNAL_CHATS=0` 默认排除外部群；历史越界数据可用
  `boundary` 审计并显式清理。

## 6. 数据恢复路径

派生数据全部可以从事实源重建：

```powershell
python -m feishu_agent.main normalize --rebuild
python -m feishu_agent.main index rebuild --allow-external
python -m feishu_agent.main summary rebuild --mode rule
python -m feishu_agent.main --db data/synth.db synthetic seed --messages 0 --reset-derived
```

合成库的 `--reset-derived` 会同时重建索引与摘要，保证干净环境可一键复现。

## 7. 评测报告注意事项

`eval run` 会把结构化报告写入固定路径
`data/reports/resume_metrics.json`，**不指定 `--db` 时会覆盖真实库评测结果**。

复现 M5 合成基线必须显式指定：

```powershell
python -m feishu_agent.main --db data/synth.db eval run --mode rule --limit 0
python -m feishu_agent.main --db data/synth.db eval report
```

## 8. 常见问题

### 报告变成 1/41

原因是 `eval run` 未加 `--db data/synth.db`，在真实库或空库上覆盖了黄金评测报告。
恢复命令见第 7 节。

### 同步返回 230027

当前是 `user` 身份运行，`230027` 只出现在 `bot` 读取消息时。先确认后台已开
`im:message:readonly`、机器人已加入白名单群，再执行 `doctor --identity bot` 复验。

### LLM 模式不可用

未配置 `FEISHU_AGENT_LLM_API_URL/API_KEY/MODEL` 时，`rule` 仍可运行；
`auto` 与 `llm` 模式下 LLM 失败会自动降级到规则链路并落盘 trace。

### 合成库状态不 ready

先执行 `synthetic seed --messages 0 --reset-derived`，再用
`synthetic status` 检查 7 chats / 115 messages / 索引与摘要是否已重建。
