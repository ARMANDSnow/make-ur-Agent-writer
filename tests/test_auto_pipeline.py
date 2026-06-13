"""iter 026: src/auto_pipeline.run_auto_pipeline orchestration tests.

Runs the full 9-step pipeline against a per-test temporary workspace
(patched ``paths.WORKSPACE_DIR``), in mock LLM mode. This mirrors the
WebUI wizard path: the wizard creates ``workspaces/<name>/`` and then
``use_workspace`` + worker thread invoke ``run_auto_pipeline``.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.auto_pipeline import STEPS, run_auto_pipeline


SAMPLE_TXT = """第一章 起点

清晨六点，雨敲在玻璃上。
路明非把手机翻过来，再翻回去。
他知道自己得做出选择。
""" * 30


class AutoPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ["OPENAI_MODEL"] = "mock"
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = "autopipe_test"
        ws = paths.WORKSPACE_DIR / "autopipe_test"
        for sub in ("小说txt", "data", "outputs", "logs"):
            (ws / sub).mkdir(parents=True)
        (ws / "小说txt" / "sample.txt").write_text(SAMPLE_TXT, encoding="utf-8")

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _ws_path(self, rel: str) -> Path:
        return paths.WORKSPACE_DIR / "autopipe_test" / rel

    def test_writes_chapter_01_end_to_end(self) -> None:
        results = run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)
        self.assertTrue(self._ws_path("outputs/drafts/chapter_01.md").exists())
        self.assertTrue(self._ws_path("outputs/drafts/chapter_01.meta.json").exists())
        self.assertEqual(len(results["write"]), 1)

    def test_progress_callback_fires_in_step_order(self) -> None:
        seen: list[tuple[str, float]] = []
        run_auto_pipeline(
            target_chapters=1,
            extract_limit=2,
            force=True,
            progress_cb=lambda step, frac: seen.append((step, frac)),
        )
        self.assertEqual(seen[0], ("normalize", 0.0))
        self.assertEqual(seen[-1], ("done", 1.0))
        step_labels = [name for name, _ in seen if name != "done"]
        self.assertEqual(step_labels, list(STEPS))

    def test_propagates_underlying_exception(self) -> None:
        """Removing the raw txt forces an early failure that must
        propagate to the caller (not get swallowed)."""
        shutil.rmtree(self._ws_path("小说txt"))
        # normalize_all returns [] silently if no txt; split_all then
        # raises because no normalized files exist. Either way the
        # caller sees an exception, not a happy results dict.
        with self.assertRaises(Exception):
            run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)

    def test_apply_bootstrap_failure_per_proposal_is_non_fatal(self) -> None:
        """In mock mode the style_examples proposal references a
        non-existent file path. The orchestrator must record the
        failure and keep going so debate / plan / write still run."""
        results = run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)
        applied = results["apply-bootstrap"]
        self.assertEqual(applied["style_examples"]["status"], "apply_failed")
        for name in ("global_facts", "entity_graph", "continuation_anchor", "personas"):
            self.assertEqual(applied[name]["status"], "applied")
        self.assertTrue(self._ws_path("outputs/drafts/chapter_01.md").exists())

    def test_apply_bootstrap_permission_error_propagates(self) -> None:
        """Iter 026 code-review #4 fix: per-proposal apply only catches
        recoverable mock-mode failures (FileNotFoundError / ValueError).
        System errors like PermissionError must propagate so the user
        sees the real root cause via trace_id."""
        from src import auto_pipeline as ap

        original = ap.apply_bootstrap

        def faulty(name, confirm=False):
            if name == "global_facts":
                raise PermissionError("read-only filesystem")
            return original(name, confirm=confirm)

        ap.apply_bootstrap = faulty
        try:
            with self.assertRaises(PermissionError):
                run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)
        finally:
            ap.apply_bootstrap = original

    def test_skip_extract_short_circuits_marker(self) -> None:
        """skip_extract=True records the short-circuit and leaves
        downstream steps to whatever they can do with the (possibly
        empty) extracted dir. We run the full pipeline once to seed
        the artifacts compress / bootstrap / write need, then re-run
        with skip_extract to confirm the marker propagates."""
        run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)
        results = run_auto_pipeline(
            target_chapters=1, skip_extract=True, force=True
        )
        self.assertEqual(results["extract"], {"skipped": True})


REBUILD_TXT = "\n\n".join(
    f"第{cn}章\n" + "\n".join(f"路明非在场景{i}里走了第{j}步，看着远处的雨。" for j in range(1, 12))
    for i, cn in enumerate(["一", "二", "三", "四"], start=1)
)


class RebuildForStartTests(unittest.TestCase):
    """iter 054b: rebuild-for-start one-shot 底座 重建编排 (mock LLM)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ["OPENAI_MODEL"] = "mock"
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = "rebuild_test"
        ws = paths.WORKSPACE_DIR / "rebuild_test"
        for sub in ("小说txt", "data", "outputs", "logs"):
            (ws / sub).mkdir(parents=True)
        (ws / "小说txt" / "sample.txt").write_text(REBUILD_TXT, encoding="utf-8")

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _ws_path(self, rel: str) -> Path:
        return paths.WORKSPACE_DIR / "rebuild_test" / rel

    def _seed_manifest(self) -> list:
        from src.chapter_splitter import split_all
        from src.text_normalizer import normalize_all

        normalize_all()
        split_all()
        return json.loads(
            self._ws_path("data/chapter_manifest.json").read_text(encoding="utf-8")
        )

    def test_rebuild_requires_start_point(self) -> None:
        # greenfield/no-start: nothing to rebuild against (铁律④).
        from src.auto_pipeline import rebuild_for_start

        self._seed_manifest()
        with self.assertRaises(ValueError):
            rebuild_for_start()

    def test_rebuild_chain_bounded_and_stamps_sidecars(self) -> None:
        from src import start_point
        from src.auto_pipeline import rebuild_for_start

        manifest = self._seed_manifest()
        cids = [c["chapter_id"] for c in manifest]
        self.assertGreaterEqual(len(cids), 2)
        start_point.set_start_point(cids[1])  # start at the 2nd chapter
        seen: list = []
        result = rebuild_for_start(window=10, progress_cb=lambda s, f: seen.append(s))

        # entity_graph + anchor freshly built AND applied (live base)
        self.assertTrue(self._ws_path("data/entity_graph.json").exists())
        self.assertTrue(
            self._ws_path("data/manual_overrides/continuation_anchor.txt").exists()
        )
        # both sidecars stamped to the current start (054b stale detection)
        eg = json.loads(self._ws_path("data/.entity_graph.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(eg["start_chapter_id"], cids[1])
        anc = json.loads(
            self._ws_path("data/manual_overrides/.continuation_anchor.meta.json").read_text(encoding="utf-8")
        )
        self.assertEqual(anc["start_chapter_id"], cids[1])
        # window bounded: window chapters extracted, post-start chapter NOT
        self.assertTrue(self._ws_path(f"data/extracted_jsons/{cids[0]}.json").exists())
        self.assertTrue(self._ws_path(f"data/extracted_jsons/{cids[1]}.json").exists())
        if len(cids) > 2:
            self.assertFalse(self._ws_path(f"data/extracted_jsons/{cids[2]}.json").exists())
        self.assertEqual(result["start_chapter_id"], cids[1])
        self.assertEqual(seen[0], "extract")
        self.assertEqual(seen[-1], "done")

    def test_rebuild_no_apply_builds_proposals_only(self) -> None:
        from src import start_point
        from src.auto_pipeline import rebuild_for_start

        manifest = self._seed_manifest()
        cids = [c["chapter_id"] for c in manifest]
        start_point.set_start_point(cids[1])
        rebuild_for_start(window=10, apply=False)
        # proposals written but NOT applied → no live graph / sidecar stamp
        self.assertTrue(self._ws_path("data/proposals/entity_graph.proposal.json").exists())
        self.assertFalse(self._ws_path("data/.entity_graph.meta.json").exists())


def _chapter_block(heading: str, body: str, n: int = 8) -> str:
    return heading + "\n" + "\n".join(body for _ in range(n))


INGEST_TXT = "\n\n".join(
    [
        _chapter_block("第一章", "起点前内容，路明非在教室里。"),
        _chapter_block("第二章", "起点章内容，雨夜的抉择。"),
        _chapter_block("第三章", "POSTSTART三章，未来剧情泄露。"),
        _chapter_block("第四章", "POSTSTART四章，结局泄露。"),
    ]
)


class IngestToStartTests(unittest.TestCase):
    """iter 054d: ingest-to-start physically bounds the corpus to <= start."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ["OPENAI_MODEL"] = "mock"
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = "ingest_test"
        ws = paths.WORKSPACE_DIR / "ingest_test"
        for sub in ("小说txt", "data", "outputs", "logs"):
            (ws / sub).mkdir(parents=True)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _ws_root(self) -> Path:
        return paths.WORKSPACE_DIR / "ingest_test"

    def _ws_path(self, rel: str) -> Path:
        return self._ws_root() / rel

    def _src(self, name: str, text: str) -> None:
        (self._ws_path("小说txt") / name).write_text(text, encoding="utf-8")

    def _full_manifest(self) -> list:
        from src.chapter_splitter import split_all
        from src.text_normalizer import normalize_all

        normalize_all()
        split_all()
        return json.loads(
            self._ws_path("data/chapter_manifest.json").read_text(encoding="utf-8")
        )

    def test_truncates_corpus_to_start_single_volume(self) -> None:
        from src import start_point
        from src.auto_pipeline import ingest_to_start

        self._src("sample.txt", INGEST_TXT)
        full = self._full_manifest()
        cids = [c["chapter_id"] for c in full]
        self.assertGreaterEqual(len(cids), 3)
        vol = full[0]["volume_id"]  # lang detection may prefix the stem
        start = cids[1]  # 2nd chapter; ch3/ch4 carry POSTSTART markers
        result = ingest_to_start(start)

        # manifest keeps only <= start
        manifest = json.loads(
            self._ws_path("data/chapter_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual([c["chapter_id"] for c in manifest], cids[:2])
        # normalized texts PHYSICALLY no longer contain post-start prose
        norm = self._ws_path(f"data/normalized_texts/{vol}.txt").read_text(encoding="utf-8")
        self.assertNotIn("POSTSTART", norm)
        self.assertIn("起点章内容", norm)
        # start point set to the (now-last) start chapter
        self.assertEqual(start_point.get_start_chapter_id(), start)
        self.assertEqual(result["kept_chapters"], 2)
        self.assertEqual(result["dropped_chapters"], len(cids) - 2)
        self.assertIn(f"{vol}.txt", result["truncated_volumes"])

    def test_deletes_post_start_volumes_multi_volume(self) -> None:
        from src.auto_pipeline import ingest_to_start

        self._src("volA.txt", "\n\n".join([
            _chapter_block("第一章", "A卷起点前内容。"),
            _chapter_block("第二章", "A卷起点章内容。"),
        ]))
        self._src("volB.txt", "\n\n".join([
            _chapter_block("第一章", "POSTSTART B卷泄露内容。"),
            _chapter_block("第二章", "POSTSTART B卷泄露内容二。"),
        ]))
        full = self._full_manifest()
        first_vol = full[0]["volume_id"]
        later_vols = {c["volume_id"] for c in full if c["volume_id"] != first_vol}
        self.assertTrue(later_vols, "test needs >= 2 volumes")
        # start at the last chapter of the first volume → later volumes drop
        start = [c for c in full if c["volume_id"] == first_vol][-1]["chapter_id"]
        result = ingest_to_start(start)

        manifest = json.loads(
            self._ws_path("data/chapter_manifest.json").read_text(encoding="utf-8")
        )
        self.assertTrue(all(c["volume_id"] == first_vol for c in manifest))
        for v in later_vols:
            self.assertFalse(self._ws_path(f"data/normalized_texts/{v}.txt").exists())
        self.assertTrue(result["deleted_volumes"])

    def test_downstream_extract_and_sampling_bounded(self) -> None:
        from src.auto_bootstrap import _normalized_context
        from src.auto_pipeline import ingest_to_start
        from src.extractor import extract_all

        self._src("sample.txt", INGEST_TXT)
        cids = [c["chapter_id"] for c in self._full_manifest()]
        ingest_to_start(cids[1])
        # extract everything the (now-bounded) manifest knows → only <= start
        extract_all(volume="all", force=True)
        got = sorted(p.stem for p in self._ws_path("data/extracted_jsons").glob("*.json"))
        self.assertEqual(got, sorted(cids[:2]))
        # the bootstrap sampling source (style/source_excerpts upstream) is clean
        ctx = _normalized_context(self._ws_root(), limit_chars=50000)
        self.assertNotIn("POSTSTART", ctx)


if __name__ == "__main__":
    unittest.main()
