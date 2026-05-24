import unittest
from pathlib import Path
from unittest.mock import patch

from src.reviewer import _repair_agent_review_dict, review_text
from src.reviewer import load_review_agents


class ReviewerPrecomputedLintTests(unittest.TestCase):
    def test_uses_precomputed_lint_when_provided(self) -> None:
        precomputed = [
            {"rule": "meta_chapter_markers", "severity": "error", "message": "bad", "line": 1, "excerpt": "第 1 章"}
        ]
        # With precomputed error-level issue, should reject immediately without needing linter
        report = review_text("some text", "test_draft.md", precomputed_lint_issues=precomputed)
        self.assertEqual(report["verdict"], "Reject")
        self.assertEqual(report["lint_issues"], precomputed)

    def test_runs_linter_when_precomputed_not_provided(self) -> None:
        # Text with chapter marker triggers meta_chapter_markers rule
        report = review_text("第 1 章 开始", "test_draft.md")
        self.assertIn("verdict", report)
        # Linter was run internally — should detect the marker
        rules = {issue["rule"] for issue in report.get("lint_issues", [])}
        self.assertIn("meta_chapter_markers", rules)

    def test_review_prompt_includes_global_facts(self) -> None:
        captured = {}

        def fake_complete_text(self, messages):
            captured["prompt"] = "\n".join(m.get("content", "") for m in messages)
            return '{"agent_name":"agent","verdict":"Approve","score":8,"issues":[],"suggestions":[]}'

        with patch("src.reviewer.global_facts_summary", return_value="FACT: 绘梨衣已死亡"), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ), patch("src.reviewer.load_review_agents", return_value=[{"name": "agent", "system_prompt": "review"}]):
            report = review_text("干净正文。", "clean.md", precomputed_lint_issues=[])
        self.assertEqual(report["verdict"], "Approve")
        self.assertIn("FACT: 绘梨衣已死亡", captured["prompt"])

    def test_missing_agent_name_is_repaired_from_config(self) -> None:
        def fake_complete_text(self, messages):
            return '{"verdict":"Approve","score":8,"issues":[],"suggestions":[]}'

        with patch("src.reviewer.load_review_agents", return_value=[{"name": "文本守门人", "system_prompt": "review"}]), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ):
            report = review_text("干净正文。", "missing_agent.md", precomputed_lint_issues=[])

        self.assertEqual(report["agent_reviews"][0]["agent_name"], "文本守门人")
        self.assertEqual(report["verdict"], "Approve")

    def test_review_text_falls_back_when_outer_json_unparseable(self) -> None:
        """Iter 019 audit fix: a single agent's malformed JSON used to
        short-circuit the whole review with a silent Approve. Now the
        agent abstains, and with only one agent in the panel that means
        all-abstain → Reject (fail-closed). The json_parse_fallback log
        event still fires for observability.
        """

        def fake_complete_text(self, messages):
            return "random text without json"

        with patch("src.reviewer.load_review_agents", return_value=[{"name": "文本守门人", "system_prompt": "review"}]), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ), patch("src.reviewer.log_event") as mock_log:
            report = review_text("干净正文。", "parse_failed.md", precomputed_lint_issues=[])

        self.assertEqual(report["verdict"], "Reject")
        self.assertEqual(report["_fallback_reason"], "(all_agents_parse_failed)")
        self.assertEqual(len(report["agent_reviews"]), 1)
        self.assertEqual(report["agent_reviews"][0]["verdict"], "Abstain")
        self.assertEqual(report["agent_reviews"][0]["_fallback_reason"], "(parse_failed)")
        self.assertTrue(any(call.args[:2] == ("review", "json_parse_fallback") for call in mock_log.call_args_list))

    def test_partial_parse_failure_does_not_short_circuit_remaining_agents(self) -> None:
        """Iter 019 audit regression: when agent[0] returns malformed JSON,
        the OLD reviewer returned Approve immediately and never asked
        agent[1]. The FIX must call all agents and respect their verdicts.
        Here agent[1] returns Reject; the final verdict must be Reject.
        """

        call_log = []

        def fake_complete_text(self, messages):
            agent_marker = next(
                (m["content"] for m in messages if "agent_name:" in m.get("content", "")),
                "",
            )
            if "agent_a" in agent_marker:
                call_log.append("a")
                return "garbage not json"
            call_log.append("b")
            return '{"agent_name":"agent_b","verdict":"Reject","score":3,"issues":[{"message":"bad","severity":"major"}],"suggestions":[]}'

        agents = [
            {"name": "agent_a", "system_prompt": "first agent"},
            {"name": "agent_b", "system_prompt": "second agent"},
        ]
        with patch("src.reviewer.load_review_agents", return_value=agents), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ):
            report = review_text("干净正文。", "partial_fail.md", precomputed_lint_issues=[])

        # Both agents must have been called — short-circuit bug regression guard.
        self.assertEqual(call_log, ["a", "b"])
        # Aggregate verdict reflects agent_b's Reject, not the parse-fail Approve fallback.
        self.assertEqual(report["verdict"], "Reject")
        # Exactly 2 entries: one Abstain from agent_a, one Reject from agent_b.
        self.assertEqual(len(report["agent_reviews"]), 2)
        verdicts = sorted(r["verdict"] for r in report["agent_reviews"])
        self.assertEqual(verdicts, ["Abstain", "Reject"])
        # No top-level fallback marker because not ALL agents failed.
        self.assertNotIn("_fallback_reason", report)

    def test_partial_parse_failure_with_other_agents_approving_still_approves(self) -> None:
        """Iter 019 audit regression: one agent parse-fails, others approve.
        The audit fix must still allow Approve in this case (it only blocks
        the silent-approve when there are NO substantive verdicts at all).
        """

        def fake_complete_text(self, messages):
            agent_marker = next(
                (m["content"] for m in messages if "agent_name:" in m.get("content", "")),
                "",
            )
            if "agent_a" in agent_marker:
                return "still not json"
            return '{"agent_name":"agent_b","verdict":"Approve","score":8,"issues":[],"suggestions":[]}'

        agents = [
            {"name": "agent_a", "system_prompt": "first agent"},
            {"name": "agent_b", "system_prompt": "second agent"},
        ]
        with patch("src.reviewer.load_review_agents", return_value=agents), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ):
            report = review_text("干净正文。", "partial_ok.md", precomputed_lint_issues=[])

        # agent_b's Approve is the only substantive verdict — final is Approve.
        self.assertEqual(report["verdict"], "Approve")
        self.assertEqual(len(report["agent_reviews"]), 2)
        # First entry abstains, second approves.
        verdicts = [r["verdict"] for r in report["agent_reviews"]]
        self.assertIn("Abstain", verdicts)
        self.assertIn("Approve", verdicts)

    def test_relationship_consistency_prompt_requires_checklist(self) -> None:
        agents_yaml = Path("config/agents.yaml").read_text(encoding="utf-8")
        self.assertIn("对照清单", agents_yaml)
        self.assertIn("禁止输出空 issues 的纯 Approve", agents_yaml)

    def test_relationship_consistency_empty_approve_becomes_review_issue(self) -> None:
        repaired = _repair_agent_review_dict(
            {"verdict": "Approve", "score": 7, "issues": [], "suggestions": []},
            "关系一致性",
        )
        self.assertEqual(repaired["verdict"], "Reject")
        self.assertEqual(repaired["issues"][0]["rule_id"], "relationship_checklist_missing")

    def test_relationship_consistency_checklist_approve_is_preserved(self) -> None:
        repaired = _repair_agent_review_dict(
            {"verdict": "Approve", "score": 8, "issues": [], "comparison_checklist": ["甲-乙：匹配"]},
            "关系一致性",
        )
        self.assertEqual(repaired["verdict"], "Approve")
        self.assertEqual(repaired["issues"], [])
        self.assertEqual(repaired["comparison_checklist"], ["甲-乙：匹配"])

    def test_enforce_relationship_checklist_rejects_empty_standalone_review(self) -> None:
        def fake_complete_text(self, messages):
            return '{"verdict":"Approve","score":8,"issues":[],"suggestions":[]}'

        with patch("src.reviewer.load_review_agents", return_value=[{"name": "关系一致性", "system_prompt": "review"}]), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ):
            report = review_text(
                "干净正文。",
                "relationship_empty.md",
                precomputed_lint_issues=[],
                enforce_relationship_checklist=True,
            )

        self.assertEqual(report["verdict"], "Reject")
        self.assertEqual(report["agent_reviews"][0]["issues"][0]["rule_id"], "relationship_checklist_missing")

    def test_relationship_consistency_agent_in_review_pipeline(self) -> None:
        graph = {
            "entities": [
                {"id": "a", "name": "甲", "type": "character", "tags": ["#同盟"], "key_facts": ["事实甲"]},
                {"id": "b", "name": "乙", "type": "character", "tags": ["#同盟"], "key_facts": ["事实乙"]},
            ],
            "relationships": [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "relation_type": "同盟",
                    "timeline": [{"anchor_chapter": "now", "state": "当前必须互相信任", "active": True}],
                }
            ],
        }
        captured = {}

        def fake_complete_text(self, messages):
            prompt = "\n".join(m.get("content", "") for m in messages)
            agent_name = prompt.split("agent_name: ", 1)[1].split("\n", 1)[0]
            captured[agent_name] = prompt
            if agent_name == "关系一致性":
                return '{"verdict":"Approve","score":8,"issues":[],"suggestions":[],"comparison_checklist":["甲-乙：匹配"]}'
            return '{"verdict":"Approve","score":8,"issues":[],"suggestions":[]}'

        self.assertIn("关系一致性", [agent["name"] for agent in load_review_agents()])
        with patch("src.reviewer.load_entity_graph", return_value=graph), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ):
            report = review_text("干净正文。", "relationship.md", precomputed_lint_issues=[])

        self.assertEqual(report["verdict"], "Approve")
        self.assertIn("关系一致性", [item["agent_name"] for item in report["agent_reviews"]])
        self.assertIn("tags:", captured["关系一致性"])
        self.assertIn("tag 反向索引", captured["关系一致性"])
        self.assertIn("当前必须互相信任", captured["关系一致性"])
        self.assertIn("人工全局事实", captured["关系一致性"])


