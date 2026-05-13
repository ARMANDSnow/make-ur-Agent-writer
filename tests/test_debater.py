import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from src.debater import _collect_agent_votes, _transcript_summary, build_decisions, build_outline
from src.llm_client import LLMClient
from src.schemas import DebateDecisions, DebateVote


class DebaterAgentFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = LLMClient("debate")

    def test_agent_error_records_in_transcript(self) -> None:
        with patch.object(LLMClient, "complete_text", side_effect=RuntimeError("boom")):
            from src.debater import run_debate

            with tempfile.TemporaryDirectory() as tmp:
                kb = Path(tmp) / "global_knowledge.md"
                kb.write_text("# test knowledge", encoding="utf-8")
                idx = Path(tmp) / "knowledge_index.json"
                idx.write_text("{}", encoding="utf-8")

                with patch("src.debater.KB_PATH", kb), patch("src.debater.INDEX_PATH", idx), patch(
                    "src.debater.DEBATE_DIR", Path(tmp)
                ):
                    run_debate()

                # Check file while temp dir still exists
                log_path = Path(tmp) / "debate_log.jsonl"
                self.assertTrue(log_path.exists())
                lines = log_path.read_text(encoding="utf-8").strip().split("\n")
                error_items = [json.loads(line) for line in lines if "error" in json.loads(line)]
                self.assertTrue(len(error_items) > 0)
                item = error_items[0]
                self.assertEqual(item["response"], "")
                self.assertIn("boom", item["error"])

    def test_llm_fallback_when_parse_fails(self) -> None:
        agents = [{"name": "a1", "stance": "s1"}, {"name": "a2", "stance": "s2"}]
        transcript = [{"round": 1, "round_name": "test", "agent": "a1", "response": "x"}]
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = False
            with patch.object(self.client, "complete_text", return_value="garbage not json"):
                decisions = build_decisions(agents, transcript, self.client)
                self.assertIn("votes", decisions)
                self.assertIn("topic", decisions)

    def test_llm_decisions_preserve_for_alias(self) -> None:
        agents = [{"name": "a1", "stance": "s1"}, {"name": "a2", "stance": "s2"}]
        transcript = [{"round": 1, "round_name": "test", "agent": "a1", "response": "x"}]
        llm_result = DebateDecisions(
            topic="裁决",
            votes=[DebateVote(question="Q", result="R", **{"for": ["a1"]}, against=["a2"])],
            transcript_items=1,
        )
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = False
            with patch.object(self.client, "complete_json", return_value=llm_result):
                decisions = build_decisions(agents, transcript, self.client)
                self.assertIn("for", decisions["votes"][0])
                self.assertNotIn("for_", decisions["votes"][0])

    def test_build_decisions_without_ballots_preserves_llm_votes(self) -> None:
        agents = [{"name": "a1", "stance": "s1"}, {"name": "a2", "stance": "s2"}]
        transcript = [{"round": 1, "round_name": "test", "agent": "a1", "response": "x"}]
        llm_result = DebateDecisions(
            topic="裁决",
            votes=[DebateVote(question="Q", result="R", **{"for": ["a2"]}, against=["a1"])],
            transcript_items=1,
        )
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = False
            with patch.object(self.client, "complete_json", return_value=llm_result):
                decisions = build_decisions(agents, transcript, self.client)
                self.assertEqual(decisions["votes"][0]["for"], ["a2"])
                self.assertEqual(decisions["votes"][0]["against"], ["a1"])

    def test_build_decisions_aggregates_agent_ballots_by_majority(self) -> None:
        agents = [{"name": "a1"}, {"name": "a2"}, {"name": "a3"}]
        transcript = [{"round": 1, "agent": "a1", "response": "x"}]
        ballots = {
            "a1": [{"question_index": 0, "position": "agree", "reason": "yes"}],
            "a2": [{"question_index": 0, "position": "agree", "reason": "yes"}],
            "a3": [{"question_index": 0, "position": "reject", "reason": "no"}],
        }
        decisions = build_decisions(agents, transcript, self.client, agent_ballots=ballots)
        self.assertEqual(decisions["votes"][0]["for"], ["a1", "a2"])
        self.assertEqual(decisions["votes"][0]["against"], ["a3"])
        self.assertEqual(len(decisions["votes"][0]["agent_votes"]), 3)
        self.assertEqual(decisions["aggregation_method"], "majority")

    def test_build_decisions_marks_tie_result(self) -> None:
        agents = [{"name": "a1"}, {"name": "a2"}]
        transcript = [{"round": 1, "agent": "a1", "response": "x"}]
        ballots = {
            "a1": [{"question_index": 0, "position": "agree", "reason": "yes"}],
            "a2": [{"question_index": 0, "position": "reject", "reason": "no"}],
        }
        decisions = build_decisions(agents, transcript, self.client, agent_ballots=ballots)
        self.assertTrue(decisions["votes"][0]["result"].startswith("[平票] "))
        self.assertEqual(decisions["votes"][0]["for"], ["a1"])
        self.assertEqual(decisions["votes"][0]["against"], ["a2"])

    def test_collect_agent_votes_falls_back_to_abstain_and_logs(self) -> None:
        agent = {"name": "a1", "stance": "s1"}
        votes = [{"question": "Q1", "result": "R1"}, {"question": "Q2", "result": "R2"}]
        transcript = [{"round": 1, "agent": "a1", "response": "x"}]
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = False
            with patch.object(self.client, "complete_json", side_effect=RuntimeError("bad json")):
                with patch("src.debater.log_event") as mock_log:
                    result = _collect_agent_votes(agent, votes, transcript, self.client)
        self.assertEqual([item["position"] for item in result["ballots"]], ["abstain", "abstain"])
        self.assertEqual([item["reason"] for item in result["ballots"]], ["(parse_failed)", "(parse_failed)"])
        mock_log.assert_called_once()
        self.assertEqual(mock_log.call_args.args[:2], ("debate", "ballot_fallback"))


