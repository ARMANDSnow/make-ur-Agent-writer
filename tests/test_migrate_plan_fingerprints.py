"""iter057 P0-A: scripts/migrate_plan_fingerprints.py 迁移逻辑测试。

plan_fingerprint 算法换代后,现存 workspace 的 plan/meta/review 里冻结的旧指纹要被
一次性刷成新算法值,否则升级即 plan_fingerprint_mismatch。测迁移正确、幂等、dry-run 不写盘。
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import migrate_plan_fingerprints as mig  # noqa: E402

from src.plot_planner import plan_fingerprint
from src.utils import read_json, write_json


def _make_outputs(tmp: Path) -> Path:
    """构造一个带旧算法 plan_fingerprint 的 outputs/ 目录。"""
    outputs = tmp / "outputs"
    (outputs / "debate").mkdir(parents=True)
    (outputs / "drafts").mkdir()
    (outputs / "reviews").mkdir()
    plan = {
        "target_chapters": 3,
        "overall_arc": "arc",
        "start_chapter_id": "v1_ch003",
        "start_point_fingerprint": "start-fp",
        "chapters": [{"chapter_no": i, "title": f"t{i}"} for i in (1, 2, 3)],
        "plan_fingerprint": "OLD_STALE_FP",
    }
    write_json(outputs / "debate" / "chapter_plan.json", plan)
    write_json(
        outputs / "drafts" / "chapter_01.meta.json",
        {"verdict": "Approve", "run_context": {
            "start_chapter_id": "v1_ch003", "plan_fingerprint": "OLD_STALE_FP"}},
    )
    write_json(
        outputs / "reviews" / "chapter_01.review.json",
        {"verdict": "Approve", "run_context": {"plan_fingerprint": "OLD_STALE_FP"}},
    )
    return outputs


class MigratePlanFingerprintsTests(unittest.TestCase):
    def test_refreshes_plan_meta_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _make_outputs(Path(tmp))
            new_fp = plan_fingerprint(read_json(outputs / "debate" / "chapter_plan.json", {}))
            self.assertNotEqual(new_fp, "OLD_STALE_FP")

            stats = mig.migrate_outputs(outputs, dry_run=False)
            self.assertEqual((stats["plan"], stats["meta"], stats["review"]), (1, 1, 1))
            self.assertEqual(
                read_json(outputs / "debate" / "chapter_plan.json", {})["plan_fingerprint"], new_fp)
            self.assertEqual(
                read_json(outputs / "drafts" / "chapter_01.meta.json", {})
                ["run_context"]["plan_fingerprint"], new_fp)
            self.assertEqual(
                read_json(outputs / "reviews" / "chapter_01.review.json", {})
                ["run_context"]["plan_fingerprint"], new_fp)

    def test_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _make_outputs(Path(tmp))
            mig.migrate_outputs(outputs, dry_run=False)
            stats2 = mig.migrate_outputs(outputs, dry_run=False)
            self.assertEqual((stats2["plan"], stats2["meta"], stats2["review"]), (0, 0, 0))

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _make_outputs(Path(tmp))
            mig.migrate_outputs(outputs, dry_run=True)
            self.assertEqual(
                read_json(outputs / "debate" / "chapter_plan.json", {})["plan_fingerprint"],
                "OLD_STALE_FP")

    def test_no_plan_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp) / "outputs"
            outputs.mkdir()
            self.assertIsNone(mig.migrate_outputs(outputs, dry_run=False))

    def test_legacy_file_without_fingerprint_untouched(self) -> None:
        # run_context 无 plan_fingerprint 的 legacy meta 不被强加(只刷有旧值的)。
        with tempfile.TemporaryDirectory() as tmp:
            outputs = _make_outputs(Path(tmp))
            write_json(
                outputs / "drafts" / "chapter_02.meta.json",
                {"verdict": "Approve", "run_context": {"start_chapter_id": "v1_ch003"}},
            )
            mig.migrate_outputs(outputs, dry_run=False)
            ch2 = read_json(outputs / "drafts" / "chapter_02.meta.json", {})
            self.assertNotIn("plan_fingerprint", ch2["run_context"])


if __name__ == "__main__":
    unittest.main()
