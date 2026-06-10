"""Tests for integrations.novel_ops (iter 049).

A FakeClient (no HTTP, no event loop fuss beyond IsolatedAsyncioTestCase)
pins command routing, default-book resolution, greenfield require_start_point
handling, deep-link composition, and the blocked-readiness guard.
"""

import inspect
import unittest

from integrations.novel_client import NovelApiError
from integrations.novel_ops import (
    NovelOpsConfig,
    op_auto,
    op_list,
    op_new,
    op_open,
    op_outline,
    op_status,
    op_write,
)


async def _maybe(x):
    if inspect.isawaitable(x):
        await x


class FakeClient:
    def __init__(
        self,
        *,
        workspaces=None,
        workbench=None,
        workbench_seq=None,
        plan=None,
        readiness=None,
        job_results=None,
        create_raises=None,
    ):
        self.base_url = "http://127.0.0.1:8765"
        self._workspaces = list(workspaces or [])
        self._workbench = workbench
        self._workbench_seq = list(workbench_seq) if workbench_seq else None
        self._wb_i = 0
        self._plan = plan or {}
        self._readiness = readiness or {"status": "ready"}
        self._job_results = job_results or {}
        self._create_raises = create_raises
        self.calls = []

    def workbench_url(self, ws):
        return f"{self.base_url}/w/{ws}/workbench"

    async def list_workspaces(self):
        self.calls.append(("list",))
        return list(self._workspaces)

    async def create_premise(self, ws, premise):
        self.calls.append(("create", ws, premise))
        if self._create_raises:
            raise self._create_raises
        self._workspaces.append(ws)
        return {"name": ws}

    async def workbench(self, ws):
        self.calls.append(("workbench", ws))
        if self._workbench_seq is not None:
            i = min(self._wb_i, len(self._workbench_seq) - 1)
            self._wb_i += 1
            return self._workbench_seq[i]
        return self._workbench or {"stage": "outline", "has_kb": True}

    async def plan(self, ws):
        self.calls.append(("plan", ws))
        return self._plan

    async def readiness(self, ws, **kw):
        self.calls.append(("readiness", ws, kw))
        return self._readiness

    async def run_and_wait(self, ws, step, params=None, *, on_progress=None, **kw):
        self.calls.append(("run", ws, step, params))
        if on_progress is not None:
            await _maybe(on_progress(step, 0.5))
            await _maybe(on_progress(step, 1.0))
        job = dict(self._job_results.get(step, {"status": "succeeded"}))
        job.setdefault("status", "succeeded")
        return job

    # convenience for assertions
    def runs(self):
        return [c for c in self.calls if c[0] == "run"]


