from __future__ import annotations

import unittest

from feishu_agent.doctor import run_doctor
from feishu_agent.feishu.client import FeishuError


class FakeClient:
    def __init__(self, chats=None, messages_error=None, messages=None):
        self.chats = chats or []
        self.messages_error = messages_error
        self.messages = messages or []

    def list_chats(self, identity=None):
        return [dict(chat) for chat in self.chats]

    def list_messages(self, chat_id, identity=None, order="asc", page_size=50, start=None, end=None, page_all=True):
        if self.messages_error is not None:
            raise self.messages_error
        return [dict(message) for message in self.messages]


class DoctorTests(unittest.TestCase):
    def test_reports_230027_and_fix(self):
        client = FakeClient(
            chats=[{"chat_id": "oc_a", "name": "A", "external": 0}],
            messages_error=FeishuError(230027, "permission denied", {"error": {"code": 230027}}),
        )
        result = run_doctor(client, identity="bot")
        self.assertFalse(result["ok"])
        self.assertEqual(result["blockers"][0]["stage"], "message_list")
        self.assertEqual(result["read_check"]["code"], 230027)
        self.assertTrue(any("im:message:readonly" in fix for fix in result["fixes"]))

    def test_healthy_identity(self):
        client = FakeClient(
            chats=[{"chat_id": "oc_a", "name": "A", "external": 0}],
            messages=[],
        )
        result = run_doctor(client, identity="user")
        self.assertTrue(result["ok"])
        self.assertTrue(result["read_check"]["ok"])

    def test_external_chat_skipped(self):
        client = FakeClient(chats=[{"chat_id": "oc_a", "name": "External", "external": 1}])
        result = run_doctor(client, identity="bot")
        self.assertTrue(result["ok"])
        self.assertEqual([item["reason"] for item in result["chats_skipped"]], ["external_chat"])

    def test_whitelist_missing_reported(self):
        client = FakeClient(chats=[])
        result = run_doctor(client, identity="bot", allowed_chat_ids={"oc_missing"})
        self.assertEqual(result["whitelist_missing"], ["oc_missing"])


if __name__ == "__main__":
    unittest.main()