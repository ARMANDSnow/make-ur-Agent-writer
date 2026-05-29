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


if __name__ == "__main__":
    unittest.main()