class ReviewerPersonaRenderingTests(unittest.TestCase):
    """Iter 016: persona-rendered reviewer agents must (1) appear with the
    rendered name in the report, (2) inject persona-bound variables into the
    system prompt, and (3) preserve the legacy-name-keyed relationship
    checklist enforcement so 关系一致性 still gets its hard guard.
    """

    def test_review_renders_persona_into_reviewer_prompt_and_name(self) -> None:
        captured = {}

        def fake_complete_text(self, messages):
            system_content = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
            user_content = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
            agent_name = user_content.split("agent_name: ", 1)[1].split("\n", 1)[0]
            captured.setdefault(agent_name, []).append(system_content)
            return '{"verdict":"Approve","score":8,"issues":[],"suggestions":[],"comparison_checklist":["mock"]}'

        agents = [
            {
                "name": "路明非本位",
                "system_prompt": "legacy prompt for 路明非",
                "name_template": "{protagonist_name}本位",
                "system_prompt_template": "审查章节是否让 {protagonist_name}（{protagonist_role}）保持主动性。",
            }
        ]
        personas = {
            "protagonist_name": "甲",
            "protagonist_role": "主角",
            "author_name": "乙",
            "style_short_descriptor": "白话",
            "world_setting_brief": "骨架",
            "core_relationships": [],
            "core_setting_rules": [],
        }
        with patch("src.reviewer.load_review_agents", return_value=agents), patch(
            "src.reviewer.load_personas", return_value=personas
        ), patch("src.llm_client.LLMClient.complete_text", fake_complete_text):
            report = review_text("干净正文。", "persona_render.md", precomputed_lint_issues=[])

        self.assertEqual(report["verdict"], "Approve")
        # Rendered name appears in the report, legacy name does not.
        names = [item["agent_name"] for item in report["agent_reviews"]]
        self.assertIn("甲本位", names)
        self.assertNotIn("路明非本位", names)
        # The system prompt the LLM actually received is the rendered template.
        rendered_system = captured["甲本位"][0]
        self.assertIn("甲", rendered_system)
        self.assertIn("主角", rendered_system)
        self.assertNotIn("路明非", rendered_system)


if __name__ == "__main__":
    unittest.main()
