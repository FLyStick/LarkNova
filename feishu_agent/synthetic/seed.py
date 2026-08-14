"""M5 synthetic corpus: deterministic multi-department chats for local testing.

The seed writes only fact-source rows (chats/messages) with stable synthetic
message ids. Derived indexes and summaries are rebuilt through the same
repositories used by production, so every M5 metric is reproducible.
"""

from __future__ import annotations

from typing import Any

from feishu_agent.config import Settings
from feishu_agent.database.db import Database
from feishu_agent.index.repository import IndexRepository
from feishu_agent.summary.repository import SummaryRepository

CHAT_DEFS = [
    {
        "chat_id": "oc_syn_hr",
        "key": "hr",
        "name": "人事群",
        "description": "HR 招聘、绩效、考勤与离职协调",
        "external": 0,
    },
    {
        "chat_id": "oc_syn_risk",
        "key": "risk",
        "name": "风控群",
        "description": "尽调、授信、供应商风险与用印复核",
        "external": 0,
    },
    {
        "chat_id": "oc_syn_finance",
        "key": "finance",
        "name": "财务群",
        "description": "预算、报销、资金与对账",
        "external": 0,
    },
    {
        "chat_id": "oc_syn_procure",
        "key": "procure",
        "name": "招采群",
        "description": "采购方案、报价比选、合同与验收",
        "external": 0,
    },
    {
        "chat_id": "oc_syn_project",
        "key": "project",
        "name": "项目群",
        "description": "研发交付、问题定位、发布与灰度",
        "external": 0,
    },
    {
        "chat_id": "oc_syn_ops",
        "key": "ops",
        "name": "运维群",
        "description": "监控告警、CI 优化、补丁与权限治理",
        "external": 0,
    },
    {
        "chat_id": "oc_syn_qa_empty",
        "key": "qa_empty",
        "name": "拒答验证群",
        "description": "用于验证无证据时正确拒答的空群",
        "external": 0,
    },
]

PEOPLE = {
    "hr": {
        "wang": "王芳",
        "li": "李明",
        "zhang": "张伟",
        "zhou": "周琳",
    },
    "risk": {
        "chen": "陈晨",
        "zhao": "赵磊",
        "sun": "孙悦",
    },
    "finance": {
        "wu": "吴倩",
        "zhou": "周涛",
        "liu": "刘雨",
    },
    "procure": {
        "zheng": "郑强",
        "wang": "王鹏",
        "he": "何静",
        "yao": "姚明",
    },
    "project": {
        "zhao": "赵一",
        "qian": "钱枫",
        "sun": "孙晓",
    },
    "ops": {
        "gao": "高远",
        "liu": "刘峰",
        "chen": "陈曦",
    },
    "qa_empty": {},
}

