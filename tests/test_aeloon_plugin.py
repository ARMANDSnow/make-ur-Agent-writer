"""Tests for integrations.aeloon_plugin command surface (iter 049).

Covers the SDK-free layer only: ``parse_novel_command`` branch coverage +
``run_novel_command`` routing / emit pass-through. The Aeloon SDK is never
imported here (``plugin.py`` is the sole SDK-coupled module; it is exercised by
the real-SDK smoke recorded in ``docs/iterations/iteration_049_PLAN.md``), so
these run clean under ``OPENAI_MODEL=mock``.
"""

import inspect
import unittest

from integrations.aeloon_plugin import HELP_TEXT, parse_novel_command, run_novel_command
from integrations.novel_ops import NovelOpsConfig


async def _maybe(x):
    if inspect.isawaitable(x):
        await x


class FakeClient:
    """Minimal in-memory client: records run-step calls, returns succeeded."""

    def __init__(self, workspaces=None, workbench=None, plan=None, readiness=None):
        self.base_url = "http://127.0.0.1:8765"
        self._workspaces = list(workspaces if workspaces is not None else ["demo"])
        self._workbench = workbench or {
            "stage": "done", "has_kb": True, "has_outline": True,
            "has_plan": True, "draft_count": 1,
        }
        self._plan = plan or {"plan": {"chapters": [{"title": "起"}]}}
        self._readiness = readiness or {"status": "ready"}
        self.calls = []

    def workbench_url(self, ws):
        return f"{self.base_url}/w/{ws}/workbench"

    async def list_workspaces(self):
        self.calls.append(("list",))
        return list(self._workspaces)

    async def create_premise(self, ws, premise):
        self.calls.append(("create", ws, premise))
        self._workspaces.append(ws)
        return {"name": ws}

    async def workbench(self, ws):
        self.calls.append(("workbench", ws))
        return dict(self._workbench)

    async def plan(self, ws):
        self.calls.append(("plan", ws))
        return self._plan

    async def readiness(self, ws, **kw):
        self.calls.append(("readiness", ws, kw))
        return self._readiness

    async def run_and_wait(self, ws, step, params=None, *, on_progress=None, **kw):
        self.calls.append(("run", ws, step, params))
        if on_progress is not None:
            await _maybe(on_progress(step, 1.0))
        return {"status": "succeeded", "result_summary": {"chapters": 1, "cost_cny": 0.5}}

    def runs(self):
        return [c for c in self.calls if c[0] == "run"]


class ParseTest(unittest.TestCase):
    def test_empty_and_help(self):
        self.assertEqual(parse_novel_command(""), ("help", {}))
        self.assertEqual(parse_novel_command("   "), ("help", {}))
        self.assertEqual(parse_novel_command("help")[0], "help")
        self.assertEqual(parse_novel_command("帮助")[0], "help")
        self.assertEqual(parse_novel_command("bogus xyz")[0], "help")

    def test_new_premise_and_name(self):
        self.assertEqual(
            parse_novel_command("new 赛博朋克侦探"),
            ("new", {"premise": "赛博朋克侦探", "name": None}),
        )
        self.assertEqual(
            parse_novel_command("new 主角觉醒 as 觉醒纪"),
            ("new", {"premise": "主角觉醒", "name": "觉醒纪"}),
        )
        self.assertEqual(
            parse_novel_command("开书 一句话设定"),
            ("new", {"premise": "一句话设定", "name": None}),
        )

    def test_count_and_book_tail(self):
        self.assertEqual(parse_novel_command("write"), ("write", {}))
        self.assertEqual(parse_novel_command("write 3"), ("write", {"chapters": 3}))
        self.assertEqual(
            parse_novel_command("write 龙族 2"),
            ("write", {"book": "龙族", "chapters": 2}),
        )
        self.assertEqual(parse_novel_command("outline 5"), ("outline", {"chapters": 5}))
        self.assertEqual(parse_novel_command("auto 2"), ("auto", {"chapters": 2}))

    def test_book_only_verbs(self):
        self.assertEqual(parse_novel_command("status"), ("status", {"book": None}))
        self.assertEqual(parse_novel_command("status 龙族"), ("status", {"book": "龙族"}))
        self.assertEqual(parse_novel_command("open"), ("open", {"book": None}))
        self.assertEqual(parse_novel_command("prepare 龙族"), ("prepare", {"book": "龙族"}))
        self.assertEqual(parse_novel_command("list"), ("list", {}))

    def test_new_with_multiple_as_takes_last(self):
        # premise may legitimately contain " as "; rpartition splits on the last
        self.assertEqual(
            parse_novel_command("new foo as bar as baz"),
            ("new", {"premise": "foo as bar", "name": "baz"}),
        )

    def test_new_with_empty_name_falls_back(self):
        # trailing "as" with no name is not a separator (" as " needs the
        # trailing space + a name), so it stays part of the premise.
        self.assertEqual(
            parse_novel_command("new foo as"),
            ("new", {"premise": "foo as", "name": None}),
        )

    def test_count_tail_edge_cases(self):
        # digit-leading book name is NOT mistaken for a count (has non-digit char)
        self.assertEqual(
            parse_novel_command("write 2024年 3"),
            ("write", {"book": "2024年", "chapters": 3}),
        )
        # a negative token is treated as a book name, never negative chapters
        self.assertEqual(parse_novel_command("write -5"), ("write", {"book": "-5"}))


