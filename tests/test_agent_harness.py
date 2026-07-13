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
            "8 段 docs/iterations/README.md 不要 commit 不要 push\n",
            encoding="utf-8",
        )
        (self.root / ".agents/skills/iter-finish/SKILL.md").write_text(
            "---\nname: iter-finish\ndescription: test\n---\n"
            "聚焦 只读 bash scripts/verify.sh 就地更新 不得新增逐轮\n",
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

    def test_valid_fixture_passes_without_rewriting_legacy_iteration(self) -> None:
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted iter 101", result.stdout)

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
            f"## {name}\n<待实施>" for name in SECTIONS
        )
        (self.root / "docs/iterations/iteration_102_active.md").write_text(
            active + "\n", encoding="utf-8"
        )
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("accepted iter 101, active iter 102", result.stdout)

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


class VerifyHarnessTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> None:
        (root / "scripts").mkdir()
        (root / ".venv/bin").mkdir(parents=True)
        shutil.copy2(VERIFY, root / "scripts/verify.sh")
        shutil.copy2(EVIDENCE_WRITER, root / "scripts/write_acceptance.py")
        fake_python = root / ".venv/bin/python3"
        real_python = shlex.quote(sys.executable)
        fake_python.write_text(
            "#!/usr/bin/env bash\n"
            "set -eu\n"
            f"REAL_PYTHON={real_python}\n"
            "if [[ \"${1:-}\" == 'scripts/write_acceptance.py' ]]; then\n"
            "  exec \"$REAL_PYTHON\" \"$@\"\n"
            "fi\n"
            "ROOT=\"$(cd \"$(dirname \"$0\")/../..\" && pwd)\"\n"
            "{\n"
            "  printf 'ENV:%s:%s:%s ARGS:' \"${OPENAI_MODEL:-}\" \"${DRAMA_MODEL:-}\" \"${OPENAI_API_KEY:-}\"\n"
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

    def test_verify_uses_venv_once_and_writes_redacted_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fixture(root)
            env = os.environ.copy()
            env["OPENAI_API_KEY"] = "must-not-survive"
            env["DRAMA_MODEL"] = "provider/must-not-survive"
            result = subprocess.run(
                ["bash", "scripts/verify.sh", "--book", "Book With Spaces"],
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            invocations = (root / "invocations.log").read_text(encoding="utf-8")
            self.assertEqual(
                invocations.count("<-m> <unittest> <discover> <-s> <tests> <-v>"), 1
            )
            self.assertIn(
                "ARGS: <main.py> <--book> <Book With Spaces> <preflight>", invocations
            )
            self.assertNotIn("provider/must-not-survive", invocations)
            self.assertTrue(
                all(
                    line.startswith("ENV:mock:mock: ARGS:")
                    for line in invocations.splitlines()
                )
            )
            evidence_path = root / "outputs/harness/acceptance.json"
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["schema_version"], 1)
            self.assertEqual(evidence["status"], "passed")
            self.assertEqual(evidence["test_count"], 7)
            self.assertEqual(evidence["python_runtime"], "project_venv")
            self.assertTrue(evidence["mock_offline"])
            self.assertRegex(evidence["run_id"], r"^[0-9a-f]{32}$")
            self.assertIsNotNone(evidence["started_at"])
            self.assertIsNotNone(evidence["completed_at"])
            self.assertIsNone(evidence["failed_step"])
            self.assertIn("harness_check", evidence["completed_steps"])
            self.assertIn("unittest", evidence["completed_steps"])
            self.assertIn("preflight", evidence["completed_steps"])
            self.assertNotIn("must-not-survive", evidence_path.read_text(encoding="utf-8"))

    def test_zero_tests_fails_and_finalizes_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_fixture(root)
            env = os.environ.copy()
            env["FAKE_ZERO_TESTS"] = "1"
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