TOPIC_DEFS: dict[str, list[dict[str, Any]]] = {
    "hr": [
        {
            "id": "hc",
            "title": "新增HC计划",
            "messages": [
                {
                    "time": "2026-08-01 09:30:00",
                    "sender": "wang",
                    "content": "本季度新增HC计划已确认：研发5个、销售2个、客服1个，总计8个HC。",
                },
                {
                    "time": "2026-08-01 09:35:00",
                    "sender": "li",
                    "content": "研发HC重点放在图像算法和前端工程，2个岗位走内部推荐。",
                    "reply": True,
                },
                {
                    "time": "2026-08-01 10:02:00",
                    "sender": "wang",
                    "content": "HC审批表今天提交，本周五前完成岗位发布。",
                },
                {
                    "time": "2026-08-01 10:18:00",
                    "sender": "zhang",
                    "content": "收到，算法岗我同步一份候选人名单。",
                    "reply": True,
                },
            ],
        },
        {
            "id": "zhangwei",
            "title": "张伟入职",
            "messages": [
                {
                    "time": "2026-08-03 14:00:00",
                    "sender": "li",
                    "content": "张伟复试已完成，评级P6，建议薪酬32K乘15个月，9月1日入职。",
                },
                {
                    "time": "2026-08-03 14:20:00",
                    "sender": "wang",
                    "content": "已确认，走offer审批流程，尽快发正式offer。",
                },
                {
                    "time": "2026-08-03 15:00:00",
                    "sender": "zhang",
                    "content": "谢谢各位，我会在9月1日前办理完离职交接。",
                    "reply": True,
                },
            ],
        },
        {
            "id": "performance",
            "title": "绩效申诉",
            "messages": [
                {
                    "time": "2026-08-05 11:00:00",
                    "sender": "li",
                    "content": "绩效申诉材料请于8月10日18:00前提交，逾期不再受理。",
                },
                {
                    "time": "2026-08-05 11:22:00",
                    "sender": "wang",
                    "content": "申诉复核流程已确认，结果8月15日公布。",
                },
                {
                    "time": "2026-08-05 12:05:00",
                    "sender": "zhang",
                    "content": "明白了，材料今天提交。",
                },
            ],
        },
        {
            "id": "liting",
            "title": "李婷离职交接",
            "messages": [
                {
                    "time": "2026-08-06 09:00:00",
                    "sender": "li",
                    "content": "李婷已提出离职，最后工作日8月21日。",
                },
                {
                    "time": "2026-08-06 09:12:00",
                    "sender": "wang",
                    "content": "交接人确定为周琳，交接清单8月18日前完成。",
                },
                {
                    "time": "2026-08-06 09:30:00",
                    "sender": "zhou",
                    "content": "收到，我按清单推进并整理知识库。",
                    "reply": True,
                },
            ],
        },
        {
            "id": "attendance",
            "title": "考勤异常",
            "messages": [
                {
                    "time": "2026-08-10 16:00:00",
                    "sender": "wang",
                    "content": "8月考勤异常共7人，请今天核对补卡记录。",
                },
                {
                    "time": "2026-08-10 16:10:00",
                    "sender": "li",
                    "content": "补卡截止8月14日，未提交将按缺勤处理。",
                    "reply": True,
                },
                {
                    "time": "2026-08-10 17:00:00",
                    "sender": "zhang",
                    "content": "已提醒3名同事尽快补卡。",
                },
            ],
        },
    ],
    "risk": [
        {
            "id": "huachen",
            "title": "华辰尽调",
            "messages": [
                {
                    "time": "2026-08-02 10:00:00",
                    "sender": "chen",
                    "content": "华辰科技尽调已通过，实缴资本2000万，近3年无重大诉讼。",
                },
                {
                    "time": "2026-08-02 10:20:00",
                    "sender": "zhao",
                    "content": "尽调结论确认，进入框架合同流程。",
                },
                {
                    "time": "2026-08-02 10:40:00",
                    "sender": "sun",
                    "content": "已同步法务和财务。",
                },
            ],
        },
        {
            "id": "framework",
            "title": "框架授信",
            "messages": [
                {
                    "time": "2026-08-04 14:00:00",
                    "sender": "zhao",
                    "content": "华辰框架合同授信500万，付款期限90天。",
                },
                {
                    "time": "2026-08-04 14:15:00",
                    "sender": "chen",
                    "content": "条款已确认，风险敞口在授权范围内。",
                    "reply": True,
                },
                {
                    "time": "2026-08-04 14:30:00",
                    "sender": "sun",
                    "content": "用印申请今天提交。",
                },
            ],
        },
        {
            "id": "jiaxing",
            "title": "嘉兴供应商",
            "messages": [
                {
                    "time": "2026-08-08 15:00:00",
                    "sender": "chen",
                    "content": "嘉兴材料供应商出现资金链风险，未付款180万建议暂缓。",
                },
                {
                    "time": "2026-08-08 15:18:00",
                    "sender": "zhao",
                    "content": "先暂缓付款，8月14日前给出最终结论。",
                    "reply": True,
                },
                {
                    "time": "2026-08-08 15:45:00",
                    "sender": "sun",
                    "content": "已通知采购暂停新增订单。",
                },
            ],
        },
        {
            "id": "seal",
            "title": "用印申请",
            "messages": [
                {
                    "time": "2026-08-11 10:00:00",
                    "sender": "sun",
                    "content": "用印申请YY-2026-0812今天提交，需双人复核。",
                },
                {
                    "time": "2026-08-11 10:12:00",
                    "sender": "zhao",
                    "content": "已确认复核人：陈晨、孙悦。",
                },
                {
                    "time": "2026-08-11 10:30:00",
                    "sender": "chen",
                    "content": "印章管理员明天上午盖章。",
                    "reply": True,
                },
            ],
        },
    ],
    "finance": [
        {
            "id": "budget",
            "title": "8月预算",
            "messages": [
                {
                    "time": "2026-08-03 09:00:00",
                    "sender": "wu",
                    "content": "8月预算已确认1260万，其中研发680万。",
                },
                {
                    "time": "2026-08-03 09:20:00",
                    "sender": "zhou",
                    "content": "市场与销售预算微调，总额不变。",
                },
                {
                    "time": "2026-08-03 09:45:00",
                    "sender": "wu",
                    "content": "预算表今天18:00前更新到共享空间。",
                },
            ],
        },
        {
            "id": "reimburse",
            "title": "报销补票",
            "messages": [
                {
                    "time": "2026-08-05 13:00:00",
                    "sender": "zhou",
                    "content": "7月还有23笔报销未开票，请8月14日前补票。",
                },
                {
                    "time": "2026-08-05 13:10:00",
                    "sender": "wu",
                    "content": "已同步各部门财务对接人，逾期将转下月处理。",
                },
                {
                    "time": "2026-08-05 13:40:00",
                    "sender": "liu",
                    "content": "研发侧还有6笔，今天补齐。",
                },
            ],
        },
        {
            "id": "q3",
            "title": "Q3资金",
            "messages": [
                {
                    "time": "2026-08-10 09:20:00",
                    "sender": "wu",
                    "content": "Q3预计结余420万，融资300万将于8月14日入账。",
                },
                {
                    "time": "2026-08-10 09:40:00",
                    "sender": "zhou",
                    "content": "入账后按计划补充研发预算。",
                    "reply": True,
                },
                {
                    "time": "2026-08-10 10:00:00",
                    "sender": "liu",
                    "content": "资金计划表已更新。",
                },
            ],
        },
        {
            "id": "reconcile",
            "title": "银行对账",
            "messages": [
                {
                    "time": "2026-08-12 17:00:00",
                    "sender": "zhou",
                    "content": "银行对账发现3笔未达账项，金额合计18.6万。",
                },
                {
                    "time": "2026-08-12 17:15:00",
                    "sender": "wu",
                    "content": "已确认其中2笔为跨行延迟，1笔待银行回单。",
                    "reply": True,
                },
                {
                    "time": "2026-08-12 17:40:00",
                    "sender": "liu",
                    "content": "8月15日前完成账务调整。",
                },
            ],
        },
    ],
    "procure": [
        {
            "id": "gpu",
            "title": "GPU采购方案",
            "messages": [
                {
                    "time": "2026-08-03 10:00:00",
                    "sender": "zheng",
                    "content": "GPU服务器采购方案已确认：2台8卡训练节点，NV A100，预算96万。",
                },
                {
                    "time": "2026-08-03 10:20:00",
                    "sender": "wang",
                    "content": "8卡节点建议直接采购整机，后续扩容按单卡评估。",
                    "reply": True,
                },
                {
                    "time": "2026-08-03 10:45:00",
                    "sender": "zheng",
                    "content": "方案按整机走，今天发报价邀请。",
                },
            ],
        },
        {
            "id": "quote",
            "title": "GPU报价比选",
            "messages": [
                {
                    "time": "2026-08-06 14:00:00",
                    "sender": "zheng",
                    "content": "三份报价已收到：华辰92万、云启88万、星河95万。",
                },
                {
                    "time": "2026-08-06 14:20:00",
                    "sender": "wang",
                    "content": "云启最低，建议作为候选第一名。",
                    "reply": True,
                },
                {
                    "time": "2026-08-06 15:00:00",
                    "sender": "he",
                    "content": "已按最低价原则整理比价表。",
                },
            ],
        },
        {
            "id": "line",
            "title": "网络专线",
            "messages": [
                {
                    "time": "2026-08-07 11:00:00",
                    "sender": "wang",
                    "content": "网络专线A标段评审完成，中选华辰，合同156万。",
                },
                {
                    "time": "2026-08-07 11:15:00",
                    "sender": "zheng",
                    "content": "合同条款已确认，本周五签署。",
                },
                {
                    "time": "2026-08-07 11:30:00",
                    "sender": "he",
                    "content": "合同章与付款节点已排期。",
                },
            ],
        },
        {
            "id": "order",
            "title": "采购验收",
            "messages": [
                {
                    "time": "2026-08-08 16:00:00",
                    "sender": "he",
                    "content": "ORD-2026-0811已收货完成，金额28.6万。",
                },
                {
                    "time": "2026-08-08 16:20:00",
                    "sender": "zheng",
                    "content": "请按流程安排验收，验收人姚明。",
                    "reply": True,
                },
                {
                    "time": "2026-08-08 17:00:00",
                    "sender": "wang",
                    "content": "验收单今天提交，预计下周开票。",
                },
            ],
        },
        {
            "id": "cloud",
            "title": "云启合同",
            "messages": [
                {
                    "time": "2026-08-11 14:00:00",
                    "sender": "he",
                    "content": "云启合同已确认88万，SLA从4小时改为2小时。",
                },
                {
                    "time": "2026-08-11 14:20:00",
                    "sender": "zheng",
                    "content": "升级项写入合同附件，今天同步法务。",
                },
                {
                    "time": "2026-08-11 14:40:00",
                    "sender": "wang",
                    "content": "已确认服务时间，原厂支持保留。",
                    "reply": True,
                },
            ],
        },
    ],
    "project": [
        {
            "id": "portal",
            "title": "客户门户交付",
            "messages": [
                {
                    "time": "2026-08-04 09:00:00",
                    "sender": "zhao",
                    "content": "客户门户9月10日上线，后端8月25日前交付，前端8月28日联调。",
                },
                {
                    "time": "2026-08-04 09:30:00",
                    "sender": "qian",
                    "content": "后端接口排期已确认，风险点集中在数据迁移。",
                    "reply": True,
                },
                {
                    "time": "2026-08-04 10:00:00",
                    "sender": "sun",
                    "content": "前端组件今天起联调环境准备。",
                },
            ],
        },
        {
            "id": "error",
            "title": "错误码5002",
            "messages": [
                {
                    "time": "2026-08-05 15:00:00",
                    "sender": "sun",
                    "content": "错误码5002已定位，根因是签名验签参数顺序。",
                },
                {
                    "time": "2026-08-05 15:20:00",
                    "sender": "zhao",
                    "content": "修复后压测QPS500下99%延迟120ms。",
                    "reply": True,
                },
                {
                    "time": "2026-08-05 16:00:00",
                    "sender": "qian",
                    "content": "已灰度给3个内部客户观察。",
                },
            ],
        },
        {
            "id": "report",
            "title": "报表导出性能",
            "messages": [
                {
                    "time": "2026-08-10 10:00:00",
                    "sender": "qian",
                    "content": "报表导出慢已修复，根因是大数据量排序未走索引。",
                },
                {
                    "time": "2026-08-10 10:30:00",
                    "sender": "zhao",
                    "content": "修复后P95从8秒降到1.2秒。",
                    "reply": True,
                },
                {
                    "time": "2026-08-10 11:00:00",
                    "sender": "sun",
                    "content": "已补充回归用例，监控指标同步。",
                },
            ],
        },
        {
            "id": "release",
            "title": "V0.8.0发布",
            "messages": [
                {
                    "time": "2026-08-12 18:00:00",
                    "sender": "zhao",
                    "content": "V0.8.0计划8月13日22:00发布，灰度5%。",
                },
                {
                    "time": "2026-08-12 18:20:00",
                    "sender": "qian",
                    "content": "发布前安全检查已完成。",
                },
                {
                    "time": "2026-08-12 18:40:00",
                    "sender": "sun",
                    "content": "回滚脚本已验证，发布窗口保持不变。",
                },
            ],
        },
    ],
    "ops": [
        {
            "id": "redis",
            "title": "Redis告警",
            "messages": [
                {
                    "time": "2026-08-04 08:50:00",
                    "sender": "gao",
                    "content": "Redis内存使用率85%告警，先临时扩容2G。",
                },
                {
                    "time": "2026-08-04 09:30:00",
                    "sender": "liu",
                    "content": "扩容后P95下降40%，继续优化大Key缓存。",
                },
                {
                    "time": "2026-08-04 10:00:00",
                    "sender": "gao",
                    "content": "今日复盘后给出长期方案。",
                    "reply": True,
                },
            ],
        },
        {
            "id": "ci",
            "title": "CI构建优化",
            "messages": [
                {
                    "time": "2026-08-06 11:00:00",
                    "sender": "liu",
                    "content": "CI构建从12分钟降到4分钟，采用分层缓存。",
                },
                {
                    "time": "2026-08-06 11:15:00",
                    "sender": "gao",
                    "content": "流水线已确认稳定，缓存清理脚本本月执行一次。",
                },
                {
                    "time": "2026-08-06 11:30:00",
                    "sender": "chen",
                    "content": "构建失败率从6%降到2%。",
                    "reply": True,
                },
            ],
        },
        {
            "id": "patch",
            "title": "安全补丁",
            "messages": [
                {
                    "time": "2026-08-11 15:00:00",
                    "sender": "gao",
                    "content": "安全补丁14台已完成11台。",
                },
                {
                    "time": "2026-08-11 15:10:00",
                    "sender": "chen",
                    "content": "剩余3台8月14日夜间执行，先停应用再打补丁。",
                    "reply": True,
                },
                {
                    "time": "2026-08-11 15:30:00",
                    "sender": "liu",
                    "content": "值班表已确认，凌晨2点前完成。",
                },
            ],
        },
        {
            "id": "perm",
            "title": "权限复核",
            "messages": [
                {
                    "time": "2026-08-13 09:00:00",
                    "sender": "chen",
                    "content": "权限复核发现17个离职账号未回收，涉及9个系统。",
                },
                {
                    "time": "2026-08-13 09:20:00",
                    "sender": "gao",
                    "content": "今天按系统owner下发回收清单。",
                    "reply": True,
                },
                {
                    "time": "2026-08-13 09:40:00",
                    "sender": "liu",
                    "content": "优先回收财务系统和代码仓库。",
                },
            ],
        },
    ],
}


