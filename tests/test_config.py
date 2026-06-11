import os
import unittest
from unittest.mock import patch

from src.config import get_model_config


class ModelConfigTests(unittest.TestCase):
    def test_write_max_tokens_env_override(self) -> None:
        with patch.dict(os.environ, {"WRITE_MAX_TOKENS": "1234"}, clear=False):
            cfg = get_model_config("write")

        self.assertEqual(cfg["max_tokens"], 1234)

    def test_default_max_tokens_unchanged_without_override(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WRITE_MAX_TOKENS", None)
            cfg = get_model_config("write")

        self.assertEqual(cfg["max_tokens"], 8000)

    def test_garbage_write_max_tokens_env_keeps_default(self) -> None:
        # iter 051b (F3): a typo'd env must degrade to the config default,
        # not crash get_model_config.
        with patch.dict(os.environ, {"WRITE_MAX_TOKENS": "lots"}, clear=False):
            cfg = get_model_config("write")

        self.assertEqual(cfg["max_tokens"], 8000)


class NumericParseHardeningTests(unittest.TestCase):
    """iter 051b (F3+F8): _safe_int/_safe_float/_env_float — hand-edited
    config values and env vars degrade to defaults instead of raising."""

    def test_safe_int_matrix(self) -> None:
        from src.config import _safe_int

        self.assertEqual(_safe_int("3", 1), 3)
        self.assertEqual(_safe_int(4.0, 1), 4)
        for bad in ("abc", "3.5", None, [], ""):
            self.assertEqual(_safe_int(bad, 7), 7, repr(bad))

    def test_safe_float_matrix(self) -> None:
        from src.config import _safe_float

        self.assertEqual(_safe_float("0.5", 1.0), 0.5)
        self.assertEqual(_safe_float(2, 1.0), 2.0)
        for bad in ("abc", None, [], ""):
            self.assertEqual(_safe_float(bad, 0.25), 0.25, repr(bad))

    def test_env_float_matrix(self) -> None:
        from src.config import _env_float

        with patch.dict(os.environ, {"X_FLOAT_TEST": "1.5"}, clear=False):
            self.assertEqual(_env_float("X_FLOAT_TEST", 9.0), 1.5)
        with patch.dict(os.environ, {"X_FLOAT_TEST": " 2.5 "}, clear=False):
            self.assertEqual(_env_float("X_FLOAT_TEST", 9.0), 2.5)
        for bad in ("abc", ""):
            with patch.dict(os.environ, {"X_FLOAT_TEST": bad}, clear=False):
                self.assertEqual(_env_float("X_FLOAT_TEST", 9.0), 9.0, repr(bad))
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("X_FLOAT_TEST", None)
            self.assertEqual(_env_float("X_FLOAT_TEST", 9.0), 9.0)

    def test_mcp_server_env_floats_degrade_not_crash(self) -> None:
        # iter 051b (F8): the MCP server used bare float() on four envs — a
        # typo crashed it at startup. Defaults must be preserved verbatim.
        from integrations.mcp_server.server import _cfg_from_env, _client_from_env

        with patch.dict(
            os.environ,
            {"NOVEL_REQUEST_TIMEOUT_S": "soon", "NOVEL_WRITE_BUDGET_CNY": "cheap"},
            clear=False,
        ):
            client = _client_from_env()
            cfg = _cfg_from_env()
        self.assertEqual(client.request_timeout_s, 30.0)
        self.assertEqual(cfg.write_budget_cny, 5.0)


if __name__ == "__main__":
    unittest.main()
