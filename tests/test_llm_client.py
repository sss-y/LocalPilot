import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import llm_client


class FakeLLMConnection:
    def __init__(self, *, apibase, apikey, model, timeout):
        self.apibase = apibase
        self.apikey = apikey
        self.model = model
        self.timeout = timeout

    def chat(self, messages):
        last_user_text = messages[-1]["content"]
        return {
            "status": "ok",
            "provider": self.apibase,
            "model": self.model,
            "reply": f"mock-reply:{last_user_text}",
        }


def build_mock_connection(config):
    return FakeLLMConnection(
        apibase=config["apibase"],
        apikey=config["apikey"],
        model=config["model"],
        timeout=config.get("read_timeout", 60),
    )


MOCK_MODEL_CONFIG = {
    "name": "mock-provider",
    "apikey": "mock-api-key",
    "apibase": "https://mock.example.com/v1",
    "model": "mock-model-v1",
    "read_timeout": 30,
}

MOCK_MESSAGES = [{"role": "user", "content": "ping"}]


class LLMClientConfigTests(unittest.TestCase):
    def setUp(self):
        self._reset_module_state()

    def tearDown(self):
        self._reset_module_state()

    def _reset_module_state(self):
        llm_client._mykeys_cache = None
        llm_client._mykeys_source_path = None
        llm_client._mykeys_mtime = None
        llm_client._langfuse_tracing_active = False

    def test_loads_python_config(self):
        config = llm_client.reload_mykeys(force=True)

        self.assertIn("native_claude_dash_config", config)
        model_config = config["native_claude_dash_config"]
        self.assertEqual(model_config["model"], "deepseek-v4-pro")
        self.assertIn("apibase", model_config)

    def test_lazy_mykeys_access_returns_loaded_config(self):
        config = llm_client.mykeys

        self.assertIsInstance(config, dict)
        self.assertIn("native_claude_dash_config", config)

    def test_reload_uses_updated_python_file_after_mtime_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "mykey.py"
            config_path.write_text(
                "demo_config = {'model': 'demo-v1', 'apibase': 'https://example.com', 'apikey': 'k1'}\n",
                encoding="utf-8",
            )

            with patch.object(llm_client, "_MYKEY_PY_PATH", config_path), patch.object(
                llm_client, "_MYKEY_JSON_PATH", tmp_path / "missing.json"
            ):
                first = llm_client.reload_mykeys(force=True)
                self.assertEqual(first["demo_config"]["model"], "demo-v1")

                config_path.write_text(
                    "demo_config = {'model': 'demo-v2', 'apibase': 'https://example.com', 'apikey': 'k2'}\n",
                    encoding="utf-8",
                )

                second = llm_client.reload_mykeys(force=True)
                self.assertEqual(second["demo_config"]["model"], "demo-v2")
                self.assertEqual(second["demo_config"]["apikey"], "k2")

    def test_langfuse_config_enables_tracing_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_path = tmp_path / "mykey.py"
            config_path.write_text(
                "langfuse_config = {'enabled': True}\n"
                "demo_config = {'model': 'demo-v1', 'apibase': 'https://example.com', 'apikey': 'k1'}\n",
                encoding="utf-8",
            )

            with patch.object(llm_client, "_MYKEY_PY_PATH", config_path), patch.object(
                llm_client, "_MYKEY_JSON_PATH", tmp_path / "missing.json"
            ):
                llm_client.reload_mykeys(force=True)
                self.assertTrue(llm_client.langfuse_tracing_active)

    def test_loaded_config_can_drive_mock_connection_and_receive_reply(self):
        config = llm_client.reload_mykeys(force=True)
        model_config = config["native_claude_dash_config"]
        fake_conn = build_mock_connection(model_config)

        response = fake_conn.chat(
            [{"role": "user", "content": "hello from test"}]
        )

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["model"], model_config["model"])
        self.assertEqual(response["provider"], model_config["apibase"])
        self.assertEqual(response["reply"], "mock-reply:hello from test")

    def test_mock_config_can_receive_mock_reply(self):
        fake_conn = build_mock_connection(MOCK_MODEL_CONFIG)

        response = fake_conn.chat(MOCK_MESSAGES)

        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["provider"], MOCK_MODEL_CONFIG["apibase"])
        self.assertEqual(response["model"], MOCK_MODEL_CONFIG["model"])
        self.assertEqual(response["reply"], "mock-reply:ping")


if __name__ == "__main__":
    unittest.main()