_FILLER_DATES = ("08-12", "08-13")


def _filler_topics(chat_key: str) -> list[dict[str, Any]]:
    if chat_key not in PEOPLE or not PEOPLE[chat_key]:
        return []
    senders = list(PEOPLE[chat_key])
    topics: list[dict[str, Any]] = []
    for date in _FILLER_DATES:
        topics.append(
            {
                "id": f"sync_{date.replace('-', '')}",
                "title": f"{date} 日常同步",
                "messages": [
                    {
                        "time": f"2026-{date} 09:30:00",
                        "sender": senders[0],
                        "content": "今日开工同步：按昨日结论推进，暂无新增阻塞。",
                    },
                    {
                        "time": f"2026-{date} 10:15:00",
                        "sender": senders[1 % len(senders)],
                        "content": "收到，我负责跟进今日事项，下午同步进度。",
                        "reply": True,
                    },
                    {
                        "time": f"2026-{date} 18:05:00",
                        "sender": senders[2 % len(senders)],
                        "content": "今日已更新进度与风险到共享文档。",
                    },
                ],
            }
        )
    return topics


def message_id_for(chat_key: str, topic_id: str, index: int) -> str:
    return f"syn_{chat_key}_{topic_id}_{index:02d}"


def build_messages(limit: int | None = None) -> list[dict[str, Any]]:
    """Build deterministic messages in chat/topic order.

    ``limit`` caps the total message count and is useful for quick eval smoke
    runs; the default (``None`` / ``0``) builds the full corpus.
    """
    limit = 0 if limit is None else int(limit)
    result: list[dict[str, Any]] = []
    for chat in CHAT_DEFS:
        chat_key = str(chat["key"])
        chat_id = str(chat["chat_id"])
        chat_people = PEOPLE.get(chat_key, {})
        position = 0
        topics = list(TOPIC_DEFS.get(chat_key, [])) + _filler_topics(chat_key)
        for topic in topics:
            previous_id: str | None = None
            topic_id = str(topic["id"])
            for index, item in enumerate(topic.get("messages", []), start=1):
                position += 1
                sender_key = str(item["sender"])
                message_id = message_id_for(chat_key, topic_id, index)
                payload: dict[str, Any] = {
                    "message_id": message_id,
                    "chat_id": chat_id,
                    "msg_type": "text",
                    "content": str(item["content"]),
                    "create_time": str(item["time"]),
                    "message_position": position,
                    "sender": {
                        "id": f"ou_syn_{chat_key}_{sender_key}",
                        "name": chat_people.get(sender_key, sender_key),
                    },
                    "thread_id": f"th_{chat_key}_{topic_id}",
                }
                if item.get("reply") and previous_id:
                    payload["reply"] = {"message_id": previous_id}
                result.append(payload)
                previous_id = message_id
                if limit and len(result) >= limit:
                    return result
    return result


