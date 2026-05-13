import unittest
import tempfile
from pathlib import Path
from unittest.mock import PropertyMock, patch

from src.llm_client import LLMClient
from src.schemas import AgentReview


class LLMClientJsonParseTests(unittest.TestCase):
    def test_invalid_json_raises_runtime_error_with_context(self) -> None:
        client = LLMClient("review")
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = False
            with patch.object(client, "complete_text", return_value="not valid json at all {{{"):
                with self.assertRaises(RuntimeError) as ctx:
                    client.complete_json(
                        [{"role": "user", "content": "test"}],
                        AgentReview,
                    )
                msg = str(ctx.exception)
                self.assertIn("AgentReview", msg)
                self.assertIn("First 500 chars", msg)
                self.assertIn("not valid json", msg)

    def test_invalid_json_can_be_repaired(self) -> None:
        client = LLMClient("review")
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = False
            with patch.object(
                client,
                "complete_text",
                side_effect=[
                    "not valid json",
                    '{"agent_name":"agent","verdict":"Approve","score":8,"issues":[],"suggestions":[]}',
                ],
            ):
                result = client.complete_json([{"role": "user", "content": "test"}], AgentReview)
        self.assertEqual(result.verdict, "Approve")

    def test_llm_call_log_does_not_include_prompt_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.llm_client.ROOT", Path(tmp)):
                client = LLMClient("review")
                client.complete_json(
                    [{"role": "user", "content": "SECRET_PROMPT_SHOULD_NOT_BE_LOGGED"}],
                    AgentReview,
                )
                log_path = Path(tmp) / "logs" / "llm_calls.jsonl"
                text = log_path.read_text(encoding="utf-8")
        self.assertIn('"task": "review"', text)
        self.assertNotIn("SECRET_PROMPT_SHOULD_NOT_BE_LOGGED", text)


if __name__ == "__main__":
    unittest.main()
