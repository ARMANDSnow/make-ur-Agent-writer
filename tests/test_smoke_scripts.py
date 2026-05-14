import unittest
from pathlib import Path


class SmokeScriptTests(unittest.TestCase):
    def test_verify_sh_unsets_real_model_env(self) -> None:
        text = Path("scripts/verify.sh").read_text(encoding="utf-8")
        self.assertIn("export OPENAI_MODEL=mock", text)
        self.assertIn("unset OPENAI_API_KEY OPENAI_BASE_URL", text)

    def test_debate_smoke_creates_snapshot_block(self) -> None:
        text = Path("scripts/debate_smoke.sh").read_text(encoding="utf-8")
        self.assertIn("outputs/debate/snapshots/${ts}", text)
        self.assertIn("Snapshot saved: $snap", text)


if __name__ == "__main__":
    unittest.main()