TOTAL_MESSAGES = len(build_messages())

GOLDEN_REF_SPECS: tuple[tuple[str, str, int], ...] = (
    ("hr", "hc", 1),
    ("hr", "zhangwei", 1),
    ("hr", "performance", 1),
    ("hr", "liting", 2),
    ("hr", "attendance", 1),
    ("hr", "attendance", 2),
    ("risk", "huachen", 1),
    ("risk", "framework", 1),
    ("risk", "jiaxing", 1),
    ("risk", "jiaxing", 2),
    ("risk", "seal", 1),
    ("finance", "budget", 1),
    ("finance", "reimburse", 1),
    ("finance", "q3", 1),
    ("finance", "reconcile", 1),
    ("procure", "gpu", 1),
    ("procure", "quote", 1),
    ("procure", "quote", 2),
    ("procure", "line", 1),
    ("procure", "order", 2),
    ("procure", "cloud", 1),
    ("project", "portal", 1),
    ("project", "error", 1),
    ("project", "report", 2),
    ("project", "release", 1),
    ("ops", "redis", 2),
    ("ops", "ci", 1),
    ("ops", "patch", 2),
    ("ops", "perm", 1),
    ("hr", "zhangwei", 3),
    ("hr", "liting", 3),
    ("risk", "framework", 1),
    ("risk", "seal", 2),
)