class ResolveBookTest(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_book_wins(self):
        c = FakeClient(workspaces=["a", "b"])
        out = await op_open(c, "chosen", cfg=NovelOpsConfig(default_book="cfgbook"))
        self.assertIn("chosen", out)
        self.assertNotIn("list", [x[0] for x in c.calls])  # no need to list

    async def test_config_default_used(self):
        c = FakeClient(workspaces=["a", "b"])
        out = await op_open(c, None, cfg=NovelOpsConfig(default_book="cfgbook"))
        self.assertIn("cfgbook", out)

    async def test_sole_workspace_auto(self):
        c = FakeClient(workspaces=["only"])
        out = await op_open(c, None)
        self.assertIn("only", out)

    async def test_ambiguous_asks(self):
        c = FakeClient(workspaces=["a", "b"])
        out = await op_status(c, None)
        self.assertIn("请指定书名", out)


class OpListTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty(self):
        out = await op_list(FakeClient(workspaces=[]))
        self.assertIn("还没有任何作品", out)

    async def test_listed(self):
        out = await op_list(FakeClient(workspaces=["龙族", "alpha"]))
        self.assertIn("龙族", out)
        self.assertIn("2 部作品", out)

    async def test_api_error(self):
        c = FakeClient()

        async def boom():
            raise NovelApiError(0, None, "down")

        c.list_workspaces = lambda: boom()
        out = await op_list(c)
        self.assertIn("连不上", out)


class OpNewTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_strips_invalid_name_and_prepares(self):
        c = FakeClient()
        seen = []
        out = await op_new(c, "一个赛博朋克侦探故事!!! @#$", emit=lambda m: seen.append(m))
        # invalid punctuation/space stripped from the derived workspace name
        create = [x for x in c.calls if x[0] == "create"][0]
        self.assertEqual(create[1], "一个赛博朋克侦探故事")
        # auto-ran the cheap prepare step
        self.assertIn(("run", "一个赛博朋克侦探故事", "prepare-greenfield", {}), c.calls)
        self.assertIn("已创建", out)
        self.assertIn("/w/", out)  # deep link present
        self.assertTrue(seen)  # progress narrated

    async def test_explicit_name(self):
        c = FakeClient()
        await op_new(c, "随便写点啥", name="my_book")
        create = [x for x in c.calls if x[0] == "create"][0]
        self.assertEqual(create[1], "my_book")

    async def test_conflict_409(self):
        c = FakeClient(create_raises=NovelApiError(409, {"error": "exists"}))
        out = await op_new(c, "abc", name="dup")
        self.assertIn("已存在", out)

    async def test_empty_premise(self):
        out = await op_new(FakeClient(), "   ")
        self.assertIn("一句话设定", out)

    async def test_prepare_blocked_reported(self):
        c = FakeClient(job_results={"prepare-greenfield": {"status": "failed", "error": "X"}})
        out = await op_new(c, "abc", name="b")
        self.assertIn("failed", out)


class OpOutlineTest(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_stage_blocks(self):
        c = FakeClient(workbench={"stage": "prepare"})
        out = await op_outline(c, "b")
        self.assertIn("还没做设定准备", out)
        self.assertEqual(c.runs(), [])  # nothing run

    async def test_runs_debate_then_plan_when_no_outline(self):
        c = FakeClient(
            workbench={"stage": "outline", "has_outline": False},
            plan={"plan": {"chapters": [{"title": "起"}, {"title": "承"}, {"title": "转"}]}},
        )
        out = await op_outline(c, "b", 3)
        steps = [r[2] for r in c.runs()]
        self.assertEqual(steps, ["debate", "plan-chapters"])
        # greenfield: plan-chapters must relax the start-point gate
        plan_run = [r for r in c.runs() if r[2] == "plan-chapters"][0]
        self.assertEqual(plan_run[3]["require_start_point"], False)
        self.assertEqual(plan_run[3]["target_chapters"], 3)
        self.assertIn("3 章", out)
        self.assertIn("承", out)

    async def test_skips_debate_when_outline_exists(self):
        c = FakeClient(
            workbench={"stage": "plan", "has_outline": True},
            plan={"plan": {"chapters": [{"title": "x"}]}},
        )
        await op_outline(c, "b")
        steps = [r[2] for r in c.runs()]
        self.assertEqual(steps, ["plan-chapters"])


class OpWriteTest(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_readiness_does_not_write(self):
        c = FakeClient(
            readiness={"status": "blocked", "blockers": ["outline_missing"], "recommended_commands": []}
        )
        out = await op_write(c, "b", 1)
        self.assertIn("还不能写正文", out)
        self.assertEqual(c.runs(), [])  # write-book never started

    async def test_writes_with_greenfield_params(self):
        c = FakeClient(
            readiness={"status": "ready"},
            job_results={"write-book": {"status": "succeeded", "result_summary": {"chapters": 2, "cost_cny": 1.5}}},
        )
        out = await op_write(c, "b", 2, cfg=NovelOpsConfig(write_tier="low", write_budget_cny=3.0))
        run = c.runs()[0]
        self.assertEqual(run[2], "write-book")
        self.assertEqual(run[3]["chapters"], 2)
        self.assertEqual(run[3]["tier"], "low")
        self.assertEqual(run[3]["budget_cny"], 3.0)
        self.assertEqual(run[3]["require_start_point"], False)
        self.assertIn("2 章", out)
        self.assertIn("¥1.50", out)

    async def test_write_blocked_job(self):
        c = FakeClient(
            readiness={"status": "ready"},
            job_results={"write-book": {"status": "blocked", "result_summary": {"first_blocked": {"reason": "foreshadow_gate"}}}},
        )
        out = await op_write(c, "b", 1)
        self.assertIn("拦截", out)
        self.assertIn("foreshadow_gate", out)


class OpAutoTest(unittest.IsolatedAsyncioTestCase):
    async def test_drives_full_pipeline(self):
        # workbench reports successively advancing stages until done
        c = FakeClient(
            workbench_seq=[
                {"stage": "prepare"},
                {"stage": "outline"},
                {"stage": "plan"},
                {"stage": "write"},
                {"stage": "done"},
            ],
            job_results={"write-book": {"status": "succeeded", "result_summary": {"chapters": 1, "cost_cny": 0.9}}},
        )
        out = await op_auto(c, "b", 1)
        steps = [r[2] for r in c.runs()]
        self.assertEqual(steps, ["prepare-greenfield", "debate", "plan-chapters", "write-book"])
        self.assertIn("1 章", out)

    async def test_stops_on_blocked_step(self):
        c = FakeClient(
            workbench_seq=[{"stage": "outline"}],
            job_results={"debate": {"status": "failed", "error": "kapow"}},
        )
        out = await op_auto(c, "b")
        self.assertIn("kapow", out)
        self.assertEqual([r[2] for r in c.runs()], ["debate"])


if __name__ == "__main__":
    unittest.main()
