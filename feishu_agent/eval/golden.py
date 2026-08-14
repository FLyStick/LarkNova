"""M5 简历评估黄金用例。

每个用例都引用合成语料中的确定性消息（``feishu_agent/synthetic``），
生产库重建后重新执行 seed 即可复现同一组用例。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GoldenCase:
    """一个黄金用例：问题、答案关键词/引用与评估意图的组合。"""

    id: str
    question: str
    chat_ids: list[str] = field(default_factory=list)
    expected_keywords: tuple[str, ...] = ()
    reference_ids: tuple[str, ...] = ()
    allow_refused: bool = False
    type: str = "search"

    def to_dict(self) -> dict[str, Any]:
        """把用例转换为可 JSON 持久化的字典。"""
        return {
            "id": self.id,
            "question": self.question,
            "chat_ids": list(self.chat_ids),
            "expected_keywords": list(self.expected_keywords),
            "reference_ids": list(self.reference_ids),
            "allow_refused": self.allow_refused,
            "type": self.type,
        }


def _ref(chat: str, topic: str, index: int) -> str:
    """按合成语料的命名规约生成确定性引用消息 id。"""
    return f"syn_{chat}_{topic}_{index:02d}"


GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        id="hr_hc",
        question="人事群新增HC计划怎么安排？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("8个HC",),
        reference_ids=(_ref("hr", "hc", 1),),
        type="search",
    ),
    GoldenCase(
        id="hr_hc_tech",
        question="研发HC的重点岗位有哪些？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("图像算法", "前端工程"),
        reference_ids=(_ref("hr", "hc", 2),),
        type="search",
    ),
    GoldenCase(
        id="hr_offer",
        question="张伟复试后的定级和薪酬建议是什么？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("P6", "32K"),
        reference_ids=(_ref("hr", "zhangwei", 1),),
        type="search",
    ),
    GoldenCase(
        id="hr_performance",
        question="绩效申诉材料截止是什么时候？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("8月10日", "18:00"),
        reference_ids=(_ref("hr", "performance", 1),),
        type="search",
    ),
    GoldenCase(
        id="hr_transfer",
        question="李婷离职的交接人是谁？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("周琳", "交接清单"),
        reference_ids=(_ref("hr", "liting", 2),),
        type="search",
    ),
    GoldenCase(
        id="hr_attendance",
        question="8月考勤补卡截止日期是什么？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("8月14日",),
        reference_ids=(_ref("hr", "attendance", 2),),
        type="search",
    ),
    GoldenCase(
        id="risk_dd",
        question="华辰科技尽调结论如何？",
        chat_ids=["oc_syn_risk"],
        expected_keywords=("实缴资本", "2000万"),
        reference_ids=(_ref("risk", "huachen", 1),),
        type="search",
    ),
    GoldenCase(
        id="risk_framework",
        question="华辰框架合同的授信和付款条件是什么？",
        chat_ids=["oc_syn_risk"],
        expected_keywords=("500万", "90天"),
        reference_ids=(_ref("risk", "framework", 1),),
        type="search",
    ),
    GoldenCase(
        id="risk_jiaxing",
        question="嘉兴供应商的风险怎么处理？",
        chat_ids=["oc_syn_risk"],
        expected_keywords=("暂缓付款", "8月14日"),
        reference_ids=(_ref("risk", "jiaxing", 2),),
        type="search",
    ),
    GoldenCase(
        id="risk_seal",
        question="用印申请的双人复核人是谁？",
        chat_ids=["oc_syn_risk"],
        expected_keywords=("陈晨", "孙悦"),
        reference_ids=(_ref("risk", "seal", 2),),
        type="search",
    ),
    GoldenCase(
        id="finance_budget",
        question="8月预算总额和研发预算分别是多少？",
        chat_ids=["oc_syn_finance"],
        expected_keywords=("1260万", "680万"),
        reference_ids=(_ref("finance", "budget", 1),),
        type="search",
    ),
    GoldenCase(
        id="finance_invoice",
        question="7月还有多少笔报销未开票？",
        chat_ids=["oc_syn_finance"],
        expected_keywords=("23笔", "8月14日"),
        reference_ids=(_ref("finance", "reimburse", 1),),
        type="search",
    ),
    GoldenCase(
        id="finance_q3",
        question="Q3融资预计什么时候入账？",
        chat_ids=["oc_syn_finance"],
        expected_keywords=("8月14日", "300万"),
        reference_ids=(_ref("finance", "q3", 1),),
        type="search",
    ),
    GoldenCase(
        id="finance_reconcile",
        question="银行对账未达账项金额是多少？",
        chat_ids=["oc_syn_finance"],
        expected_keywords=("18.6万",),
        reference_ids=(_ref("finance", "reconcile", 1),),
        type="search",
    ),
    GoldenCase(
        id="procure_gpu",
        question="GPU服务器采购预算和配置是什么？",
        chat_ids=["oc_syn_procure"],
        expected_keywords=("96万", "A100"),
        reference_ids=(_ref("procure", "gpu", 1),),
        type="search",
    ),
    GoldenCase(
        id="procure_quote",
        question="GPU报价中云启多少钱？",
        chat_ids=["oc_syn_procure"],
        expected_keywords=("88万", "云启"),
        reference_ids=(_ref("procure", "quote", 2),),
        type="search",
    ),
    GoldenCase(
        id="procure_line",
        question="网络专线中选供应商和合同金额是什么？",
        chat_ids=["oc_syn_procure"],
        expected_keywords=("华辰", "156万"),
        reference_ids=(_ref("procure", "line", 1),),
        type="search",
    ),
    GoldenCase(
        id="procure_order",
        question="ORD-2026-0811的验收人是谁？",
        chat_ids=["oc_syn_procure"],
        expected_keywords=("姚明",),
        reference_ids=(_ref("procure", "order", 2),),
        type="search",
    ),
    GoldenCase(
        id="procure_sla",
        question="云启合同的SLA调整成多少？",
        chat_ids=["oc_syn_procure"],
        expected_keywords=("2小时", "88万"),
        reference_ids=(_ref("procure", "cloud", 1),),
        type="search",
    ),
    GoldenCase(
        id="project_portal",
        question="客户门户什么时候上线？",
        chat_ids=["oc_syn_project"],
        expected_keywords=("9月10日", "8月25日"),
        reference_ids=(_ref("project", "portal", 1),),
        type="search",
    ),
    GoldenCase(
        id="project_risk",
        question="客户门户的风险点集中在哪里？",
        chat_ids=["oc_syn_project"],
        expected_keywords=("数据迁移",),
        reference_ids=(_ref("project", "portal", 2),),
        type="search",
    ),
    GoldenCase(
        id="project_error",
        question="错误码5002的根因是什么？",
        chat_ids=["oc_syn_project"],
        expected_keywords=("签名验签参数顺序",),
        reference_ids=(_ref("project", "error", 1),),
        type="search",
    ),
    GoldenCase(
        id="project_report",
        question="报表导出优化后P95是多少？",
        chat_ids=["oc_syn_project"],
        expected_keywords=("1.2秒", "P95"),
        reference_ids=(_ref("project", "report", 2),),
        type="search",
    ),
    GoldenCase(
        id="project_release",
        question="V0.8.0发布灰度比例和时间是什么？",
        chat_ids=["oc_syn_project"],
        expected_keywords=("5%", "8月13日22:00"),
        reference_ids=(_ref("project", "release", 1),),
        type="search",
    ),
    GoldenCase(
        id="ops_redis",
        question="Redis告警后临时扩容多少？",
        chat_ids=["oc_syn_ops"],
        expected_keywords=("2G", "85%"),
        reference_ids=(_ref("ops", "redis", 1),),
        type="search",
    ),
    GoldenCase(
        id="ops_ci",
        question="CI构建优化后耗时多少？",
        chat_ids=["oc_syn_ops"],
        expected_keywords=("4分钟", "12分钟"),
        reference_ids=(_ref("ops", "ci", 1),),
        type="search",
    ),
    GoldenCase(
        id="ops_patch",
        question="还有几台服务器待打补丁？",
        chat_ids=["oc_syn_ops"],
        expected_keywords=("3台", "8月14日"),
        reference_ids=(_ref("ops", "patch", 2),),
        type="search",
    ),
    GoldenCase(
        id="ops_perm",
        question="权限复核发现多少个离职账号未回收？",
        chat_ids=["oc_syn_ops"],
        expected_keywords=("17个", "9个系统"),
        reference_ids=(_ref("ops", "perm", 1),),
        type="search",
    ),
    GoldenCase(
        id="hr_summary",
        question="人事群最近有什么结论和待办？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("结论", "待办"),
        reference_ids=(_ref("hr", "hc", 1),),
        type="summary",
    ),
    GoldenCase(
        id="finance_summary",
        question="财务群待办有哪些？",
        chat_ids=["oc_syn_finance"],
        expected_keywords=("结论", "待办"),
        reference_ids=(_ref("finance", "budget", 1),),
        type="summary",
    ),
    GoldenCase(
        id="risk_summary",
        question="风控群最近发生了什么？",
        chat_ids=["oc_syn_risk"],
        expected_keywords=("结论", "待办"),
        reference_ids=(_ref("risk", "huachen", 1),),
        type="summary",
    ),
    GoldenCase(
        id="hr_recent",
        question="人事群今天有什么新消息？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("今日开工同步",),
        reference_ids=(_ref("hr", "sync_0813", 1),),
        type="recent",
    ),
    GoldenCase(
        id="ops_recent",
        question="运维群最近在推进什么？",
        chat_ids=["oc_syn_ops"],
        expected_keywords=("权限复核",),
        reference_ids=(_ref("ops", "perm", 1),),
        type="recent",
    ),
    GoldenCase(
        id="project_recent",
        question="项目群今天有什么同步？",
        chat_ids=["oc_syn_project"],
        expected_keywords=("今日开工同步",),
        reference_ids=(_ref("project", "sync_0813", 1),),
        type="recent",
    ),
    GoldenCase(
        id="graph_zhangwei",
        question="图谱实体“张伟”有哪些关联？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("张伟", "关联实体"),
        reference_ids=(_ref("hr", "zhangwei", 1),),
        type="graph",
    ),
    GoldenCase(
        id="graph_qian",
        question="图谱实体“钱枫”有哪些关联？",
        chat_ids=["oc_syn_project"],
        expected_keywords=("钱枫", "关联实体"),
        reference_ids=(_ref("project", "portal", 2),),
        type="graph",
    ),
    GoldenCase(
        id="graph_sun",
        question="图谱实体“孙悦”有哪些关联？",
        chat_ids=["oc_syn_risk"],
        expected_keywords=("孙悦", "关联实体"),
        reference_ids=(_ref("risk", "huachen", 3),),
        type="graph",
    ),
    GoldenCase(
        id="graph_hr_chat",
        question="图谱实体“人事群”有哪些关联？",
        chat_ids=["oc_syn_hr"],
        expected_keywords=("人事群", "关联实体"),
        reference_ids=(_ref("hr", "hc", 1),),
        type="graph",
    ),
    GoldenCase(
        id="graph_finance_chat",
        question="图谱实体“财务群”有哪些关联？",
        chat_ids=["oc_syn_finance"],
        expected_keywords=("财务群", "关联实体"),
        reference_ids=(_ref("finance", "budget", 1),),
        type="graph",
    ),
    GoldenCase(
        id="graph_gao",
        question="图谱实体“高远”有哪些关联？",
        chat_ids=["oc_syn_ops"],
        expected_keywords=("高远", "关联实体"),
        reference_ids=(_ref("ops", "redis", 1),),
        type="graph",
    ),
    GoldenCase(
        id="refuse_empty",
        question="实测群里最近有什么结论？",
        chat_ids=["oc_syn_qa_empty"],
        allow_refused=True,
        type="refusal",
    ),
)


def load_golden(path: str | Path | None = None) -> list[GoldenCase]:
    """加载黄金用例；`None` 时返回内置语料。"""
    if path is None:
        return list(GOLDEN_CASES)
    # 外部文件兼容 `{"cases": [...]}` 的直接列表两种结构。
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cases") or []
    if not isinstance(data, list):
        raise ValueError("golden file must contain a cases list")
    # 仅接受字典项，避免脏数据进入评估流程。
    return [_case_from_dict(item) for item in data if isinstance(item, dict)]


def dump_golden(path: str | Path) -> str:
    """把内置黄金语料写成可版本化的 JSON 文件。"""
    target = Path(path)
    # 目录不存在时先创建，保证写入路径始终可用。
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"cases": [case.to_dict() for case in GOLDEN_CASES]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return str(target)


def _case_from_dict(data: dict[str, Any]) -> GoldenCase:
    """从 JSON 字典还原用例，并兼容旧的键名写法。"""
    return GoldenCase(
        id=str(data.get("id") or data.get("case_id") or ""),
        question=str(data.get("question") or ""),
        chat_ids=[
            str(item)
            for item in (data.get("chat_ids") or data.get("chats") or [])
            if str(item).strip()
        ],
        expected_keywords=tuple(
            str(item)
            for item in (data.get("expected_keywords") or data.get("keywords") or [])
        ),
        reference_ids=tuple(
            str(item)
            for item in (data.get("reference_ids") or [])
            if str(item).strip()
        ),
        allow_refused=bool(data.get("allow_refused")),
        type=str(data.get("type") or data.get("case_type") or "search"),
    )
