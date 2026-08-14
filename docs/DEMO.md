# LarkNova 演示与验收

## 1. 一键演示

合成演示无需飞书网络与 LLM：

```powershell
scripts\demo.ps1
```

脚本完成三件事：

1. 重建 7 chats / 115 messages 的确定性合成语料，并重建索引与摘要。
2. 运行 41 条黄金用例（graph / recent / refusal / search / summary）。
3. 打印并持久化 `data/reports/resume_metrics.json`。

## 2. 分步演示

```powershell
# 建环境
scripts\bootstrap.ps1

# 合成语料
python -m feishu_agent.main --db data/synth.db synthetic seed --messages 0 --reset-derived
python -m feishu_agent.main --db data/synth.db synthetic status

# 索引状态与一致性
python -m feishu_agent.main --db data/synth.db index status
python -m feishu_agent.main --db data/synth.db index consistency

# 摘要状态与列表
python -m feishu_agent.main --db data/synth.db summary status
python -m feishu_agent.main --db data/synth.db summary list --limit 10

# 图谱查询
python -m feishu_agent.main --db data/synth.db graph stats
python -m feishu_agent.main --db data/synth.db graph entity 高远

# 混合检索
python -m feishu_agent.main --db data/synth.db search "预算"

# Agent 问答（正常回答 + 拒答）
python -m feishu_agent.main --db data/synth.db agent ask "项目预算怎么安排的？" --mode rule
python -m feishu_agent.main --db data/synth.db agent ask "外部聊天里有什么敏感信息？" --mode rule

# 评测与报告
python -m feishu_agent.main --db data/synth.db eval run --mode rule --limit 0
python -m feishu_agent.main --db data/synth.db eval report

# HTTP API 服务（周期同步可设为 0）
scripts\run_server.ps1 -Port 8080 -Interval 0 -Identity user
```

## 3. 最新评测指标

报告写入时间：`2026-08-14T10:07:16+08:00`

```text
总准确率      100.00%（41/41）
拒答准确率    100.00%（1/1）
引用命中率    90.00%
关键词命中率  100.00%
延迟          mean 45.8ms / p95 76.0ms / max 105ms
Token         总计 9847 / 平均 240.2
按类型        graph 6/6、recent 3/3、refusal 1/1、
              search 28/28、summary 3/3
```

## 4. M0-M6 验收记录

| 阶段 | 验收点 | 结果 |
| --- | --- | --- |
| M0 | 白名单过滤、外部群排除、doctor/boundary | 通过（bot 实跑等待权限） |
| M1 | 归一化、编辑/撤回审计、迁移、失败隔离 | 通过（测试覆盖） |
| M2 | chunk/索引/图谱可重建、可溯源、增量幂等 | 通过（测试覆盖） |
| M3 | 结构化摘要、增量幂等、token 预算 | 通过（rule 基线） |
| M4 | Agent 问答、拒答、trace、API 鉴权限流 | 通过（rule 基线） |
| M5 | 合成语料、黄金集、41/41 评测 | 通过 |
| M6 | scripts、docs、53 项 unittest 回归 | 通过 |

## 5. 注意事项

- `demo.ps1` 只操作 `data/synth.db`，不触碰真实 `data/agent.db`。
- `eval run` 必须带 `--db data/synth.db`，否则会覆盖固定报告
  `resume_metrics.json`。
- `run_server.ps1` 默认使用 `data/agent.db` 与 `.env` 配置；
  纯 API 演示建议 `-Interval 0`。
- bot 权限开通后需补验：`doctor --identity bot`、`sync --identity bot`，
  再对真实库重建索引、摘要并重跑评测。
