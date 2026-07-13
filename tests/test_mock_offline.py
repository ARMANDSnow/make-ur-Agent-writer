from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from src import config


ROOT = Path(__file__).resolve().parents[1]


class MockOfflineConfigTests(unittest.TestCase):
    def test_mock_overrides_conflicting_cost_map_setting(self) -> None:
        models = {"default": {"model": "mock"}}
        with patch.dict(
            os.environ,
            {"OPENAI_MODEL": "mock", "LITELLM_LOCAL_MODEL_COST_MAP": "false"},
            clear=True,
        ), patch.object(config, "load_dotenv_if_available"), patch.object(
            config, "load_config", return_value=models
        ):
            self.assertTrue(config.prepare_litellm_environment())
            self.assertEqual(os.environ["LITELLM_LOCAL_MODEL_COST_MAP"], "true")

    def test_default_mock_is_offline_when_model_env_is_absent(self) -> None:
        models = {"default": {"model": "mock"}}
        with patch.dict(os.environ, {}, clear=True), patch.object(
            config, "load_dotenv_if_available"
        ), patch.object(config, "load_config", return_value=models):
            self.assertTrue(config.prepare_litellm_environment())
            self.assertEqual(os.environ["LITELLM_LOCAL_MODEL_COST_MAP"], "true")

    def test_real_model_is_not_forced_to_local_cost_map(self) -> None:
        models = {"default": {"model": "mock"}}
        with patch.dict(
            os.environ, {"OPENAI_MODEL": "deepseek/deepseek-chat"}, clear=True
        ), patch.object(config, "load_dotenv_if_available"), patch.object(
            config, "load_config", return_value=models
        ):
            self.assertFalse(config.prepare_litellm_environment())
            self.assertNotIn("LITELLM_LOCAL_MODEL_COST_MAP", os.environ)


class MockOfflineSubprocessTests(unittest.TestCase):
    def test_main_import_uses_forced_local_map_without_network_attempt(self) -> None:
        code = textwrap.dedent(
            """
            import os
            import sys

            network_events = []

            def audit(event, args):
                if event in {"socket.connect", "socket.getaddrinfo", "urllib.Request"}:
                    network_events.append(event)
                    raise OSError("network disabled by mock-offline regression")

            sys.addaudithook(audit)
            import main
            import tempfile
            from pathlib import Path
            import src.llm_client as client_module
            import src.web.server

            assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "true"
            assert client_module._LITELLM_MOCK_OFFLINE is True
            client_module.append_jsonl = lambda *args, **kwargs: None
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["TIKTOKEN_CACHE_DIR"] = tmp
                client = client_module.LLMClient()
                assert client.is_mock is True
                assert client.complete_text([{"role": "user", "content": "offline probe"}])
                report = main.run_preflight(root=Path(tmp))
                assert report["status"] in {"ok", "warn"}, report
            assert network_events == [], network_events
            """
        )
        env = os.environ.copy()
        env["OPENAI_MODEL"] = "mock"
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = "false"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertNotIn("Failed to fetch remote model cost map", result.stderr)

    def test_direct_drama_module_help_pins_mock_before_project_imports(self) -> None:
        code = textwrap.dedent(
            """
            import os
            import runpy
            import sys

            module = sys.argv[1]
            network_events = []

            def audit(event, args):
                if event in {"socket.connect", "socket.getaddrinfo", "urllib.Request"}:
                    network_events.append(event)
                    raise OSError("network disabled by mock-offline regression")

            sys.addaudithook(audit)
            sys.argv = [module, "--help"]
            try:
                runpy.run_module(module, run_name="__main__")
            except SystemExit as exc:
                assert exc.code == 0, exc.code
            assert os.environ.get("OPENAI_MODEL") == "mock"
            assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "true"
            assert network_events == [], network_events
            """
        )
        for module in ("src.drama_smoke", "src.drama_multimodal_smoke"):
            env = os.environ.copy()
            env["OPENAI_MODEL"] = "deepseek/deepseek-chat"
            env["LITELLM_LOCAL_MODEL_COST_MAP"] = "false"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", code, module],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_programmatic_drama_imports_defer_llm_stack(self) -> None:
        code = textwrap.dedent(
            """
            import importlib
            import os
            import sys

            module = sys.argv[1]
            network_events = []

            def audit(event, args):
                if event in {"socket.connect", "socket.getaddrinfo", "urllib.Request"}:
                    network_events.append(event)
                    raise OSError("network disabled by mock-offline regression")

            sys.addaudithook(audit)
            imported = importlib.import_module(module)
            assert imported is not None
            assert "src.llm_client" not in sys.modules
            assert os.environ.get("OPENAI_MODEL") == "deepseek/deepseek-chat"
            assert network_events == [], network_events
            """
        )
        for module in ("src.drama_smoke", "src.drama_multimodal_smoke"):
            env = os.environ.copy()
            env["OPENAI_MODEL"] = "deepseek/deepseek-chat"
            env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", code, module],
                cwd=ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_missing_litellm_fallback_stays_offline(self) -> None:
        code = textwrap.dedent(
            """
            import builtins
            import os
            import sys

            network_events = []

            def audit(event, args):
                if event in {"socket.connect", "socket.getaddrinfo", "urllib.Request"}:
                    network_events.append(event)
                    raise OSError("network disabled by mock-offline regression")

            original_import = builtins.__import__

            def without_litellm(name, *args, **kwargs):
                if name == "litellm" or name.startswith("litellm."):
                    raise ImportError("simulated missing litellm")
                return original_import(name, *args, **kwargs)

            sys.addaudithook(audit)
            builtins.__import__ = without_litellm
            import src.llm_client as client_module

            assert client_module._LITELLM_MOCK_OFFLINE is True
            assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "true"
            assert client_module.LLMClient().is_mock is True
            assert network_events == [], network_events
            """
        )
        env = os.environ.copy()
        env["OPENAI_MODEL"] = "mock"
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = "false"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_real_subprocess_does_not_receive_project_forced_local_map(self) -> None:
        code = textwrap.dedent(
            """
            import json
            import os
            import tempfile
            from pathlib import Path
            import sys
            import types
            import socket
            import pydantic
            import src.config as config

            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "config").mkdir()
                (root / "config" / "models.yaml").write_text(
                    json.dumps({"default": {"model": "mock"}}), encoding="utf-8"
                )
                config.ROOT = root
                connections = []

                class FakeSocket:
                    def settimeout(self, value):
                        pass
                    def connect(self, address):
                        connections.append(address)
                        raise OSError("offline real-branch probe")
                    def close(self):
                        pass

                socket.socket = lambda *args, **kwargs: FakeSocket()
                fake_litellm = types.ModuleType("litellm")
                fake_litellm.completion = lambda **kwargs: None
                sys.modules["litellm"] = fake_litellm
                import src.llm_client as client_module

                assert client_module._LITELLM_MOCK_OFFLINE is False
                assert "LITELLM_LOCAL_MODEL_COST_MAP" not in os.environ
                assert connections == [("localhost", 63501)], connections
                assert fake_litellm.drop_params is True
            """
        )
        env = os.environ.copy()
        env["OPENAI_MODEL"] = "deepseek/deepseek-chat"
        env.pop("LITELLM_LOCAL_MODEL_COST_MAP", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
