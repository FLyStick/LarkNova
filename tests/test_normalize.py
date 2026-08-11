from __future__ import annotations

import unittest

from feishu_agent.normalize import message_digest, normalize_message


class NormalizeTests(unittest.TestCase):
    def test_post_with_markdown_image(self):
        msg = {
            "message_id": "m1",
            "msg_type": "post",
            "content": "你好\n![Image](https://example.com/a.png)\n正文",
        }
        result = normalize_message(msg)
        self.assertIn("[图片: https://example.com/a.png]", result["content_normalized"])
        self.assertNotIn("![Image]", result["content_normalized"])
        self.assertIsNone(result["normalize_error"])

    def test_interactive_html_stripped(self):
        msg = {
            "message_id": "m2",
            "msg_type": "interactive",
            "content": "<card><clickable>**重点**</clickable><footer>来源A</footer></card>",
        }
        result = normalize_message(msg)
        self.assertIn("重点", result["content_normalized"])
        self.assertIn("来源A", result["content_normalized"])
        self.assertNotIn("<", result["content_normalized"])

    def test_dict_content_collects_text_and_image_tag(self):
        msg = {
            "message_id": "m3",
            "msg_type": "post",
            "content": {
                "title": "标题",
                "elements": [{"tag": "img"}, {"text": "正文细节"}],
            },
        }
        result = normalize_message(msg)
        text = result["content_normalized"]
        self.assertIn("标题", text)
        self.assertIn("正文细节", text)
        self.assertIn("[图片]", text)

    def test_image_marker_normalized(self):
        result = normalize_message(
            {
                "message_id": "m4",
                "msg_type": "image",
                "content": "[Image: img_v3_abc123]",
            }
        )
        self.assertEqual(result["content_normalized"], "[图片: img_v3_abc123]")

    def test_merge_forward_stripped(self):
        result = normalize_message(
            {
                "message_id": "m5",
                "msg_type": "merge_forward",
                "content": "<forwarded_messages>上层决策</forwarded_messages>",
            }
        )
        self.assertEqual(result["content_normalized"], "上层决策")

    def test_digest_stable_and_sensitive_to_content(self):
        first = {"msg_type": "text", "content": "a", "deleted": False}
        second = {"content": "a", "msg_type": "text", "deleted": False}
        third = {"msg_type": "text", "content": "b", "deleted": False}
        self.assertEqual(message_digest(first), message_digest(second))
        self.assertNotEqual(message_digest(first), message_digest(third))


if __name__ == "__main__":
    unittest.main()
