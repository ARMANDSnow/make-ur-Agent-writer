"""iter 053 拍板④: 提速降本两个小钩子。

* ``WRITE_REVIEW_MIN_APPROVE`` —— 只降票数闸、分数线随 tier 不动（整体换
  tier low 会把分数线连降到 6.5，违背"不影响质量"前提）；缺省/非法值回退
  tier 预设（铁律④回退契约），合法值夹紧 1-5。
* models.yaml 的 write/review/debate ``model_env`` 钩子 —— 按任务粒度换模型
  档（如 GPT-5.5-low），复用 config.get_model_config 现成机制；mock 隔离
  优先级不变（OPENAI_MODEL=mock 时 model_env 不得突破 mock）。
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src import review_tier
from src.config import get_model_config


class MinApproveOverrideTests(unittest.TestCase):
    def test_default_without_env_is_tier_preset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WRITE_REVIEW_MIN_APPROVE", None)
            thresholds = review_tier.thresholds_for("mid")
        self.assertEqual(thresholds.min_approve_count, 4)
        self.assertEqual(thresholds.min_panel_score, 7.5)

    def test_override_lowers_votes_keeps_panel_score(self) -> None:
        # 053c 配方：WRITE_REVIEW_MIN_APPROVE=3 + tier mid → 3 票闸 + 7.5 分线。
        with patch.dict(os.environ, {"WRITE_REVIEW_MIN_APPROVE": "3"}, clear=False):
            thresholds = review_tier.thresholds_for("mid")
        self.assertEqual(thresholds.min_approve_count, 3)
        self.assertEqual(thresholds.min_panel_score, 7.5)

    def test_invalid_value_falls_back_and_legal_value_clamps(self) -> None:
        with patch.dict(os.environ, {"WRITE_REVIEW_MIN_APPROVE": "abc"}, clear=False):
            self.assertEqual(review_tier.thresholds_for("mid").min_approve_count, 4)
        with patch.dict(os.environ, {"WRITE_REVIEW_MIN_APPROVE": "99"}, clear=False):
            self.assertEqual(review_tier.thresholds_for("mid").min_approve_count, 5)
        with patch.dict(os.environ, {"WRITE_REVIEW_MIN_APPROVE": "0"}, clear=False):
            self.assertEqual(review_tier.thresholds_for("mid").min_approve_count, 1)

    def test_snapshot_reflects_override(self) -> None:
        with patch.dict(os.environ, {"WRITE_REVIEW_MIN_APPROVE": "3"}, clear=False):
            snapshot = review_tier.thresholds_snapshot("mid")
        self.assertEqual(snapshot["min_approve_count"], 3)
        self.assertEqual(snapshot["min_panel_score"], 7.5)


class TaskModelEnvHookTests(unittest.TestCase):
    def test_model_env_overrides_per_task_when_not_mock(self) -> None:
        env = {
            "OPENAI_MODEL": "openai/gpt-5.5",
            "WRITER_MODEL": "openai/gpt-5.5-low",
            "REVIEWER_MODEL": "openai/gpt-5.5-low",
            "DEBATER_MODEL": "openai/gpt-5.5-low",
        }
        # get_model_config 每次调用都会经 load_dotenv_if_available 把测试环境
        # 强制刷回 mock（047B2 M9 隔离铁则）——非 mock 路径只能 no-op 掉 scrub
        # 才测得到。
        with patch("src.config.load_dotenv_if_available"), patch.dict(
            os.environ, env, clear=False
        ):
            self.assertEqual(get_model_config("write")["model"], "openai/gpt-5.5-low")
            self.assertEqual(get_model_config("review")["model"], "openai/gpt-5.5-low")
            self.assertEqual(get_model_config("debate")["model"], "openai/gpt-5.5-low")
            # 未挂钩子的任务不受影响。
            self.assertEqual(get_model_config("compress")["model"], "openai/gpt-5.5")

    def test_mock_isolation_beats_model_env(self) -> None:
        # 测试隔离铁则：OPENAI_MODEL=mock 时任何 model_env 都不得逃逸 mock。
        env = {"OPENAI_MODEL": "mock", "WRITER_MODEL": "openai/gpt-5.5-low"}
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(get_model_config("write")["model"], "mock")


if __name__ == "__main__":
    unittest.main()
