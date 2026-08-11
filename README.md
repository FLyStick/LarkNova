# 飞书 Agent 后端（MVP）

一个最小可运行的后端：拉取飞书群聊历史消息 → 写入 SQLite → 通过本地 HTTP API
对外提供查询。飞书侧复用本机已安装的 `lark-cli`，因此不需要额外集成 SDK，
代码只使用 Python 标准库。

## 方案结论

采用「机器人身份」方案可行，且正好满足“只归纳机器人所在群聊”的需求：

1. 机器人通过 `im +chat-list --as bot` 枚举自己加入的群聊。
2. 定时或首次拉取每个群的聊天记录，原始消息写入 `messages` 表。
3. AI 模块基于 `messages` 做归纳，结果写入 `summaries` 表。
4. 前端通过 HTTP API 查询原始消息或 AI 归纳结果。

当前唯一阻塞点：应用缺少 `im:message:readonly` 权限，机器人身份拉取消息返回
`230027`。开启权限后，将 `LARK_IDENTITY=bot` 重启服务即可切换为纯机器人身份。

## 当前测试状态

- 测试群：`飞书Agent测试群`
  - chat_id：`oc_11404e974de3daf54122b117e907d177`
  - 群成员：蒋林（open_id `ou_6bad0b5a57b571a7315ee8d6f5044a69`）
  - 机器人：十三的codex，open_id `ou_a2054e868f3d65dbedbb9e8b877c05e8`
- 本地库当前为 4 个会话、480 条消息，其中测试群 4 条。
- 机器人身份可以建群、枚举群聊；读取消息因权限 `230027` 暂不可用。
- 用户身份拉取消息已打通，首次同步和增量同步均验证通过。
- 拉取消息使用 `--page-all --page-limit 1000`。lark-cli 默认 `--page-limit 10`
  会把大群历史截断成每次只拉几十条，现已修复。
- 网络抖动会自动重试；周期同步与手动 `POST /api/sync` 串行执行，避免重复计数。

## 目录结构

```text
feishu_agent/
  config.py       环境变量与运行参数
  feishu/client.py lark-cli 封装（会话 + 消息）
  database/db.py  SQLite 表结构与查询
  sync/runner.py  首次同步与增量同步逻辑
  api/server.py   标准库 HTTP API
  main.py         CLI 入口
data/agent.db     本地 SQLite 数据库
```

## 数据表

- `chats`：群聊基础信息与最近同步时间。
- `messages`：消息原文、类型、发送者、时间、提及、原始 JSON 等。
- `sync_state`：每个群的增量游标（最后一条消息 ID / 时间）。
- `summaries`：预留的 AI 归纳结果表。

## 使用方法

在 Windows PowerShell 中执行：

```powershell
# 复制环境变量默认值（可选，所有配置都有默认值）
copy .env.example .env

# 首次同步 / 手动拉取
python -m feishu_agent.main sync --identity user

# 只同步指定群
python -m feishu_agent.main sync --identity user `
  --chat-id oc_11404e974de3daf54122b117e907d177

# 启动 HTTP API：启动时先同步一次，之后每 60 秒增量同步
python -m feishu_agent.main serve --port 8080 `
  --interval 60 --sync-on-start --identity user
```

## API 接口

```text
GET  /health
GET  /api/chats
GET  /api/messages?chat_id=oc_xxx&q=关键词&msg_type=text&limit=50
GET  /api/stats
POST /api/sync   {"full": false}
```

示例：

```bash
curl "http://127.0.0.1:8080/api/messages?chat_id=oc_11404e974de3daf54122b117e907d177&limit=20"
```

## 下一步

1. 在飞书开发者后台（https://open.feishu.cn/app/cli_aaf825fe1ef81d06/permission）
   开启 `im:message:readonly`，设置 `LARK_IDENTITY=bot` 后重新同步，验证机器人
   只能读到它所在群的消息。
2. 基于 `messages` 表实现 AI 归纳模块，结果写入 `summaries`。
3. 增加面向 Agent/前端的查询接口，支持按群、时间、发送者、消息类型过滤，并返回
   归纳后的上下文。
