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

    def test_write_book_retry_prunes_rolling_summary(self) -> None:
        """Iter 027: rejected chapter retries must not keep failed rolling state."""
        text = Path("scripts/write_book.sh").read_text(encoding="utf-8")
        self.assertIn("prune_from_chapter", text)
        self.assertIn("failed to prune rolling summary", text)

    def test_write_book_prune_failure_aborts_instead_of_warning(self) -> None:
        """Iter 027 bug-sweep F2: a prune crash must abort the retry rather than
        be swallowed with a WARN — silent failure leaves the rejected draft's
        rolling summary in place and the retry inherits its polluted context."""
        text = Path("scripts/write_book.sh").read_text(encoding="utf-8")
        self.assertNotIn("[WARN] failed to prune rolling summary", text)
        self.assertIn("Aborting to avoid polluting the next retry", text)

    def test_write_book_requires_explicit_start_point_by_default(self) -> None:
        """Iter 027: long generation must not silently fall back to old anchors."""
        text = Path("scripts/write_book.sh").read_text(encoding="utf-8")
        self.assertIn('REQUIRE_START_POINT="1"', text)
        self.assertIn("--start-point", text)
        self.assertIn("--allow-missing-start-point", text)
        self.assertIn("chapter_plan.json has no start_chapter_id metadata", text)
        self.assertIn("Plan start point:", text)


if __name__ == "__main__":
    unittest.main()
