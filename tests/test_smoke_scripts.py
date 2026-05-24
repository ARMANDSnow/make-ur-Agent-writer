import unittest
from pathlib import Path


class SmokeScriptTests(unittest.TestCase):
    def test_verify_sh_unsets_real_model_env(self) -> None:
        text = Path("scripts/verify.sh").read_text(encoding="utf-8")
        self.assertIn("export OPENAI_MODEL=mock", text)
        self.assertIn("unset OPENAI_API_KEY OPENAI_BASE_URL", text)

    def test_debate_smoke_creates_snapshot_block(self) -> None:
        text = Path("scripts/debate_smoke.sh").read_text(encoding="utf-8")
        # iter 017: snapshot path is now derived from per-workspace
        # DEBATE_DIR (legacy mode still resolves to outputs/debate/).
        self.assertIn("snapshots/${ts}", text)
        self.assertIn("Snapshot saved: $snap", text)

    def test_smoke_scripts_accept_book_flag(self) -> None:
        """Iter 017: all smoke scripts must accept --book / $WORKSPACE_NAME."""
        for name in ("debate_smoke.sh", "write_smoke.sh", "real_smoke.sh", "write_book.sh", "verify.sh"):
            text = Path(f"scripts/{name}").read_text(encoding="utf-8")
            self.assertIn("--book", text, f"{name} must accept --book flag")
            self.assertIn("WORKSPACE_NAME", text, f"{name} must honor WORKSPACE_NAME env var")

    def test_write_book_sh_dropped_manual_proposal_idx_placeholder(self) -> None:
        """Iter 019: the human-targeted '--proposal-idx <comma-list>'
        placeholder string in write_book.sh must be gone — the script now
        invokes apply-advance with --auto-apply --confirm unattended.
        """
        text = Path("scripts/write_book.sh").read_text(encoding="utf-8")
        self.assertNotIn("--proposal-idx <comma-list>", text)


if __name__ == "__main__":
    unittest.main()
