from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from feishu_agent.config import _load_dotenv


class DotenvTests(unittest.TestCase):
    def test_loads_without_overriding_existing_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "LARKNOVA_TEST_A=1\nLARKNOVA_TEST_B=\"hello world\"\n"
                "LARKNOVA_TEST_C=keep\n# comment\n",
                encoding="utf-8",
            )
            os.environ["LARKNOVA_TEST_C"] = "existing"
            try:
                _load_dotenv(env_file)
                self.assertEqual(os.environ.get("LARKNOVA_TEST_A"), "1")
                self.assertEqual(os.environ.get("LARKNOVA_TEST_B"), "hello world")
                self.assertEqual(os.environ.get("LARKNOVA_TEST_C"), "existing")
            finally:
                for key in ("LARKNOVA_TEST_A", "LARKNOVA_TEST_B", "LARKNOVA_TEST_C"):
                    os.environ.pop(key, None)