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
            ), patch("src.config.load_dotenv_if_available"):
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
                # iter078 P1-8 语义迁移：max_tokens 5000→50——新增的
                # max_tokens≥context_limit×0.9 FATAL 恰好会抓住旧 fixture 的
                # 矛盾配置（5000 vs 100）；本用例的原命题（超长章只 warn 不
                # fatal）与之正交，fixture 改成自洽值保命题不变。
                model_cfg.side_effect = lambda task="default": {
                    "model": "mock",
                    "temperature": 0.1,
                    "max_tokens": 50,
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
            ), patch("src.config.load_dotenv_if_available"):
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
            ), patch("src.config.load_dotenv_if_available"):
                report = run_preflight(Path(tmp))
        self.assertFalse(any("provider" in item.lower() for item in report["fatal"]))

    def test_real_model_missing_planner_api_key_is_fatal(self) -> None:
        fake_litellm = types.SimpleNamespace(get_llm_provider=lambda model: ("provider", model, None, None))
        env = {
            "OPENAI_MODEL": "deepseek/deepseek-chat",
            "OPENAI_API_KEY": "test",
            "OPENAI_BASE_URL": "https://x.com",
            "PLANNER_BASE_URL": "https://planner.example/v1",
        }
        with build_root() as tmp:
            with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {"litellm": fake_litellm}), patch(
                "src.preflight.load_dotenv_if_available"
            ), patch("src.config.load_dotenv_if_available"):
                report = run_preflight(Path(tmp))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("PLANNER_API_KEY" in item for item in report["fatal"]))


class Iter078GateTests(unittest.TestCase):
    """iter078 P1-8：env/preflight 守门盲区 4 项。"""

    def test_dirty_write_review_tier_is_fatal(self) -> None:
        with build_root() as tmp:
            with patch.dict(
                os.environ, {"OPENAI_MODEL": "mock", "WRITE_REVIEW_TIER": "ultra-strict"}, clear=True
            ):
                report = run_preflight(Path(tmp))
        self.assertEqual(report["status"], "fail")
        self.assertTrue(any("WRITE_REVIEW_TIER" in item for item in report["fatal"]), report["fatal"])

    def test_legal_tier_echoed_as_info(self) -> None:
        with build_root() as tmp:
            with patch.dict(
                os.environ, {"OPENAI_MODEL": "mock", "WRITE_REVIEW_TIER": "low"}, clear=True
            ):
                report = run_preflight(Path(tmp))
        self.assertEqual(report["fatal"], [])
        self.assertTrue(any("WRITE_REVIEW_TIER 生效值：low" in item for item in report["info"]))

    def test_nonfinite_timeout_warns_and_config_falls_back(self) -> None:
        from src.config import _env_float

        for bad in ("inf", "nan", "-5"):
            with self.subTest(bad=bad), build_root() as tmp:
                with patch.dict(
                    os.environ, {"OPENAI_MODEL": "mock", "LLM_REQUEST_TIMEOUT": bad}, clear=True
                ):
                    # config 侧：inf/nan 回退默认（-5 可解析且有限——由
                    # preflight WARN 提示，config 不改数值语义）
                    if bad in ("inf", "nan"):
                        self.assertEqual(_env_float("LLM_REQUEST_TIMEOUT", 240.0), 240.0)
                    report = run_preflight(Path(tmp))
                self.assertTrue(
                    any("LLM_REQUEST_TIMEOUT" in item for item in report["warn"]), report["warn"]
                )

    def test_max_tokens_over_ninety_percent_is_fatal(self) -> None:
        from src.preflight import _check_context_limits

        fatal: list = []
        warn: list = []
        info: list = []
        with patch("src.preflight.TASKS", ("write",)), patch(
            "src.preflight.get_model_config",
            return_value={"model": "mock", "temperature": 0.2, "max_tokens": 7000, "context_limit": 7500},
        ):
            _check_context_limits(
                fatal, warn, info, {"default": {"context_limit": 7500}, "tasks": {}}
            )
        self.assertTrue(any("恒触发" in item for item in fatal), fatal)

    def test_max_tokens_over_half_is_warn(self) -> None:
        from src.preflight import _check_context_limits

        fatal: list = []
        warn: list = []
        info: list = []
        with patch("src.preflight.TASKS", ("write",)), patch(
            "src.preflight.get_model_config",
            return_value={"model": "mock", "temperature": 0.2, "max_tokens": 5000, "context_limit": 8000},
        ):
            _check_context_limits(
                fatal, warn, info, {"default": {"context_limit": 8000}, "tasks": {}}
            )
        self.assertEqual(fatal, [])
        self.assertTrue(any("挤压" in item for item in warn), warn)

    def test_empty_manual_anchor_file_warns_specifically(self) -> None:
        with build_root() as tmp:
            root = Path(tmp)
            anchor = root / "data" / "manual_overrides" / "continuation_anchor.txt"
            anchor.parent.mkdir(parents=True, exist_ok=True)
            anchor.write_text("   \n", encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True):
                report = run_preflight(root)
        self.assertTrue(
            any("手工文件存在但内容为空" in item for item in report["warn"]), report["warn"]
        )

    def test_workspace_yaml_anchor_not_effective_warns(self) -> None:
        # workspace 态（root≠repo root）yaml 的 anchor 不生效——旧检查按 yaml
        # 值放行是假阳性，新检查必须点破。
        from src.config import load_config as real_load_config

        def fake_load_config(name: str):
            cfg = dict(real_load_config(name))
            if name == "agents.yaml":
                cfg["continuation_anchor"] = "第 42 章之后"
            return cfg

        with build_root() as tmp:
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True), patch(
                "src.preflight.load_config", side_effect=fake_load_config
            ), patch("src.continuation_anchor.load_config", side_effect=fake_load_config):
                report = run_preflight(Path(tmp))
        self.assertTrue(
            any("只认 manual 文件" in item for item in report["warn"]), report["warn"]
        )

    def test_manual_anchor_wins_over_yaml_echoed(self) -> None:
        from src.config import load_config as real_load_config

        def fake_load_config(name: str):
            cfg = dict(real_load_config(name))
            if name == "agents.yaml":
                cfg["continuation_anchor"] = "yaml 锚"
            return cfg

        with build_root() as tmp:
            root = Path(tmp)
            anchor = root / "data" / "manual_overrides" / "continuation_anchor.txt"
            anchor.parent.mkdir(parents=True, exist_ok=True)
            anchor.write_text("manual 锚", encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True), patch(
                "src.preflight.load_config", side_effect=fake_load_config
            ):
                report = run_preflight(root)
        self.assertTrue(
            any("manual 文件优先生效" in item for item in report["info"]), report["info"]
        )


