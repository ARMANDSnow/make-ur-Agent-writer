import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from src.preflight import run_preflight
from src.utils import write_json


def load_config_with_empty_anchor(name: str):
    from src.config import load_config as real_load_config

    cfg = real_load_config(name)
    if name == "agents.yaml":
        cfg = dict(cfg)
        cfg["continuation_anchor"] = ""
    return cfg


def build_root() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "logs").mkdir()
    (root / "data" / "extracted_jsons").mkdir(parents=True)
    (root / "data" / "extraction_failures").mkdir(parents=True)
    (root / "data" / "rolling_summaries").mkdir(parents=True)
    (root / "data" / "manual_overrides").mkdir(parents=True)
    write_json(
        root / "data" / "chapter_manifest.json",
        [
            {
                "chapter_id": "longzu_1_ch001",
                "volume_id": "longzu_1",
                "source_file": "source.txt",
                "normalized_file": "norm.txt",
                "title": "第一章",
                "start_line": 1,
                "end_line": 2,
                "char_count": 100,
            }
        ],
    )
    write_json(root / "data" / "manual_overrides" / "global_facts.json", [{"fact_id": "f", "statement": "fact"}])
    return tmp


class PreflightTests(unittest.TestCase):
    def test_missing_api_key_for_real_model_is_fatal(self) -> None:
        with build_root() as tmp:
            with patch.dict(os.environ, {"OPENAI_MODEL": "deepseek-chat", "OPENAI_BASE_URL": "https://example.com"}, clear=True), patch(
                "src.preflight.load_dotenv_if_available"
            ):
                report = run_preflight(Path(tmp))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("OPENAI_API_KEY" in item for item in report["fatal"]))

    def test_mock_model_with_clean_files_is_ok(self) -> None:
        with build_root() as tmp:
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True), patch(
                "src.preflight.load_config", side_effect=load_config_with_empty_anchor
            ):
                report = run_preflight(Path(tmp))
        self.assertEqual(report["status"], "warn")
        self.assertEqual(report["fatal"], [])
        self.assertTrue(any("continuation_anchor" in item for item in report["warn"]))

    def test_empty_continuation_anchor_is_warn(self) -> None:
        with build_root() as tmp:
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True), patch(
                "src.preflight.load_config", side_effect=load_config_with_empty_anchor
            ):
                report = run_preflight(Path(tmp))
        self.assertEqual(report["status"], "warn")
        self.assertTrue(any("continuation_anchor is empty" in item for item in report["warn"]))

    def test_residual_extraction_failure_is_fatal(self) -> None:
        with build_root() as tmp:
            root = Path(tmp)
            (root / "data" / "extraction_failures" / "bad.json").write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True):
                report = run_preflight(root)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("extraction_failures" in item for item in report["fatal"]))

    def test_rolling_last_chapter_missing_from_extracted_is_fatal(self) -> None:
        with build_root() as tmp:
            root = Path(tmp)
            write_json(
                root / "data" / "rolling_summaries" / "longzu_1.json",
                {"previous_summaries": ["s"], "previous_chapter_ids": ["longzu_1_ch999"]},
            )
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True):
                report = run_preflight(root)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("longzu_1_ch999" in item for item in report["fatal"]))

    def test_longest_chapter_over_context_is_warn_only(self) -> None:
        with build_root() as tmp:
            root = Path(tmp)
            manifest = json.loads((root / "data" / "chapter_manifest.json").read_text(encoding="utf-8"))
            manifest[0]["char_count"] = 30000
            write_json(root / "data" / "chapter_manifest.json", manifest)
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True), patch(
                "src.preflight.get_model_config"
            ) as model_cfg:
                model_cfg.side_effect = lambda task="default": {
                    "model": "mock",
                    "temperature": 0.1,
                    "max_tokens": 5000,
                    "context_limit": 100,
                    "cache_enabled": False,
                }
                report = run_preflight(root)
        self.assertEqual(report["status"], "warn")
        self.assertTrue(any("Longest chapter" in item for item in report["warn"]))
        self.assertEqual(report["fatal"], [])

    def test_missing_max_review_attempts_is_fatal(self) -> None:
        from src.config import load_config as real_load_config

        def fake_load_config(name: str):
            if name == "agents.yaml":
                cfg = dict(real_load_config(name))
                cfg.pop("max_review_attempts", None)
                return cfg
            return real_load_config(name)

        with build_root() as tmp:
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True), patch(
                "src.preflight.load_config", side_effect=fake_load_config
            ):
                report = run_preflight(Path(tmp))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("max_review_attempts" in item for item in report["fatal"]))

    def test_empty_global_facts_warns(self) -> None:
        with build_root() as tmp:
            root = Path(tmp)
            (root / "data" / "manual_overrides" / "global_facts.json").write_text("[]", encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True):
                report = run_preflight(root)
        self.assertEqual(report["status"], "warn")
        self.assertTrue(any("global_facts.json" in item for item in report["warn"]))

    def test_real_model_unknown_provider_is_fatal(self) -> None:
        fake_litellm = types.SimpleNamespace(
            get_llm_provider=lambda model: (_ for _ in ()).throw(ValueError("unknown provider"))
        )
        env = {
            "OPENAI_MODEL": "deepseek-chat",
            "OPENAI_API_KEY": "test",
            "OPENAI_BASE_URL": "https://x.com",
        }
        with build_root() as tmp:
            with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {"litellm": fake_litellm}), patch(
                "src.preflight.load_dotenv_if_available"
            ):
                report = run_preflight(Path(tmp))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("provider" in item.lower() for item in report["fatal"]))

    def test_real_model_known_provider_no_fatal_routing(self) -> None:
        fake_litellm = types.SimpleNamespace(get_llm_provider=lambda model: ("deepseek", model, None, None))
        env = {
            "OPENAI_MODEL": "deepseek/deepseek-chat",
            "OPENAI_API_KEY": "test",
            "OPENAI_BASE_URL": "https://x.com",
        }
        with build_root() as tmp:
            with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {"litellm": fake_litellm}), patch(
                "src.preflight.load_dotenv_if_available"
            ):
                report = run_preflight(Path(tmp))
        self.assertFalse(any("provider" in item.lower() for item in report["fatal"]))


if __name__ == "__main__":
    unittest.main()
