"""iter 053a: debate 中间产物起点一致性校验（outline/decisions 护栏）。

四层覆盖：

* 纯函数 —— ``start_point.outline_consistency_failures``（四态：匹配 /
  不匹配 / 无指纹 / decisions 缺失）与 ``plan_outline_lineage_failures``；
* debater 落盘侧 —— decisions.json 元数据钉入（dict 键，schema 不动）、
  outline 先写 decisions 后写、log 指纹头、resume 防洗白、--force 归档；
* plot_planner 消费侧 —— 硬拦 / warn 放行 / --allow-stale-outline 逃生门
  审计痕 / plan↔outline 血统链落盘；
* driver 三态 —— 指纹一致跳过 / 不匹配缺省 blocked / --force-debate 重辩
  并归档失效下游 chapter_plan.json / 与 --skip-debate 互斥。
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import book_driver, paths, start_point
from src.config import ROOT
from src.utils import read_json, sha256_text, write_json

WORKSPACES_DIR = ROOT / "workspaces"


# ---------------------------------------------------------------------------
# 纯函数层
# ---------------------------------------------------------------------------


class OutlineConsistencyFunctionTests(unittest.TestCase):
    """workspace 模式下的四态判定 + 血统链纯函数。"""

    def setUp(self) -> None:
        self._old_ws_env = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter053atest"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter053atest"
        (self.ws_root / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        manifest = [
            {"chapter_id": "v1_ch001", "volume_id": "v1", "title": "first",
             "source_file": "a.txt", "start_line": 1, "end_line": 5},
            {"chapter_id": "v1_ch002", "volume_id": "v1", "title": "second",
             "source_file": "a.txt", "start_line": 6, "end_line": 10},
        ]
        (self.ws_root / "data" / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        (self.ws_root / "data" / "manual_overrides" / "start_chapter.json").write_text(
            json.dumps({"start_chapter_id": "v1_ch002"}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws_env

    def _fresh_decisions(self, outline_text: str) -> dict:
        return {
            "topic": "t",
            "votes": [],
            "start_chapter_id": start_point.get_start_chapter_id() or "",
            "start_point_fingerprint": start_point.start_point_fingerprint(),
            "outline_sha256": sha256_text(outline_text),
        }

    def test_empty_or_legacy_decisions_is_metadata_missing(self) -> None:
        # decisions.json 缺失（{}）与存量无指纹（仅 topic/votes）都必须落进
        # 同一条 warn 道——否则删一个文件即可绕过硬拦（审查 A2）。
        for decisions in ({}, None, {"topic": "t", "votes": []}):
            self.assertEqual(
                start_point.outline_consistency_failures(decisions, outline_text="x"),
                [start_point.OUTLINE_METADATA_MISSING],
                msg=f"decisions={decisions!r}",
            )

    def test_fresh_metadata_matches_clean(self) -> None:
        outline = "# 大纲正文"
        self.assertEqual(
            start_point.outline_consistency_failures(
                self._fresh_decisions(outline), outline_text=outline
            ),
            [],
        )

    def test_start_chapter_id_mismatch_is_hard(self) -> None:
        outline = "# 大纲"
        decisions = self._fresh_decisions(outline)
        decisions["start_chapter_id"] = "v1_ch001"
        decisions["start_point_fingerprint"] = "stale-era-fp"
        codes = start_point.outline_consistency_failures(decisions, outline_text=outline)
        self.assertIn("outline_start_chapter_id_mismatch", codes)
        self.assertIn("outline_start_point_fingerprint_mismatch", codes)

    def test_fingerprint_only_mismatch(self) -> None:
        # 起点 id 没变、指纹变了（典型：重切章行号漂移）——单独一码，消费侧
        # 报错文案据此区分处置建议（审查 A7）。
        outline = "# 大纲"
        decisions = self._fresh_decisions(outline)
        decisions["start_point_fingerprint"] = "drifted"
        self.assertEqual(
            start_point.outline_consistency_failures(decisions, outline_text=outline),
            ["outline_start_point_fingerprint_mismatch"],
        )

    def test_outline_content_mismatch(self) -> None:
        decisions = self._fresh_decisions("原始大纲")
        self.assertEqual(
            start_point.outline_consistency_failures(decisions, outline_text="被手改过的大纲"),
            ["outline_content_mismatch"],
        )

    def test_fail_open_when_no_current_start(self) -> None:
        # 当前工作区没有起点（greenfield）→ 存的起点信息不构成矛盾（与 F6
        # enforce_consistency 同一 fail-open 约定）。
        (self.ws_root / "data" / "manual_overrides" / "start_chapter.json").unlink()
        outline = "# 大纲"
        decisions = {
            "start_chapter_id": "v1_ch001",
            "start_point_fingerprint": "some-old-fp",
            "outline_sha256": sha256_text(outline),
        }
        self.assertEqual(
            start_point.outline_consistency_failures(decisions, outline_text=outline),
            [],
        )

    def test_plan_outline_lineage(self) -> None:
        outline = "# 当前大纲"
        # 旧 plan 没记哈希 → fail-open（存量兼容）。
        self.assertEqual(
            start_point.plan_outline_lineage_failures({"chapters": []}, outline_text=outline),
            [],
        )
        # 哈希匹配 → 干净。
        self.assertEqual(
            start_point.plan_outline_lineage_failures(
                {"outline_sha256": sha256_text(outline)}, outline_text=outline
            ),
            [],
        )
        # debate 重跑后 outline 变了 → 血统断裂（052 毒 plan 场景，审查 A1）。
        self.assertEqual(
            start_point.plan_outline_lineage_failures(
                {"outline_sha256": sha256_text("旧大纲")}, outline_text=outline
            ),
            ["plan_outline_lineage_mismatch"],
        )
        # outline 读不到 → fail-open。
        self.assertEqual(
            start_point.plan_outline_lineage_failures(
                {"outline_sha256": "abc"}, outline_text=None
            ),
            [],
        )


# ---------------------------------------------------------------------------
# debater 落盘侧
# ---------------------------------------------------------------------------


class DebaterProvenanceTests(unittest.TestCase):
    """legacy 模式（patch DEBATE_DIR 三常量）+ patch start_point 当前态。"""

    def _run(self, tmp_path: Path, fingerprint: str, start_id: str = "v9_ch001", **kwargs):
        from src.debater import run_debate

        kb = tmp_path / "global_knowledge.md"
        if not kb.exists():
            kb.write_text("# kb", encoding="utf-8")
        idx = tmp_path / "knowledge_index.json"
        if not idx.exists():
            idx.write_text("{}", encoding="utf-8")
        with patch("src.debater.KB_PATH", kb), patch("src.debater.INDEX_PATH", idx), patch(
            "src.debater.DEBATE_DIR", tmp_path
        ), patch("src.start_point.get_start_chapter_id", return_value=start_id), patch(
            "src.start_point.start_point_fingerprint", return_value=fingerprint
        ):
            return run_debate(**kwargs)

    def test_decisions_carry_provenance_and_outline_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._run(tmp_path, "fp-A")
            decisions = json.loads((tmp_path / "decisions.json").read_text(encoding="utf-8"))
            outline = (tmp_path / "outline.md").read_text(encoding="utf-8")
        self.assertEqual(decisions["start_chapter_id"], "v9_ch001")
        self.assertEqual(decisions["start_point_fingerprint"], "fp-A")
        self.assertEqual(decisions["outline_sha256"], sha256_text(outline))
        self.assertTrue(decisions["generated_at"])

    def test_log_head_is_provenance_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._run(tmp_path, "fp-A")
            first = json.loads(
                (tmp_path / "debate_log.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
        self.assertEqual(first.get("meta"), "debate_start_point")
        self.assertEqual(first.get("start_point_fingerprint"), "fp-A")
        self.assertEqual(first.get("start_chapter_id"), "v9_ch001")

    def test_resume_same_fingerprint_passes_and_keeps_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._run(tmp_path, "fp-A")
            self._run(tmp_path, "fp-A")  # resume：done_keys 全命中，不得报错
            first = json.loads(
                (tmp_path / "debate_log.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
        self.assertEqual(first.get("meta"), "debate_start_point")

    def test_resume_foreign_fingerprint_refuses_laundering(self) -> None:
        # 审查 A3：旧起点时代的 log + 新起点 resume → 旧 transcript 会被盖上
        # 新鲜指纹"洗白"，必须拒绝并指路 --force。
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._run(tmp_path, "fp-A")
            with self.assertRaises(ValueError) as ctx:
                self._run(tmp_path, "fp-B")
        self.assertIn("--force", str(ctx.exception))

    def test_resume_legacy_log_without_meta_fails_open(self) -> None:
        # 存量 log（无指纹头）→ fail-open 放行，护 052 前的 workspace。
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "debate_log.jsonl").write_text(
                json.dumps({"round": 1, "round_name": "立场陈述", "agent": "旧人", "response": "旧话"})
                + "\n",
                encoding="utf-8",
            )
            self._run(tmp_path, "fp-A")  # 不得 raise
            decisions = json.loads((tmp_path / "decisions.json").read_text(encoding="utf-8"))
        self.assertEqual(decisions["start_point_fingerprint"], "fp-A")

    def test_force_archives_trio_to_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._run(tmp_path, "fp-A")
            old_outline = (tmp_path / "outline.md").read_text(encoding="utf-8")
            # 起点换代 + force：归档（非删除）三件套后全新辩论，不得报错。
            self._run(tmp_path, "fp-B", force=True)
            snaps = list((tmp_path / "snapshots").iterdir())
            self.assertEqual(len(snaps), 1)
            archived = {p.name for p in snaps[0].iterdir()}
            self.assertEqual(
                archived, {"outline.md", "decisions.json", "debate_log.jsonl"}
            )
            self.assertEqual(
                (snaps[0] / "outline.md").read_text(encoding="utf-8"), old_outline
            )
            fresh = json.loads((tmp_path / "decisions.json").read_text(encoding="utf-8"))
        self.assertEqual(fresh["start_point_fingerprint"], "fp-B")

    def test_force_with_nothing_to_archive_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._run(tmp_path, "fp-A", force=True)
            self.assertFalse((tmp_path / "snapshots").exists())
            self.assertTrue((tmp_path / "decisions.json").exists())

    def test_outline_cr_normalized_before_hashing(self) -> None:
        # 铁律⑨ A-M2：LLM 输出带 \r\n 时，写盘哈希必须与 read_text 读回一致
        # ——否则 outline_content_mismatch 假阳性硬拦且重跑无解。
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch(
                "src.debater.build_outline", return_value="# 大纲\r\n第一行\r第二行"
            ):
                self._run(tmp_path, "fp-A")
            decisions = json.loads(
                (tmp_path / "decisions.json").read_text(encoding="utf-8")
            )
            on_disk = (tmp_path / "outline.md").read_text(encoding="utf-8")
        self.assertEqual(decisions["outline_sha256"], sha256_text(on_disk))
        self.assertNotIn("\r", on_disk)

    def test_resume_headless_log_with_metadata_decisions_refuses(self) -> None:
        # 铁律⑨ A-M3：log 指纹头被删/截断、decisions 已带 053 元数据 →
        # fail-closed（纯 legacy 工作区两边都无元数据，照旧放行）。
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            self._run(tmp_path, "fp-A")
            log_path = tmp_path / "debate_log.jsonl"
            body = [
                line
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if '"meta"' not in line
            ]
            log_path.write_text("\n".join(body) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                self._run(tmp_path, "fp-A")
        self.assertIn("--force", str(ctx.exception))

    def test_empty_log_file_gets_provenance_head(self) -> None:
        # 铁律⑨ A-L2：0 字节 log 同样补指纹头，防永久无头 fail-open。
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "debate_log.jsonl").write_text("", encoding="utf-8")
            self._run(tmp_path, "fp-A")
            first = json.loads(
                (tmp_path / "debate_log.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
        self.assertEqual(first.get("meta"), "debate_start_point")


# ---------------------------------------------------------------------------
# debate 显式起点锚定块（iter 053e，053c 实跑发现直修）
# ---------------------------------------------------------------------------


class DebateStartPointBlockTests(unittest.TestCase):
    """053c 段一实证：起点安全 KB + 053a 指纹也挡不住辩论把起点前已收束的
    高潮当'当前局势'重演（毒 anchor 内容层穿透，id 级 provenance 拦不住）。
    053e 把 plot_planner 的显式起点块 + anchor 降级搬给 debate 三个 prompt 面。"""

    def test_no_start_point_block_is_empty(self) -> None:
        from src.debater import _start_point_prompt_block

        with patch("src.start_point.get_start_chapter_id", return_value=None):
            self.assertEqual(_start_point_prompt_block(), "")

    def test_block_contains_override_clause_and_chapter_tail(self) -> None:
        from src.debater import _start_point_prompt_block

        with patch(
            "src.start_point.get_start_chapter_id", return_value="v9_ch024"
        ), patch(
            "src.start_point.chapters_before_start",
            return_value=[{"chapter_id": "v9_ch023", "title": "前章"}],
        ), patch(
            "src.start_point.load_chapter_text", return_value="……尾声结尾原文。"
        ):
            block = _start_point_prompt_block()
        self.assertIn("显式续写起点", block)
        self.assertIn("v9_ch024", block)
        # 显式压过 must-anchor 叙事块（anchor 内容毒的治法核心）。
        self.assertIn("must-anchor", block)
        self.assertIn("已经收束", block)
        self.assertIn("尾声结尾原文", block)
        self.assertIn("v9_ch023", block)

    def test_agent_prompts_carry_block_only_with_start(self) -> None:
        from src.debater import run_debate

        for start_id, expect in (("v9_ch024", True), (None, False)):
            prompts: list = []

            def spy(self, messages, temperature=None, cache_segments=None):
                prompts.append("\n".join(m.get("content", "") for m in messages))
                return "发言。"

            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                (tmp_path / "global_knowledge.md").write_text("# kb", encoding="utf-8")
                (tmp_path / "knowledge_index.json").write_text("{}", encoding="utf-8")
                with patch("src.debater.KB_PATH", tmp_path / "global_knowledge.md"), patch(
                    "src.debater.INDEX_PATH", tmp_path / "knowledge_index.json"
                ), patch("src.debater.DEBATE_DIR", tmp_path), patch(
                    "src.start_point.get_start_chapter_id", return_value=start_id
                ), patch(
                    "src.start_point.start_point_fingerprint",
                    return_value="fp-block-test" if start_id else "",
                ), patch(
                    "src.llm_client.LLMClient.complete_text", spy
                ):
                    run_debate()
            joined = "\n".join(prompts)
            if expect:
                self.assertIn("显式续写起点", joined, msg=f"start={start_id}")
            else:
                self.assertNotIn("显式续写起点", joined, msg=f"start={start_id}")


# ---------------------------------------------------------------------------
# plot_planner 消费侧
# ---------------------------------------------------------------------------


class PlotPlannerGateTests(unittest.TestCase):
    def _generate(self, tmp_path: Path, decisions: dict | None, *, current_fp="fp-now",
                  current_start="chX", **kwargs):
        from src.plot_planner import generate_chapter_plan

        outline_path = tmp_path / "outline.md"
        if not outline_path.exists():
            outline_path.write_text("# mock outline", encoding="utf-8")
        plan_path = tmp_path / "chapter_plan.json"
        decisions_path = tmp_path / "decisions.json"
        if decisions is not None:
            write_json(decisions_path, decisions)
        with patch("src.plot_planner.OUTLINE_PATH", outline_path), patch(
            "src.plot_planner.CHAPTER_PLAN_PATH", plan_path
        ), patch("src.plot_planner.DECISIONS_PATH", decisions_path), patch(
            "src.start_point.get_start_chapter_id", return_value=current_start
        ), patch(
            "src.start_point.start_point_fingerprint", return_value=current_fp
        ):
            return generate_chapter_plan(target_chapters=3, **kwargs), plan_path, outline_path

    def _matching_decisions(self, outline_text: str = "# mock outline") -> dict:
        return {
            "start_chapter_id": "chX",
            "start_point_fingerprint": "fp-now",
            "outline_sha256": sha256_text(outline_text),
        }

    def test_missing_decisions_warns_and_records_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data, plan_path, outline_path = self._generate(Path(tmp), None)
            written = json.loads(plan_path.read_text(encoding="utf-8"))
            outline = outline_path.read_text(encoding="utf-8")
        # warn 放行 + 血统链落盘（审查 A1）。
        self.assertEqual(written["outline_sha256"], sha256_text(outline))
        self.assertNotIn("stale_outline_acknowledged", written)

    def test_matching_metadata_passes_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data, plan_path, _ = self._generate(Path(tmp), self._matching_decisions())
            written = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(written["chapters"]), 1)
        self.assertNotIn("stale_outline_acknowledged", written)

    def test_start_mismatch_hard_blocks(self) -> None:
        decisions = self._matching_decisions()
        decisions["start_chapter_id"] = "chOLD"
        decisions["start_point_fingerprint"] = "fp-old"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                self._generate(Path(tmp), decisions)
            self.assertFalse((Path(tmp) / "chapter_plan.json").exists())
        self.assertIn("stale debate outline", str(ctx.exception))
        self.assertIn("debate --force", str(ctx.exception))

    def test_fingerprint_only_mismatch_offers_escape_hatch(self) -> None:
        decisions = self._matching_decisions()
        decisions["start_point_fingerprint"] = "fp-drift"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                self._generate(Path(tmp), decisions)
        # 审查 A7：行号漂移情形必须给出 --allow-stale-outline 的处置指引。
        self.assertIn("--allow-stale-outline", str(ctx.exception))

    def test_content_mismatch_hard_blocks(self) -> None:
        decisions = self._matching_decisions("另一份大纲")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as ctx:
                self._generate(Path(tmp), decisions)
        self.assertIn("outline_content_mismatch", str(ctx.exception))

    def test_allow_stale_outline_passes_with_audit_trail(self) -> None:
        decisions = self._matching_decisions()
        decisions["start_chapter_id"] = "chOLD"
        with tempfile.TemporaryDirectory() as tmp:
            data, plan_path, _ = self._generate(
                Path(tmp), decisions, allow_stale_outline=True
            )
            written = json.loads(plan_path.read_text(encoding="utf-8"))
        audit = written["stale_outline_acknowledged"]
        self.assertIn("outline_start_chapter_id_mismatch", audit["codes"])
        self.assertTrue(audit["acknowledged_at"])


# ---------------------------------------------------------------------------
# driver 三态
# ---------------------------------------------------------------------------

_STUB_SOURCE = """\
import json, os, sys
calls_path = os.environ["DRIVER_STUB_CALLS"]
queue_path = os.environ["DRIVER_STUB_QUEUE"]
with open(calls_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
with open(queue_path, "r", encoding="utf-8") as fh:
    queue = json.load(fh)
for i, entry in enumerate(queue):
    if entry["cmd"] in sys.argv[1:]:
        queue.pop(i)
        with open(queue_path, "w", encoding="utf-8") as fh:
            json.dump(queue, fh, ensure_ascii=False)
        for line in entry.get("stdout", []):
            print(line)
        sys.exit(int(entry.get("exit", 0)))
print("unscripted stub call: " + " ".join(sys.argv[1:]), file=sys.stderr)
sys.exit(97)
"""


def _driver_args(**overrides):
    base = dict(
        action="start",
        chapters=2,
        resume_from=1,
        segment_size=2,
        replan_every=0,
        plan_target=2,
        budget_cny=None,
        tier=None,
        max_retries=2,
        skip_debate=False,
        force_debate=False,
        require_start_point=False,
        allow_missing_start_point=True,
        allow_missing_plan=False,
        skip_external_review=False,
        pause_after_segment=None,
        step_timeout_minutes=None,
        on_blocked=None,
        detach=False,
        confirm_real_run=False,
        json=False,
        cmd_prefix=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _ready_json() -> str:
    return json.dumps({"status": "ready", "blockers": [], "warnings": []})


def _wb_json() -> str:
    return json.dumps(
        {
            "status": "succeeded",
            "chapters": [
                {"chapter": 1, "action": "written", "status": {"verdict": "Approve"}},
                {"chapter": 2, "action": "written", "status": {"verdict": "Approve"}},
            ],
        },
        ensure_ascii=False,
    )


class DriverDebateTriStateTests(unittest.TestCase):
    def setUp(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            original = signal.getsignal(sig)
            self.addCleanup(signal.signal, sig, original)
        WORKSPACES_DIR.mkdir(exist_ok=True)
        self.ws = Path(tempfile.mkdtemp(prefix="unit_driver_053a_", dir=WORKSPACES_DIR))
        self.addCleanup(shutil.rmtree, self.ws, True)
        env = patch.dict(os.environ, {"WORKSPACE_NAME": self.ws.name}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        # 起点 + manifest：让 start_point_fingerprint 有真实非空值。
        (self.ws / "data" / "manual_overrides").mkdir(parents=True)
        (self.ws / "data" / "chapter_manifest.json").write_text(
            json.dumps(
                [
                    {"chapter_id": "v1_ch001", "volume_id": "v1", "title": "a",
                     "source_file": "a.txt", "start_line": 1, "end_line": 5},
                    {"chapter_id": "v1_ch002", "volume_id": "v1", "title": "b",
                     "source_file": "a.txt", "start_line": 6, "end_line": 10},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (self.ws / "data" / "manual_overrides" / "start_chapter.json").write_text(
            json.dumps({"start_chapter_id": "v1_ch002"}), encoding="utf-8"
        )

    def _install_stub(self, queue: list) -> tuple[str, Path]:
        stub = self.ws / "driver_stub.py"
        stub.write_text(_STUB_SOURCE, encoding="utf-8")
        queue_path = self.ws / "stub_queue.json"
        calls_path = self.ws / "stub_calls.jsonl"
        queue_path.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
        calls_path.write_text("", encoding="utf-8")
        env = patch.dict(
            os.environ,
            {"DRIVER_STUB_QUEUE": str(queue_path), "DRIVER_STUB_CALLS": str(calls_path)},
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(stub))}", calls_path

    def _calls(self, calls_path: Path) -> list:
        return [
            json.loads(line)
            for line in calls_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _seed_outline(self, *, stale: bool, with_metadata: bool = True) -> None:
        debate_dir = paths.debate_dir()
        debate_dir.mkdir(parents=True, exist_ok=True)
        outline = "# 大纲"
        (debate_dir / "outline.md").write_text(outline, encoding="utf-8")
        if not with_metadata:
            return
        decisions = {
            "topic": "t",
            "votes": [],
            "start_chapter_id": "v1_ch001" if stale else "v1_ch002",
            "start_point_fingerprint": (
                "fp-of-another-era" if stale else start_point.start_point_fingerprint()
            ),
            "outline_sha256": sha256_text(outline),
        }
        write_json(debate_dir / "decisions.json", decisions)

    def _seed_plan(self, count: int) -> None:
        plan_path = paths.chapter_plan_path()
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(plan_path, {"chapters": [{"chapter_no": i + 1} for i in range(count)]})

    def _events(self) -> list:
        p = book_driver.events_path()
        if not p.exists():
            return []
        return [
            json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_consistent_outline_skips_debate(self) -> None:
        self._seed_outline(stale=False)
        self._seed_plan(2)
        prefix, calls_path = self._install_stub(
            [
                {"cmd": "preflight", "exit": 0},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
                {"cmd": "write-book", "exit": 0, "stdout": [_wb_json()]},
            ]
        )
        rc = book_driver.cmd_start(_driver_args(cmd_prefix=prefix))
        self.assertEqual(rc, 0)
        cmds = [argv for argv in self._calls(calls_path)]
        self.assertFalse(any("debate" in argv for argv in cmds))
        events = [e["event"] for e in self._events()]
        self.assertIn("step_skipped", events)

    def test_stale_outline_blocks_by_default(self) -> None:
        # 缺省 fail-closed（审查 A6）：不静默烧钱自动重辩，blocked 停人审。
        self._seed_outline(stale=True)
        self._seed_plan(2)
        prefix, calls_path = self._install_stub([{"cmd": "preflight", "exit": 0}])
        rc = book_driver.cmd_start(_driver_args(cmd_prefix=prefix))
        self.assertEqual(rc, book_driver.TERMINAL_EXIT_CODES["blocked"])
        state = book_driver.load_state()
        self.assertEqual(state["status"], "blocked")
        self.assertIn("--force-debate", state["last_error"])
        blocked = [e for e in self._events() if e["event"] == "debate_stale_outline_blocked"]
        self.assertEqual(len(blocked), 1)
        self.assertIn("outline_start_chapter_id_mismatch", blocked[0]["codes"])
        # debate 子进程从未被调起（blocked 在进程内判定，零成本）。
        self.assertFalse(any("debate" in argv for argv in self._calls(calls_path)))

    def test_legacy_outline_warns_and_skips(self) -> None:
        self._seed_outline(stale=False, with_metadata=False)
        self._seed_plan(2)
        prefix, calls_path = self._install_stub(
            [
                {"cmd": "preflight", "exit": 0},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
                {"cmd": "write-book", "exit": 0, "stdout": [_wb_json()]},
            ]
        )
        rc = book_driver.cmd_start(_driver_args(cmd_prefix=prefix))
        self.assertEqual(rc, 0)
        events = [e["event"] for e in self._events()]
        self.assertIn("debate_outline_no_fingerprint", events)
        self.assertFalse(any("debate" in argv for argv in self._calls(calls_path)))

    def test_force_debate_reruns_and_archives_stale_plan(self) -> None:
        self._seed_outline(stale=True)
        self._seed_plan(2)
        prefix, calls_path = self._install_stub(
            [
                {"cmd": "preflight", "exit": 0},
                {"cmd": "debate", "exit": 0},
                {"cmd": "plan-chapters", "exit": 0},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
                {"cmd": "write-book", "exit": 0, "stdout": [_wb_json()]},
            ]
        )
        rc = book_driver.cmd_start(_driver_args(cmd_prefix=prefix, force_debate=True))
        self.assertEqual(rc, 0)
        calls = self._calls(calls_path)
        debate_calls = [argv for argv in calls if "debate" in argv]
        self.assertEqual(len(debate_calls), 1)
        self.assertIn("--force", debate_calls[0])
        # 下游 plan 联动归档（审查 A1）：旧 plan 进 snapshots，ensure-plan 重跑。
        snapshots = list((paths.debate_dir() / "snapshots").iterdir())
        self.assertEqual(len(snapshots), 1)
        self.assertTrue((snapshots[0] / "chapter_plan.json").exists())
        self.assertTrue(any("plan-chapters" in argv for argv in calls))
        events = [e["event"] for e in self._events()]
        self.assertIn("stale_plan_archived", events)
        # 一次性旗标已消费：resume 不会再重辩。
        self.assertFalse(book_driver.load_state()["params"]["force_debate"])

    def test_skip_and_force_debate_are_mutually_exclusive(self) -> None:
        rc = book_driver.cmd_start(_driver_args(skip_debate=True, force_debate=True))
        self.assertEqual(rc, 2)

    def test_force_debate_archives_plan_before_debate_even_on_failure(self) -> None:
        # 铁律⑨ A-H1：plan 归档必须先于 debate 子进程——debate 失败/超时也
        # 不能丢"联动失效"意图，否则 resume（force 已清零）补完辩论后
        # ensure-plan 见旧 plan 条数够数直接复用（052 事故中断路径复活）。
        self._seed_outline(stale=True)
        self._seed_plan(2)
        prefix, calls_path = self._install_stub(
            [
                {"cmd": "preflight", "exit": 0},
                {"cmd": "debate", "exit": 1},
            ]
        )
        rc = book_driver.cmd_start(_driver_args(cmd_prefix=prefix, force_debate=True))
        self.assertEqual(rc, book_driver.TERMINAL_EXIT_CODES["failed"])
        snapshots = list((paths.debate_dir() / "snapshots").iterdir())
        self.assertEqual(len(snapshots), 1)
        self.assertTrue((snapshots[0] / "chapter_plan.json").exists())
        self.assertFalse(paths.chapter_plan_path().exists())


if __name__ == "__main__":
    unittest.main()