class Iter078ContextLimitLaneTests(unittest.TestCase):
    """iter078 P1-3：yaml context_limit 与已知模型上限矛盾的可见性 lane。"""

    def _run_lane(self, *, yaml_limit: int, effective_model: str, effective_limit: int):
        from src.preflight import _check_context_limits

        fatal: list = []
        warn: list = []
        info: list = []
        model_cfg = {
            "default": {"context_limit": 128000},
            "tasks": {"write": {"context_limit": yaml_limit}},
        }
        fake_cfg = {
            "model": effective_model,
            "temperature": 0.65,
            "max_tokens": 8000,
            "context_limit": effective_limit,
        }
        with patch("src.preflight.TASKS", ("write",)), patch(
            "src.preflight.get_model_config", return_value=fake_cfg
        ):
            _check_context_limits(fatal, warn, info, model_cfg)
        return fatal, warn, info

    def test_over_cap_warns_with_effective_value(self) -> None:
        fatal, warn, info = self._run_lane(
            yaml_limit=128000, effective_model="deepseek/deepseek-chat", effective_limit=64000
        )
        self.assertEqual(fatal, [])
        self.assertTrue(any("已按 64000 生效" in w for w in warn), warn)

    def test_under_cap_is_info_not_warn(self) -> None:
        fatal, warn, info = self._run_lane(
            yaml_limit=32000, effective_model="deepseek/deepseek-chat", effective_limit=32000
        )
        self.assertEqual([w for w in warn if "context_limit" in w], [])
        self.assertTrue(any("主动保守" in i for i in info), info)

    def test_mock_model_skips_lane(self) -> None:
        fatal, warn, info = self._run_lane(
            yaml_limit=128000, effective_model="mock", effective_limit=128000
        )
        self.assertEqual([w for w in warn if "context_limit" in w], [])


if __name__ == "__main__":
    unittest.main()
