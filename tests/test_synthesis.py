from __future__ import annotations

import unittest

from feishu_agent.agent.synthesis import (
    synthesize_answer,
    synthesize_answer_with_evidence,
    wants_concise_answer,
)


def _item(
    excerpt: str,
    message_id: str = "m1",
    create_time: str = "2026-08-19 07:10",
) -> dict[str, str]:
    return {
        "message_id": message_id,
        "chat_id": "oc_a",
        "chat_name": "知行良知总群",
        "sender_name": "大管家",
        "create_time": create_time,
        "excerpt": excerpt,
    }


def _lunch_items() -> list[dict[str, str]]:
    """复刻「什么时候陪罗总吃饭」的完整消息链。"""
    return [
        _item("老A/小狐狸分享垫资条款等", "om-low", create_time="2026-08-13 17:06"),
        _item(
            "通知：明天中午 11:00-13:00 在办公室陪刘琴吃饭，王军陪同",
            "om-first",
            create_time="2026-08-13 17:19",
        ),
        _item(
            "更正，明天中午 11:00-13:00 是陪宜宾罗总吃饭",
            "om-correct1",
            create_time="2026-08-13 17:22",
        ),
        _item(
            "只有董事长和罗总俩人用餐吗，中等餐标吗",
            "om-ask",
            create_time="2026-08-13 17:24",
        ),
        _item(
            "又更正，改为陪宜宾罗总吃饭，王军陪同，刘琴取消",
            "om-correct2",
            create_time="2026-08-13 17:27",
        ),
        _item(
            "最终版：明天中午 11:00-13:00 陪宜宾罗总吃饭，王军陪同，刘琴负责现场保障",
            "om-final",
            create_time="2026-08-13 17:28",
        ),
        _item("订餐标准补充", "om-meal", create_time="2026-08-13 17:28"),
        _item("大管家 bot 问刘忠培要行程模板", "om-template", create_time="2026-08-13 17:30"),
        _item(
            "前几条关于明天的通知作废，具体安排以飞书日历为准",
            "om-void",
            create_time="2026-08-13 17:33",
        ),
        _item("没查到，建议问行政/接待", "om-nobody", create_time="2026-08-13 17:35"),
    ]


class SynthesisTests(unittest.TestCase):
    def test_extracts_short_answer_from_quoted_evidence(self):
        items = [
            _item("抢业务，抓回款，控成本，提利润。", "m-slogan"),
            _item(
                "老板说：'有——「你再想想」馅的。'",
                "m-joke",
            ),
        ]

        answer = synthesize_answer(
            "早餐包子什么馅的，只告诉我包子馅是什么，不需要其他信息",
            items,
        )

        self.assertEqual(answer, "早餐包子是「你再想想」馅的。")
        self.assertTrue(wants_concise_answer("只告诉我包子馅是什么"))

    def test_normal_question_returns_direct_answer_without_evidence_dump(self):
        items = [
            _item("项目预算已确认，采购清单计划明天提交", f"m{i}")
            for i in range(1, 6)
        ]

        answer = synthesize_answer("项目预算怎么安排的？", items)

        self.assertIn("预算", answer)
        self.assertIn("已确认", answer)
        self.assertNotIn("根据本地消息检索", answer)

    def test_concise_without_extraction_uses_single_preview(self):
        answer = synthesize_answer(
            "只告诉我这条消息说了什么",
            [_item("第一条消息内容", "m1"), _item("第二条消息内容", "m2")],
        )

        self.assertEqual(answer.count("\n"), 0)
        self.assertIn("第一条消息内容", answer)
        self.assertNotIn("根据本地消息检索", answer)

    def test_time_question_reads_evidence_and_notices_supersede(self):
        result = synthesize_answer_with_evidence(
            "什么时候陪罗总吃饭",
            _lunch_items(),
        )
        answer = result.answer

        self.assertIn("罗总", answer)
        self.assertIn("明天", answer)
        self.assertIn("11:00", answer)
        self.assertIn("作废", answer)
        self.assertIn("飞书日历", answer)
        self.assertNotIn("根据本地消息检索", answer)
        self.assertIn("om-final", result.cited_item_ids)
        self.assertIn("om-void", result.cited_item_ids)
        self.assertNotIn("om-first", result.cited_item_ids)

    def test_person_question_extracts_names_from_evidence(self):
        result = synthesize_answer_with_evidence(
            "陪罗总吃饭谁陪同",
            _lunch_items(),
        )

        self.assertIn("王军", result.answer)
        self.assertIn("om-final", result.cited_item_ids)

    def test_amount_question_extracts_value(self):
        items = [
            _item("采购预算约 12.5 万元，下周走审批", "m-amount"),
        ]

        result = synthesize_answer_with_evidence("采购预算是多少", items)

        self.assertIn("12.5 万元", result.answer)
        self.assertNotIn("根据本地消息检索", result.answer)
        self.assertEqual(result.cited_item_ids, ["m-amount"])


if __name__ == "__main__":
    unittest.main()
