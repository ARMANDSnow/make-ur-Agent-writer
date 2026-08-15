import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts/check_agent_harness.py"
VERIFY = ROOT / "scripts/verify.sh"
EVIDENCE_WRITER = ROOT / "scripts/write_acceptance.py"
ISOLATED_CLI = ROOT / "scripts/run_isolated_cli.py"
SECTIONS = (
    "Context",
    "Plan",
    "Acceptance",
    "Implementation Notes",
    "Acceptance Result",
    "文件变更汇总",
    "不在本轮范围",
    "Notes",
)


class AgentHarnessCheckerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "docs/iterations").mkdir(parents=True)
        (self.root / "docs/reference.md").write_text(
            "tracked implementation reference\n", encoding="utf-8"
        )
        (self.root / ".agents/skills/iter-start").mkdir(parents=True)
        (self.root / ".agents/skills/iter-finish").mkdir(parents=True)
        (self.root / "AGENTS.md").write_text(
            "# Agent rules\n\n## 标准验证\n\n```bash\nbash scripts/verify.sh\n```\n",
            encoding="utf-8",
        )
        (self.root / "README.md").write_text(
            "# Project\n\n## 快速开始\n\n```bash\nbash scripts/verify.sh\n```\n\n"
            "最近一次更新：**iter 101**（2026-07-14，收官）。\n",
            encoding="utf-8",
        )
        (self.root / "docs/AGENT_HANDOFF.md").write_text(
            "# Handoff\n\n| 项 | 当前值 |\n|---|---|\n"
            "| 更新时间 | iter 101，2026-07-14 收官 |\n",
            encoding="utf-8",
        )
        (self.root / "docs/iterations/README.md").write_text(
            "# Iteration Log\n\n## Index\n\n"
            "1. [Iteration 100 - Previous](./iteration_100_previous.md)\n"
            "2. [Iteration 101 - Current](./iteration_101_current.md)\n",
            encoding="utf-8",
        )
        (self.root / "docs/iterations/iteration_100_previous.md").write_text(
            "# Historical document\n\n## Context\nLegacy shape is preserved.\n",
            encoding="utf-8",
        )
        latest = "# Iteration 101 - Current\n\n" + "\n\n".join(
            f"## {name}\ncomplete" for name in SECTIONS
        )
        (self.root / "docs/iterations/iteration_101_current.md").write_text(
            latest + "\n", encoding="utf-8"
        )
        (self.root / ".agents/skills/iter-start/SKILL.md").write_text(
            "---\nname: iter-start\ndescription: test\n---\n"
            "8 段 docs/iterations/README.md 不要 commit 不要 push "
            "Implementation Context Review Context Knowledge Promotion\n",
            encoding="utf-8",
        )
        (self.root / ".agents/skills/iter-finish/SKILL.md").write_text(
            "---\nname: iter-finish\ndescription: test\n---\n"
            "聚焦 只读 bash scripts/verify.sh 就地更新 不得新增逐轮 "
            "Review Context Knowledge Promotion git diff --check HEAD\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            [
                "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "-qm", "accepted baseline",
            ],
            cwd=self.root,
            check=True,
        )
        accepted = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True,
            capture_output=True, check=True,
        ).stdout.strip()
        handoff = self.root / "docs/AGENT_HANDOFF.md"
        handoff.write_text(
            handoff.read_text(encoding="utf-8")
            + f"| Accepted implementation commit | `{accepted}` |\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def run_checker(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), "--root", str(self.root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def configure_legacy_111(self) -> None:
        readme = self.root / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("iter 101", "iter 111"),
            encoding="utf-8",
        )
        handoff = self.root / "docs/AGENT_HANDOFF.md"
        handoff.write_text(
            handoff.read_text(encoding="utf-8").replace("iter 101", "iter 111"),
            encoding="utf-8",
        )
        (self.root / "docs/iterations/README.md").write_text(
            "# Iteration Log\n\n## Index\n\n"
            "1. [Iteration 111 - Legacy](./iteration_111_legacy.md)\n",
            encoding="utf-8",
        )
        legacy = "# Iteration 111 - Legacy\n\n" + "\n\n".join(
            f"## {name}\n"
            + (
                "- **A111-01**: promise"
                if name == "Acceptance"
                else "- **A111-01**: passed"
                if name == "Acceptance Result"
                else "complete"
            )
            for name in SECTIONS
        )
        (self.root / "docs/iterations/iteration_111_legacy.md").write_text(
            legacy + "\n", encoding="utf-8"
        )

    def configure_structured_112(
        self,
        *,
        active: bool = True,
        implementation_context: str | None = None,
        review_context: str | None = None,
        knowledge_promotion: str | None = None,
    ) -> Path:
        self.configure_legacy_111()
        accepted = "111" if active else "112"
        readme = self.root / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("iter 111", f"iter {accepted}"),
            encoding="utf-8",
        )
        handoff = self.root / "docs/AGENT_HANDOFF.md"
        handoff.write_text(
            handoff.read_text(encoding="utf-8").replace(
                "iter 111", f"iter {accepted}"
            ),
            encoding="utf-8",
        )
        index = self.root / "docs/iterations/README.md"
        index.write_text(
            index.read_text(encoding="utf-8")
            + "2. [Iteration 112 - Structured](./iteration_112_structured.md)\n",
            encoding="utf-8",
        )
        implementation_context = implementation_context or (
            "### Implementation Context\n"
            "- `must_read`: `docs/reference.md`\n"
            "- `expected_changes`: `scripts/future_checker.py`\n"
            "- `do_not_touch`: `.env`; private inputs"
        )
        review_context = review_context or (
            "### Review Context\n"
            "- `correctness_behavior`: check legacy and structured behavior\n"
            "- `security_boundary`: check paths fail closed\n"
            "- `extra_risk_view`: `none`"
        )
        if knowledge_promotion is None:
            if active:
                knowledge_promotion = (
                    "### Knowledge Promotion\n"
                    "- `decision`: `<pending>`\n"
                    "- `destination`: `<pending>`\n"
                    "- `reason`: `<pending>`"
                )
            else:
                knowledge_promotion = (
                    "### Knowledge Promotion\n"
                    "- `decision`: `none`\n"
                    "- `destination`: `none`\n"
                    "- `reason`: existing workflow authority already covers the lesson"
                )
        bodies = {
            "Context": "structured fixture",
            "Plan": implementation_context,
            "Acceptance": review_context + "\n\n- **A112-01**: structured promise",
            "Implementation Notes": "complete",
            "Acceptance Result": (
                ("pending" if active else "- **A112-01**: passed")
                + "\n\n"
                + knowledge_promotion
            ),
            "文件变更汇总": "complete",
            "不在本轮范围": "complete",
            "Notes": "complete",
        }
        text = "# Iteration 112 - Structured\n\n" + "\n\n".join(
            f"## {name}\n{bodies[name]}" for name in SECTIONS
        )
        path = self.root / "docs/iterations/iteration_112_structured.md"
        path.write_text(text + "\n", encoding="utf-8")
        return path

    def append_active_113(self) -> Path:
        index = self.root / "docs/iterations/README.md"
        index.write_text(
            index.read_text(encoding="utf-8")
            + "3. [Iteration 113 - Active](./iteration_113_active.md)\n",
            encoding="utf-8",
        )
        bodies = {
            "Context": "next active fixture",
            "Plan": (
                "### Implementation Context\n"
                "- `must_read`: `docs/reference.md`\n"
                "- `expected_changes`: `scripts/future_113.py`\n"
                "- `do_not_touch`: private inputs"
            ),
            "Acceptance": (
                "### Review Context\n"
                "- `correctness_behavior`: check accepted predecessor closure\n"
                "- `security_boundary`: check paths fail closed\n"
                "- `extra_risk_view`: `none`\n\n"
                "- **A113-01**: active promise"
            ),
            "Implementation Notes": "pending",
            "Acceptance Result": (
                "pending\n\n### Knowledge Promotion\n"
                "- `decision`: `<pending>`\n"
                "- `destination`: `<pending>`\n"
                "- `reason`: `<pending>`"
            ),
            "文件变更汇总": "pending",
            "不在本轮范围": "complete",
            "Notes": "complete",
        }
        text = "# Iteration 113 - Active\n\n" + "\n\n".join(
            f"## {name}\n{bodies[name]}" for name in SECTIONS
        )
        path = self.root / "docs/iterations/iteration_113_active.md"
        path.write_text(text + "\n", encoding="utf-8")
        return path

    def test_valid_fixture_passes_without_rewriting_legacy_iteration(self) -> None:
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted iter 101", result.stdout)

    def test_iter111_legacy_shape_remains_valid(self) -> None:
        self.configure_legacy_111()
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted iter 111, active iter none", result.stdout)

    def test_active_iter112_structured_context_passes(self) -> None:
        self.configure_structured_112()
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted iter 111, active iter 112", result.stdout)

    def test_iter112_requires_unique_blocks_in_the_correct_sections(self) -> None:
        path = self.configure_structured_112()
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "## Plan\n### Implementation Context",
                "## Plan\n### Wrong Context",
            )
            + "\n### Implementation Context\n- `must_read`: `docs/reference.md`\n"
            "- `expected_changes`: `future.py`\n- `do_not_touch`: private\n",
            encoding="utf-8",
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Implementation Context must appear exactly once under ## Plan", result.stderr)

    def test_iter112_rejects_missing_duplicate_and_pending_required_fields(self) -> None:
        cases = {
            "missing": "### Implementation Context\n"
            "- `expected_changes`: `future.py`\n- `do_not_touch`: private",
            "empty": "### Implementation Context\n"
            "- `must_read`: \n"
            "- `expected_changes`: `future.py`\n- `do_not_touch`: private",
            "duplicate": "### Implementation Context\n"
            "- `must_read`: `docs/reference.md`\n- `must_read`: `README.md`\n"
            "- `expected_changes`: `future.py`\n- `do_not_touch`: private",
            "pending": "### Implementation Context\n"
            "- `must_read`: `<pending>`\n"
            "- `expected_changes`: `future.py`\n- `do_not_touch`: private",
        }
        for name, block in cases.items():
            with self.subTest(name=name):
                self.configure_structured_112(implementation_context=block)
                result = self.run_checker()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Implementation Context field 'must_read'", result.stderr)

    def test_iter112_ignores_fields_spoofed_inside_code_fences(self) -> None:
        block = (
            "### Implementation Context\n"
            "```markdown\n- `must_read`: `docs/reference.md`\n```\n"
            "- `expected_changes`: `future.py`\n- `do_not_touch`: private"
        )
        self.configure_structured_112(implementation_context=block)
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Implementation Context field 'must_read'", result.stderr)

    def test_iter112_rejects_duplicate_structured_block(self) -> None:
        path = self.configure_structured_112()
        text = path.read_text(encoding="utf-8")
        duplicate = (
            "\n\n### Implementation Context\n"
            "- `must_read`: `docs/reference.md`\n"
            "- `expected_changes`: `future.py`\n"
            "- `do_not_touch`: private"
        )
        path.write_text(
            text.replace("## Acceptance\n", duplicate + "\n\n## Acceptance\n"),
            encoding="utf-8",
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("found 2 total", result.stderr)

    def test_fenced_h2_example_does_not_replace_real_parent_section(self) -> None:
        path = self.configure_structured_112()
        text = path.read_text(encoding="utf-8")
        fenced = (
            "```markdown\n## Plan\n### Implementation Context\n"
            "- `must_read`: `/tmp/private`\n```\n\n"
        )
        path.write_text(text.replace("## Plan\n", fenced + "## Plan\n"), encoding="utf-8")
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_fenced_h2_cannot_hide_a_duplicate_h3(self) -> None:
        path = self.configure_structured_112()
        text = path.read_text(encoding="utf-8")
        hidden = (
            "\n```markdown\n## Fake\n```\n"
            "### Implementation Context\n"
            "- `must_read`: `docs/reference.md`\n"
            "- `expected_changes`: `future.py`\n"
            "- `do_not_touch`: private\n"
        )
        path.write_text(text.replace("## Acceptance\n", hidden + "\n## Acceptance\n"), encoding="utf-8")
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("found 2 total", result.stderr)

    def test_non_closing_fence_text_does_not_expose_fake_headings(self) -> None:
        path = self.configure_structured_112()
        text = path.read_text(encoding="utf-8")
        fenced = "```markdown\n## Plan\n```not-a-close\n"
        path.write_text(text.replace("## Plan\n", fenced + "## Plan\n"), encoding="utf-8")
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly the 8 canonical sections", result.stderr)

    def test_backtick_in_fence_info_cannot_create_a_checker_renderer_split(self) -> None:
        malicious = (
            "```bad`\n"
            "### Implementation Context\n"
            "- `must_read`: `/tmp/private.md`\n"
            "- `expected_changes`: `future.py`\n"
            "- `do_not_touch`: private\n"
            "```\n"
            "### Implementation Context\n"
            "- `must_read`: `docs/reference.md`\n"
            "- `expected_changes`: `future.py`\n"
            "- `do_not_touch`: private\n"
            "```"
        )
        self.configure_structured_112(implementation_context=malicious)
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must_read path", result.stderr)

    def test_indented_or_closing_marker_h3_cannot_hide_a_duplicate(self) -> None:
        for heading in (
            " ### Implementation Context",
            "### Implementation Context ###",
        ):
            with self.subTest(heading=heading):
                path = self.configure_structured_112()
                duplicate = (
                    f"\n{heading}\n"
                    "- `must_read`: `/tmp/private.md`\n"
                    "- `expected_changes`: `future.py`\n"
                    "- `do_not_touch`: private\n"
                )
                text = path.read_text(encoding="utf-8")
                path.write_text(
                    text.replace("## Acceptance\n", duplicate + "\n## Acceptance\n"),
                    encoding="utf-8",
                )
                result = self.run_checker()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("found 2 total", result.stderr)

    def test_indented_markdown_field_cannot_hide_a_duplicate(self) -> None:
        block = (
            "### Implementation Context\n"
            " - `must_read`: `.env`\n"
            "- `must_read`: `docs/reference.md`\n"
            "- `expected_changes`: `future.py`\n"
            "- `do_not_touch`: private"
        )
        self.configure_structured_112(implementation_context=block)
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("field 'must_read' must appear exactly once", result.stderr)

    def test_iter112_rejects_unsafe_or_missing_must_read_paths(self) -> None:
        cases = {
            "absolute": "`/tmp/private.md`",
            "traversal": "`../private.md`",
            "dotenv": "`.env`",
            "private_root": "`data/private.md`",
            "missing": "`docs/missing.md`",
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                block = (
                    "### Implementation Context\n"
                    f"- `must_read`: {value}\n"
                    "- `expected_changes`: `scripts/future_checker.py`\n"
                    "- `do_not_touch`: `.env`; private inputs"
                )
                self.configure_structured_112(implementation_context=block)
                result = self.run_checker()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Implementation Context must_read path", result.stderr)

    def test_iter112_allows_nonexistent_expected_change_path(self) -> None:
        self.configure_structured_112()
        self.assertFalse((self.root / "scripts/future_checker.py").exists())
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_iter112_rejects_unsafe_expected_change_paths(self) -> None:
        for value in (
            "`/tmp/future.py`",
            "`../future.py`",
            "`outputs/future.py`",
            "`Data/future.py`",
            "`C:relative.py`",
            "`.git/config`",
        ):
            with self.subTest(value=value):
                block = (
                    "### Implementation Context\n"
                    "- `must_read`: `docs/reference.md`\n"
                    f"- `expected_changes`: {value}\n"
                    "- `do_not_touch`: protected paths"
                )
                self.configure_structured_112(implementation_context=block)
                result = self.run_checker()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Implementation Context expected_changes path", result.stderr)

    def test_iter112_requires_canonical_path_list_separators(self) -> None:
        for value in (
            "`docs/reference.md` `README.md`",
            "`docs/reference.md`,,,,`README.md`",
            ",`docs/reference.md`",
            "`docs/reference.md`,",
        ):
            with self.subTest(value=value):
                block = (
                    "### Implementation Context\n"
                    f"- `must_read`: {value}\n"
                    "- `expected_changes`: `future.py`\n"
                    "- `do_not_touch`: protected paths"
                )
                self.configure_structured_112(implementation_context=block)
                result = self.run_checker()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("comma-separated list", result.stderr)

    def test_must_read_requires_a_tracked_regular_file(self) -> None:
        untracked = self.root / "docs/untracked-context.md"
        untracked.write_text("user-owned\n", encoding="utf-8")
        block = (
            "### Implementation Context\n"
            "- `must_read`: `docs/untracked-context.md`\n"
            "- `expected_changes`: `future.py`\n"
            "- `do_not_touch`: user-owned docs"
        )
        self.configure_structured_112(implementation_context=block)
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Git-tracked regular file", result.stderr)

    def test_context_paths_reject_symlinks_and_embedded_nul(self) -> None:
        (self.root / "data").mkdir()
        (self.root / "data/private.md").write_text("synthetic private\n", encoding="utf-8")
        alias = self.root / "docs/private-alias.md"
        alias.symlink_to("../data/private.md")
        (self.root / "docs/existing-dir").mkdir()
        for value in (
            "`docs/private-alias.md`",
            "`loop.md`",
            "`bad\x00path.md`",
            "`docs/existing-dir`",
        ):
            with self.subTest(value=value):
                if value == "`loop.md`":
                    loop = self.root / "loop.md"
                    if not loop.exists() and not loop.is_symlink():
                        loop.symlink_to("loop.md")
                block = (
                    "### Implementation Context\n"
                    "- `must_read`: `docs/reference.md`\n"
                    f"- `expected_changes`: {value}\n"
                    "- `do_not_touch`: protected paths"
                )
                self.configure_structured_112(implementation_context=block)
                result = self.run_checker()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Implementation Context expected_changes path", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_iter112_requires_both_base_review_views(self) -> None:
        review = (
            "### Review Context\n"
            "- `correctness_behavior`: check behavior\n"
            "- `extra_risk_view`: `none`"
        )
        self.configure_structured_112(review_context=review)
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Review Context field 'security_boundary'", result.stderr)

    def test_accepted_iter112_requires_complete_knowledge_promotion(self) -> None:
        self.configure_structured_112(
            active=False,
            knowledge_promotion=(
                "### Knowledge Promotion\n"
                "- `decision`: `<pending>`\n"
                "- `destination`: `<pending>`\n"
                "- `reason`: `<pending>`"
            ),
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Knowledge Promotion must be either entirely pending", result.stderr)

    def test_accepted_iter112_accepts_none_and_allowed_promotion(self) -> None:
        self.configure_structured_112(active=False)
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

        self.configure_structured_112(
            active=False,
            knowledge_promotion=(
                "### Knowledge Promotion\n"
                "- `decision`: `promoted`\n"
                "- `destination`: `AGENTS.md`, `.agents/skills/iter-finish/SKILL.md`\n"
                "- `reason`: stable workflow rule"
            ),
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepted_iter112_rejects_invalid_promotion_target(self) -> None:
        self.configure_structured_112(
            active=False,
            knowledge_promotion=(
                "### Knowledge Promotion\n"
                "- `decision`: `promoted`\n"
                "- `destination`: `README.md`\n"
                "- `reason`: invalid authority"
            ),
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not an allowed authority document", result.stderr)

    def test_accepted_iter112_rejects_untracked_product_promotion_target(self) -> None:
        product = self.root / "docs/product"
        product.mkdir()
        (product / "journal.md").write_text("untracked journal\n", encoding="utf-8")
        self.configure_structured_112(
            active=False,
            knowledge_promotion=(
                "### Knowledge Promotion\n"
                "- `decision`: `promoted`\n"
                "- `destination`: `docs/product/journal.md`\n"
                "- `reason`: must not create a second knowledge store"
            ),
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Git-tracked regular file", result.stderr)

    def test_active_next_iteration_does_not_hide_pending_accepted_promotion(self) -> None:
        self.configure_structured_112(
            active=False,
            knowledge_promotion=(
                "### Knowledge Promotion\n"
                "- `decision`: `<pending>`\n"
                "- `destination`: `<pending>`\n"
                "- `reason`: `<pending>`"
            ),
        )
        self.append_active_113()
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Knowledge Promotion must be either entirely pending", result.stderr)

    def test_active_next_iteration_does_not_hide_accepted_id_drift(self) -> None:
        path = self.configure_structured_112(active=False)
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "- **A112-01**: passed\n\n### Knowledge Promotion",
                "closed without ID\n\n### Knowledge Promotion",
            ),
            encoding="utf-8",
        )
        self.append_active_113()
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("accepted indexed iteration Acceptance and Result ID sets must match", result.stderr)

    def test_latest_iteration_missing_section_fails(self) -> None:
        path = self.root / "docs/iterations/iteration_101_current.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("## Notes\ncomplete\n", ""),
            encoding="utf-8",
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly the 8 canonical sections", result.stderr)

    def test_missing_index_target_fails(self) -> None:
        index = self.root / "docs/iterations/README.md"
        index.write_text(
            index.read_text(encoding="utf-8").replace(
                "iteration_100_previous.md", "iteration_100_missing.md"
            ),
            encoding="utf-8",
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("index target is missing", result.stderr)

    def test_obsolete_skill_workflow_fails(self) -> None:
        skill = self.root / ".agents/skills/iter-finish/SKILL.md"
        skill.write_text(
            skill.read_text(encoding="utf-8") + "追加 AGENT_HANDOFF Phase Status\n",
            encoding="utf-8",
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("obsolete workflow text", result.stderr)

    def test_readme_and_handoff_iteration_drift_fails(self) -> None:
        readme = self.root / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("iter 101", "iter 100"),
            encoding="utf-8",
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("accepted iteration mismatch", result.stderr)

    def test_nonconsecutive_index_ordinals_fail(self) -> None:
        index = self.root / "docs/iterations/README.md"
        index.write_text(
            index.read_text(encoding="utf-8").replace(
                "2. [Iteration 101", "3. [Iteration 101"
            ),
            encoding="utf-8",
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ordinals must be consecutive", result.stderr)

    def test_one_active_next_iteration_is_allowed(self) -> None:
        index = self.root / "docs/iterations/README.md"
        index.write_text(
            index.read_text(encoding="utf-8")
            + "3. [Iteration 102 - Active](./iteration_102_active.md)\n",
            encoding="utf-8",
        )
        active = "# Iteration 102 - Active\n\n" + "\n\n".join(
            f"## {name}\n" + ("- `A102-01`: active promise" if name == "Acceptance" else "<待实施>")
            for name in SECTIONS
        )
        (self.root / "docs/iterations/iteration_102_active.md").write_text(
            active + "\n", encoding="utf-8"
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted iter 101, active iter 102", result.stdout)

    def test_implementation_drift_without_active_iteration_fails(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "src/新 file.py").write_text("VALUE = 1\n", encoding="utf-8")
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("implementation drift", result.stderr)

    def test_untracked_docs_report_does_not_count_as_implementation_drift(self) -> None:
        (self.root / "docs/体检 report.md").write_text("read-only report\n", encoding="utf-8")
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_committed_unindexed_iteration_doc_is_not_allowed_closure(self) -> None:
        extra = self.root / "docs/iterations/iteration_101_extra.md"
        extra.write_text("# unindexed\n", encoding="utf-8")
        subprocess.run(["git", "add", str(extra)], cwd=self.root, check=True)
        subprocess.run(
            [
                "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "-qm", "unindexed docs drift",
            ],
            cwd=self.root,
            check=True,
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("iteration_101_extra.md", result.stderr)

    def test_active_iteration_requires_matching_acceptance_id(self) -> None:
        index = self.root / "docs/iterations/README.md"
        index.write_text(
            index.read_text(encoding="utf-8")
            + "3. [Iteration 102 - Active](./iteration_102_active.md)\n",
            encoding="utf-8",
        )
        active = "# Iteration 102 - Active\n\n" + "\n\n".join(
            f"## {name}\n" + ("- `A999-01`: wrong" if name == "Acceptance" else "pending")
            for name in SECTIONS
        )
        (self.root / "docs/iterations/iteration_102_active.md").write_text(
            active + "\n", encoding="utf-8"
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("match its iteration", result.stderr)

    def test_invalid_latest_target_is_not_read_after_boundary_failure(self) -> None:
        private = self.root / "private.md"
        private.write_text("## SECRET-PRIVATE-HEADING\n", encoding="utf-8")
        index = self.root / "docs/iterations/README.md"
        index.write_text(
            index.read_text(encoding="utf-8").replace(
                "iteration_101_current.md",
                "iteration_101_escape/../../../private.md",
            ),
            encoding="utf-8",
        )
        result = self.run_checker()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("target escapes docs/iterations", result.stderr)
        self.assertNotIn("SECRET-PRIVATE-HEADING", result.stderr)
        self.assertNotIn("exactly the 8 canonical sections", result.stderr)


class IsolatedCliTests(unittest.TestCase):
    def _root(self, base: Path) -> Path:
        root = base / "isolated"
        root.mkdir(parents=True)
        (root / ".dragon-raja-verify-owned").write_text("owned\n", encoding="utf-8")
        return root

    def _fake_project(self, base: Path) -> Path:
        project = base / "project"
        (project / "scripts").mkdir(parents=True)
        (project / "src").mkdir()
        shutil.copy2(ISOLATED_CLI, project / "scripts/run_isolated_cli.py")
        (project / "src/__init__.py").write_text("", encoding="utf-8")
        (project / "src/paths.py").write_text(
            "from pathlib import Path\nWORKSPACE_DIR = Path(__file__).parents[1] / 'workspaces'\n",
            encoding="utf-8",
        )
        (project / "main.py").write_text(
            "import os\nfrom src import paths\nfrom pathlib import Path\n"
            "target = paths.WORKSPACE_DIR / os.environ['WORKSPACE_NAME'] / 'observed.txt'\n"
            "target.parent.mkdir(parents=True, exist_ok=True)\n"
            "target.write_text(' '.join(__import__('sys').argv[1:]), encoding='utf-8')\n",
            encoding="utf-8",
        )
        return project

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "OPENAI_MODEL": "mock",
                "PLANNER_MODEL": "mock",
                "LITELLM_LOCAL_MODEL_COST_MAP": "true",
                "DRAGON_RAJA_SKIP_DOTENV": "1",
                "PYTHON_DOTENV_DISABLED": "1",
                "WORKSPACE_NAME": "private-sentinel",
                "BOOK": "private-fallback",
            }
        )
        return env

    def test_wrapper_runs_normalize_inside_isolated_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            project = self._fake_project(base)
            result = subprocess.run(
                [
                    sys.executable, str(project / "scripts/run_isolated_cli.py"),
                    "--workspace-root", str(root),
                    "normalize",
                ],
                cwd=project,
                env=self._env(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / "verify/observed.txt").is_file())
            self.assertFalse((project / "workspaces/private-sentinel").exists())
            self.assertFalse((project / "workspaces/verify").exists())

    def test_wrapper_rejects_book_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._root(base)
            project = self._fake_project(base)
            result = subprocess.run(
                [
                    sys.executable, str(project / "scripts/run_isolated_cli.py"),
                    "--workspace-root", str(root),
                    "status", "--book", "legacy",
                ],
                cwd=project,
                env=self._env(),
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("must not override", result.stderr)
            self.assertFalse((root / "verify/observed.txt").exists())
            self.assertFalse((project / "workspaces").exists())


class VerifyHarnessTests(unittest.TestCase):
    def assert_only_known_platform_tmp_entries(self, tmpdir: Path) -> None:
        self.assertEqual(list(tmpdir.iterdir()), [])

    def test_xcrun_db_name_is_not_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "xcrun_db"
            marker.mkdir()
            with self.assertRaises(AssertionError):
                self.assert_only_known_platform_tmp_entries(Path(tmp))

    def test_verify_cleanup_preserves_unowned_tmp_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            self.make_fixture(root)
            tmpdir = Path(tmp) / "caller-tmp"
            tmpdir.mkdir()
            sibling = tmpdir / "unowned-sibling"
            sibling.mkdir()
            (sibling / "sentinel").write_text("keep", encoding="utf-8")
            env = os.environ.copy()
            env["TMPDIR"] = str(tmpdir)
            result = subprocess.run(
                ["bash", "scripts/verify.sh"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((sibling / "sentinel").read_text(encoding="utf-8"), "keep")
            self.assertEqual(list(tmpdir.iterdir()), [sibling])

    def test_acceptance_start_failure_cleans_owned_root_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            self.make_fixture(root)
            tmpdir = Path(tmp) / "caller-tmp"
            tmpdir.mkdir()
            sibling = tmpdir / "unowned-sibling"
            sibling.mkdir()
            env = os.environ.copy()
            env["TMPDIR"] = str(tmpdir)
            env["FAKE_ACCEPTANCE_START_FAIL"] = "1"
            result = subprocess.run(
                ["bash", "scripts/verify.sh"], cwd=root, env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(tmpdir.iterdir()), [sibling])
            self.assertFalse((root / "outputs/harness/acceptance.json").exists())

    def test_acceptance_finish_failure_cleans_owned_root_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            self.make_fixture(root)
            tmpdir = Path(tmp) / "caller-tmp"
            tmpdir.mkdir()
            sibling = tmpdir / "unowned-sibling"
            sibling.mkdir()
            env = os.environ.copy()
            env["TMPDIR"] = str(tmpdir)
            env["FAKE_ACCEPTANCE_FINISH_FAIL"] = "1"
            result = subprocess.run(
                ["bash", "scripts/verify.sh"], cwd=root, env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("failed to finalize", result.stderr)
            self.assertEqual(list(tmpdir.iterdir()), [sibling])

    def make_fixture(self, root: Path) -> None:
        (root / "scripts").mkdir()
        (root / ".venv/bin").mkdir(parents=True)
        (root / ".gitignore").write_text(
            "outputs/\ninvocations.log\ntmp/\n.pycache/\n", encoding="utf-8"
        )
        shutil.copy2(VERIFY, root / "scripts/verify.sh")
        shutil.copy2(EVIDENCE_WRITER, root / "scripts/write_acceptance.py")
        shutil.copy2(ISOLATED_CLI, root / "scripts/run_isolated_cli.py")
        (root / "scripts/check_novel_only_boundary.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8"
        )
        fake_python = root / ".venv/bin/python3"
        real_python = shlex.quote(sys.executable)
        fake_python.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            f"REAL_PYTHON={real_python}\n"
            "if [[ \"${1:-}\" == 'scripts/write_acceptance.py' ]]; then\n"
            "  if [[ \"${FAKE_ACCEPTANCE_START_FAIL:-}\" == '1' && \"${2:-}\" == 'start' ]]; then exit 17; fi\n"
            "  if [[ \"${FAKE_ACCEPTANCE_FINISH_FAIL:-}\" == '1' && \"${2:-}\" == 'finish' ]]; then exit 18; fi\n"
            "  exec \"$REAL_PYTHON\" \"$@\"\n"
            "fi\n"
            "ROOT=\"$(cd \"$(dirname \"$0\")/../..\" && pwd)\"\n"
            "{\n"
            "  printf 'ENV:%s:%s:%s ARGS:' \"${OPENAI_MODEL:-}\" \"${OPENAI_API_KEY:-}\" \"${DRAGON_RAJA_SKIP_DOTENV:-}\"\n"
            "  for arg in \"$@\"; do printf ' <%s>' \"$arg\"; done\n"
            "  printf '\\n'\n"
            "} >> \"$ROOT/invocations.log\"\n"
            "if [[ \"$*\" == *'-m unittest discover -s tests -v'* ]]; then\n"
            "  if [[ \"${FAKE_ZERO_TESTS:-}\" == '1' ]]; then\n"
            "    echo 'Ran 0 tests in 0.001s' >&2\n"
            "  else\n"
            "    echo 'Ran 7 tests in 0.001s' >&2\n"
            "    echo 'OK' >&2\n"
            "  fi\n"
            "fi\n",
            encoding="utf-8",
        )
        fake_python.chmod(0o755)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            [
                "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "-qm", "verify fixture",
            ],
            cwd=root,
            check=True,
        )

    def test_verify_writes_novel_only_schema_v3_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fixture(root)
            result = subprocess.run(
                ["bash", "scripts/verify.sh"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(
                (root / "outputs/harness/acceptance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["schema_version"], 3)
            self.assertEqual(evidence["verification_profile"], "canonical-novel-mock-offline")
            self.assertEqual(evidence["acceptance_level"], "mock-functional")
            self.assertEqual(evidence["status"], "passed")
            self.assertEqual(evidence["test_count"], 7)
            self.assertEqual(
                evidence["completed_steps"],
                [
                    "repository_state",
                    "harness_check",
                    "novel_only_boundary",
                    "py_compile",
                    "unittest",
                    "normalize",
                    "split",
                    "auto_pipeline",
                    "status",
                    "check_manifest",
                    "manifest_report",
                    "review_summary",
                    "check_reports",
                    "estimate_cost",
                    "preflight",
                ],
            )
            invocations = (root / "invocations.log").read_text(encoding="utf-8")
            self.assertEqual(invocations.count("<-m> <unittest> <discover>"), 1)



    def test_verify_rejects_arguments_before_writing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fixture(root)
            result = subprocess.run(
                ["bash", "scripts/verify.sh", "--book", "private"], cwd=root,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 64)
            self.assertFalse((root / "outputs/harness/acceptance.json").exists())

    def test_repository_check_rejects_untracked_code_but_allows_docs_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fixture(root)
            (root / "docs").mkdir()
            (root / "docs/体检 report.md").write_text("report\n", encoding="utf-8")
            allowed = subprocess.run(
                [
                    sys.executable, str(root / "scripts/write_acceptance.py"),
                    "check-repository", "--root", str(root),
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            (root / "integrations").mkdir()
            (root / "integrations/new adapter.py").write_text("VALUE = 1\n", encoding="utf-8")
            rejected = subprocess.run(
                [
                    sys.executable, str(root / "scripts/write_acceptance.py"),
                    "check-repository", "--root", str(root),
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("integrations/new adapter.py", rejected.stderr)




    def test_dirty_start_cannot_be_finalized_as_passed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fixture(root)
            (root / "src").mkdir()
            (root / "src/untracked.py").write_text("VALUE = 1\n", encoding="utf-8")
            start = subprocess.run(
                [
                    sys.executable, str(root / "scripts/write_acceptance.py"), "start",
                    "--root", str(root), "--python-runtime", "project_venv",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(start.returncode, 0, start.stderr)
            finish = subprocess.run(
                [
                    sys.executable, str(root / "scripts/write_acceptance.py"), "finish",
                    "--root", str(root), "--run-id", start.stdout.strip(),
                    "--status", "passed", "--exit-code", "0", "--test-count", "1",
                    "--duration-seconds", "1",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(finish.returncode, 0)
            self.assertIn("clean, committed", finish.stderr)

    def test_clean_run_cannot_bypass_canonical_step_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fixture(root)
            start = subprocess.run(
                [
                    sys.executable, str(root / "scripts/write_acceptance.py"), "start",
                    "--root", str(root), "--python-runtime", "project_venv",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(start.returncode, 0, start.stderr)
            finish = subprocess.run(
                [
                    sys.executable, str(root / "scripts/write_acceptance.py"), "finish",
                    "--root", str(root), "--run-id", start.stdout.strip(),
                    "--status", "passed", "--exit-code", "0", "--test-count", "1",
                    "--duration-seconds", "1", "--completed-steps", "unittest",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertNotEqual(finish.returncode, 0)
            self.assertIn("complete canonical step sequence", finish.stderr)

    def test_zero_tests_fails_and_finalizes_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fixture(root)
            env = os.environ.copy()
            env["FAKE_ZERO_TESTS"] = "1"
            tmpdir = root / "tmp"
            tmpdir.mkdir()
            env["TMPDIR"] = str(tmpdir)
            result = subprocess.run(
                ["bash", "scripts/verify.sh"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            evidence = json.loads(
                (root / "outputs/harness/acceptance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["status"], "failed")
            self.assertEqual(evidence["test_count"], 0)
            self.assertEqual(evidence["failed_step"], "unittest")
            self.assert_only_known_platform_tmp_entries(tmpdir)

    def test_missing_project_venv_replaces_stale_pass_with_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            shutil.copy2(VERIFY, root / "scripts/verify.sh")
            shutil.copy2(EVIDENCE_WRITER, root / "scripts/write_acceptance.py")
            stale = root / "outputs/harness/acceptance.json"
            stale.parent.mkdir(parents=True)
            stale.write_text('{"status":"passed","run_id":"stale"}\n', encoding="utf-8")
            result = subprocess.run(
                ["bash", "scripts/verify.sh"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            evidence = json.loads(stale.read_text(encoding="utf-8"))
            self.assertEqual(evidence["status"], "failed")
            self.assertEqual(evidence["python_runtime"], "missing_project_venv")
            self.assertEqual(evidence["failed_step"], "project_interpreter")
            self.assertNotEqual(evidence["run_id"], "stale")

    def test_evidence_writer_rejects_symlinked_outputs_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / "outputs").symlink_to(Path(outside), target_is_directory=True)
            result = subprocess.run(
                [
                    sys.executable,
                    str(EVIDENCE_WRITER),
                    "start",
                    "--root",
                    str(root),
                    "--python-runtime",
                    "project_venv",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_older_run_cannot_overwrite_a_newer_running_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def start() -> str:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(EVIDENCE_WRITER),
                        "start",
                        "--root",
                        str(root),
                        "--python-runtime",
                        "project_venv",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.strip()

            run_a = start()
            run_b = start()
            stale_finish = subprocess.run(
                [
                    sys.executable,
                    str(EVIDENCE_WRITER),
                    "finish",
                    "--root",
                    str(root),
                    "--run-id",
                    run_a,
                    "--status",
                    "passed",
                    "--exit-code",
                    "0",
                    "--test-count",
                    "1",
                    "--duration-seconds",
                    "1",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(stale_finish.returncode, 0)
            evidence = json.loads(
                (root / "outputs/harness/acceptance.json").read_text(encoding="utf-8")
            )
            self.assertEqual(evidence["run_id"], run_b)
            self.assertEqual(evidence["status"], "running")
            lock_mode = (root / "outputs/harness/acceptance.lock").stat().st_mode
            self.assertEqual(lock_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