class RunRoutingTest(unittest.IsolatedAsyncioTestCase):
    async def test_help_returns_help_text(self):
        out = await run_novel_command("help", {}, FakeClient(), NovelOpsConfig())
        self.assertEqual(out, HELP_TEXT)

    async def test_new_routes_to_op_new_with_emit(self):
        c = FakeClient(workspaces=[])
        seen = []
        await run_novel_command(
            "new", {"premise": "一个故事", "name": "b"}, c, NovelOpsConfig(),
            emit=lambda m: seen.append(m),
        )
        self.assertIn(("create", "b", "一个故事"), c.calls)
        self.assertIn(("run", "b", "prepare-greenfield", {}), c.calls)
        self.assertTrue(seen)  # progress emitted through

    async def test_write_routes_and_resolves_sole_book(self):
        c = FakeClient(workspaces=["only"])
        await run_novel_command("write", {"chapters": 1}, c, NovelOpsConfig())
        self.assertEqual(c.runs()[0][1:3], ("only", "write-book"))

    async def test_outline_routes(self):
        c = FakeClient(workspaces=["only"], workbench={"stage": "outline", "has_outline": False})
        await run_novel_command("outline", {"chapters": 3}, c, NovelOpsConfig())
        self.assertIn("plan-chapters", [r[2] for r in c.runs()])

    async def test_status_open_list_routes(self):
        c = FakeClient(workspaces=["only"])
        s = await run_novel_command("status", {"book": None}, c, NovelOpsConfig())
        self.assertIn("only", s)
        o = await run_novel_command("open", {"book": "only"}, c, NovelOpsConfig())
        self.assertIn("/w/only/workbench", o)
        listed = await run_novel_command("list", {}, c, NovelOpsConfig())
        self.assertIn("only", listed)

    async def test_unknown_verb_falls_back_to_help(self):
        out = await run_novel_command("nope", {}, FakeClient(), NovelOpsConfig())
        self.assertEqual(out, HELP_TEXT)

    async def test_unexpected_exception_degrades_gracefully(self):
        # an op raising a non-NovelApiError (KeyError/TypeError/…) must NOT
        # bubble out of run_novel_command — it degrades to a friendly string
        # so the host's chat handler never crashes.
        class BrokenClient(FakeClient):
            async def list_workspaces(self):
                raise KeyError("boom")

        out = await run_novel_command("list", {}, BrokenClient(), NovelOpsConfig())
        self.assertIn("出错", out)
        self.assertIn("KeyError", out)


if __name__ == "__main__":
    unittest.main()
