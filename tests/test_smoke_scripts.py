import unittest
from pathlib import Path


class SmokeScriptTests(unittest.TestCase):
    def test_verify_sh_unsets_real_model_env(self) -> None:
        text = Path("scripts/verify.sh").read_text(encoding="utf-8")
        self.assertIn("export OPENAI_MODEL=mock", text)
        self.assertIn("unset OPENAI_API_KEY OPENAI_BASE_URL", text)
        self.assertIn("PLANNER_API_KEY PLANNER_BASE_URL PLANNER_MODEL", text)
        self.assertIn("OPENAI_STREAM", text)

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
        """Iter 029: retry pruning moved from shell into src.book_runner."""
        text = Path("scripts/write_book.sh").read_text(encoding="utf-8")
        self.assertNotIn("prune_from_chapter", text)
        runner = Path("src/book_runner.py").read_text(encoding="utf-8")
        self.assertIn("prune_from_chapter", runner)

    def test_write_book_prune_failure_aborts_instead_of_warning(self) -> None:
        """Iter 027 bug-sweep F2: a prune crash must abort the retry rather than
        be swallowed with a WARN — silent failure leaves the rejected draft's
        rolling summary in place and the retry inherits its polluted context."""
        text = Path("scripts/write_book.sh").read_text(encoding="utf-8")
        self.assertNotIn("[WARN] failed to prune rolling summary", text)
        self.assertNotIn("Aborting to avoid polluting the next retry", text)

    def test_write_book_requires_explicit_start_point_by_default(self) -> None:
        """Iter 027: long generation must not silently fall back to old anchors."""
        text = Path("scripts/write_book.sh").read_text(encoding="utf-8")
        self.assertIn('REQUIRE_START_POINT="1"', text)
        self.assertIn("--start-point", text)
        self.assertIn("--allow-missing-start-point", text)
        self.assertIn("write-book", text)

    def test_true_smoke_scripts_require_confirmation_gate(self) -> None:
        for name in ("debate_smoke.sh", "write_smoke.sh", "real_smoke.sh"):
            text = Path(f"scripts/{name}").read_text(encoding="utf-8")
            self.assertIn("CONFIRM_REAL_MODEL_SMOKE", text)
            self.assertIn("--confirm-real-smoke", text)
            self.assertIn("exit 64", text)

    def test_drive_book_sh_accepts_book_flag(self) -> None:
        """iter 052: 驱动器包装脚本沿用 iter017 的 --book / WORKSPACE_NAME 契约。"""
        text = Path("scripts/drive_book.sh").read_text(encoding="utf-8")
        self.assertIn("--book", text)
        self.assertIn("WORKSPACE_NAME", text)

    def test_drive_book_sh_requires_confirmation_gate(self) -> None:
        """iter 052: start/resume 必须有真模型确认闸，并映射到 --confirm-real-run。"""
        text = Path("scripts/drive_book.sh").read_text(encoding="utf-8")
        self.assertIn("CONFIRM_REAL_MODEL_SMOKE", text)
        self.assertIn("--confirm-real-smoke", text)
        self.assertIn("exit 64", text)
        self.assertIn("--confirm-real-run", text)

    def test_watchdog_sh_driver_mode_heartbeat_and_abort_marker(self) -> None:
        """iter 076 HIGH#4: watchdog --driver 读心跳 epoch 判活（llm mtime 兜底），
        abort 前写 watchdog_abort.json 供 supervisor 区分 watchdog 杀/人工 stop。"""
        text = Path("scripts/watchdog.sh").read_text(encoding="utf-8")
        self.assertIn("--driver", text)
        self.assertIn("driver_heartbeat.json", text)
        self.assertIn("watchdog_abort.json", text)
        self.assertIn("write_abort_marker", text)
        self.assertIn("driver.pid", text)          # driver 模式 pid 自动回退
        self.assertIn("json_int_field", text)      # 零 jq 依赖的字段提取
        # legacy 模式默认阈值不变（300/360）
        self.assertIn("WARN_AFTER:-300", text)
        self.assertIn("ABORT_AFTER:-360", text)
        # 审查 B M2 / A5b：driver 模式 TERM→宽限→SIGKILL 升级 + abort 后留场
        # （abort_armed 缴械/上膛），不再一发即退。
        self.assertIn("kill -KILL", text)
        self.assertIn("abort_armed", text)
        # 审查 B L7：kill 前校验目标确实是 drive-book 进程（pid 复用保险）
        self.assertIn("pid_is_driver", text)

    def test_drive_book_supervised_sh_contract(self) -> None:
        """iter 076 HIGH#5: supervisor 必须有确认闸、禁 --detach、退避与上限、
        决策表关键分支（budget/blocked 终态、pause_after_segment 尊重、标记消费）。"""
        text = Path("scripts/drive_book_supervised.sh").read_text(encoding="utf-8")
        self.assertIn("CONFIRM_REAL_MODEL_SMOKE", text)
        self.assertIn("--confirm-real-smoke", text)
        self.assertIn("exit 64", text)
        self.assertIn("--confirm-real-run", text)
        self.assertIn("--book", text)
        self.assertIn("WORKSPACE_NAME", text)
        self.assertIn("--detach is incompatible", text)
        self.assertIn("SUPERVISE_MAX_RESTARTS", text)
        self.assertIn("SUPERVISE_BACKOFF_BASE", text)
        self.assertIn("watchdog_abort.json", text)
        self.assertIn("pause_after_segment", text)
        self.assertIn("caffeinate", text)
        self.assertIn("GIVING UP", text)
        # 审查 B M1：总轮次硬顶（不随存活归零重置）+ 真模型无预算 WARN
        self.assertIn("SUPERVISE_MAX_ROUNDS", text)
        self.assertIn("without --budget-cny", text)
        # 审查 B L9：supervisor 互斥 pid 文件
        self.assertIn("supervise.pid", text)


if __name__ == "__main__":
    unittest.main()