class DebaterTranscriptTests(unittest.TestCase):
    def test_transcript_summary_truncates_long_transcript(self) -> None:
        transcript = [{"round": 1, "agent": f"a{i}", "response": "x"} for i in range(50)]
        summary = _transcript_summary(transcript)
        data = json.loads(summary)
        self.assertTrue(any("__truncated__" in item for item in data))

    def test_transcript_summary_keeps_short_transcript_intact(self) -> None:
        transcript = [{"round": 1, "agent": "a1", "response": "x"}]
        summary = _transcript_summary(transcript)
        self.assertEqual(json.loads(summary), transcript)


class DebaterHardcodedFallbackTests(unittest.TestCase):
    def test_mock_client_uses_hardcoded_decisions(self) -> None:
        client = LLMClient("debate")
        agents = [{"name": "a1"}, {"name": "a2"}]
        transcript = [{"round": 1, "agent": "a1", "response": "hello"}]
        decisions = build_decisions(agents, transcript, client)
        self.assertIn("路鸣泽", decisions["votes"][0]["question"])
        self.assertEqual(decisions["transcript_items"], 1)

    def test_hardcoded_outline_contains_votes(self) -> None:
        from src.debater import _hardcoded_outline

        decisions = {
            "votes": [{"question": "Q1", "result": "R1"}],
        }
        outline = _hardcoded_outline("Test", decisions)
        self.assertIn("Q1", outline)
        self.assertIn("R1", outline)
        self.assertIn("核心共识", outline)

    def test_run_debate_mock_outputs_agent_votes(self) -> None:
        from src.debater import run_debate

        with tempfile.TemporaryDirectory() as tmp:
            kb = Path(tmp) / "global_knowledge.md"
            kb.write_text("# test knowledge", encoding="utf-8")
            idx = Path(tmp) / "knowledge_index.json"
            idx.write_text("{}", encoding="utf-8")

            with patch("src.debater.KB_PATH", kb), patch("src.debater.INDEX_PATH", idx), patch(
                "src.debater.DEBATE_DIR", Path(tmp)
            ):
                result = run_debate()

            decisions = result["decisions"]
            self.assertEqual(decisions["aggregation_method"], "majority")
            for vote in decisions["votes"]:
                self.assertEqual(len(vote["agent_votes"]), 6)
                self.assertTrue({"agent_name", "position", "reason"}.issubset(vote["agent_votes"][0]))

            log_path = Path(tmp) / "debate_log.jsonl"
            items = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            ballot_items = [item for item in items if item.get("round_name") == "裁决投票"]
            self.assertEqual(len(ballot_items), 6)


if __name__ == "__main__":
    unittest.main()