GOLDEN_MESSAGE_IDS = tuple(
    message_id_for(*spec) for spec in GOLDEN_REF_SPECS
)


def seed_database(
    db: Database,
    limit: int | None = None,
    reset_derived: bool = True,
) -> dict[str, Any]:
    """Seed chats/messages and optionally rebuild all derived layers."""
    db.init()
    for chat in CHAT_DEFS:
        db.upsert_chat({k: v for k, v in chat.items() if k != "key"})
    messages = build_messages(limit)
    for message in messages:
        db.upsert_message(message)

    index: dict[str, Any] | None = None
    summary: dict[str, Any] | None = None
    if reset_derived:
        index = IndexRepository(db).rebuild()
        summary = SummaryRepository(db, Settings()).rebuild(mode="rule")
    return {
        "ok": True,
        "chats_seeded": len(CHAT_DEFS),
        "messages_seeded": len(messages),
        "limit": limit,
        "reset_derived": bool(reset_derived),
        "index": index,
        "summary": summary,
    }


def synthetic_status(db: Database) -> dict[str, Any]:
    """Report whether the golden synthetic corpus is present and indexed."""
    db.init()
    per_chat: list[dict[str, Any]] = []
    total = 0
    for chat in CHAT_DEFS:
        chat_id = str(chat["chat_id"])
        count = db.count_messages(chat_id)
        total += count
        per_chat.append(
            {
                "chat_id": chat_id,
                "name": chat["name"],
                "messages": count,
            }
        )
    missing = [
        message_id
        for message_id in GOLDEN_MESSAGE_IDS
        if not db.message_exists(message_id)
    ]
    return {
        "synthetic": True,
        "chats": per_chat,
        "messages": total,
        "golden_references": len(GOLDEN_MESSAGE_IDS),
        "missing_golden_references": missing,
        "ready": total >= 100 and not missing,
        "index": IndexRepository(db).status(),
        "summary": SummaryRepository(db, Settings()).status(),
    }
