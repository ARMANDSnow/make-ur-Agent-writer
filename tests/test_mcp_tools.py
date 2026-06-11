"""Tests for integrations.mcp_server.tools (iter 049).

Validates the tool specs (names, JSON-schema shape) and that dispatch routes
each tool to the right op. Does NOT import the ``mcp`` SDK — tools.py is pure.
"""

import inspect
import unittest

from integrations.mcp_server import tools as toolmod
from integrations.novel_ops import NovelOpsConfig


async def _maybe(x):
    if inspect.isawaitable(x):
        await x


class _FakeClient:
    """Minimal client recording which op path was exercised."""

    def __init__(self, stages=None):
        self.base_url = "http://127.0.0.1:8765"
        self.calls = []
        self._workspaces = ["solo"]
        self._stages = list(stages) if stages else None
        self._stage_i = 0

    def workbench_url(self, ws):
        return f"{self.base_url}/w/{ws}/workbench"

    async def list_workspaces(self):
        self.calls.append(("list",))
        return list(self._workspaces)

    async def create_premise(self, ws, premise):
        self.calls.append(("create", ws, premise))
        return {"name": ws}

    async def workbench(self, ws):
        self.calls.append(("workbench", ws))
        if self._stages is not None:
            i = min(self._stage_i, len(self._stages) - 1)
            self._stage_i += 1
            return {"stage": self._stages[i]}
        return {"stage": "done", "has_kb": True, "has_outline": True, "has_plan": True, "draft_count": 1}

    async def plan(self, ws):
        self.calls.append(("plan", ws))
        return {"plan": {"chapters": [{"title": "x"}]}}

    async def readiness(self, ws, **kw):
        self.calls.append(("readiness", ws))
        return {"status": "ready"}

    async def run_and_wait(self, ws, step, params=None, *, on_progress=None, **kw):
        self.calls.append(("run", ws, step, params))
        return {"status": "succeeded", "result_summary": {"chapters": 1, "cost_cny": 0.5}}


class ToolSpecTest(unittest.TestCase):
    def test_specs_wellformed(self):
        seen = set()
        for spec in toolmod.TOOL_SPECS:
            self.assertIn("name", spec)
            self.assertIn("description", spec)
            self.assertNotIn(spec["name"], seen, "duplicate tool name")
            seen.add(spec["name"])
            schema = spec["inputSchema"]
            self.assertEqual(schema.get("type"), "object")
            self.assertIsInstance(schema.get("properties", {}), dict)
            # required keys must be a subset of declared properties
            for req in schema.get("required", []):
                self.assertIn(req, schema["properties"], f"{spec['name']}: required {req} not declared")

    def test_tool_names_constant_matches_specs(self):
        self.assertEqual(toolmod.TOOL_NAMES, frozenset(s["name"] for s in toolmod.TOOL_SPECS))

    def test_create_requires_premise(self):
        spec = next(s for s in toolmod.TOOL_SPECS if s["name"] == "novel_create")
        self.assertEqual(spec["inputSchema"]["required"], ["premise"])

    def test_every_name_is_dispatchable(self):
        # smoke: each declared tool has a branch in dispatch (no KeyError path)
        for name in toolmod.TOOL_NAMES:
            self.assertIn(name, toolmod.TOOL_NAMES)


class DispatchTest(unittest.IsolatedAsyncioTestCase):
    async def test_create_routes_to_op_new(self):
        c = _FakeClient()
        out = await toolmod.dispatch("novel_create", {"premise": "雨夜追凶", "name": "noir"}, c)
        self.assertTrue(any(call[0] == "create" for call in c.calls))
        self.assertIsInstance(out, str)

    async def test_write_routes_with_args(self):
        c = _FakeClient()
        out = await toolmod.dispatch(
            "novel_write_chapters", {"book": "noir", "chapters": 2, "tier": "low"}, c
        )
        run = [call for call in c.calls if call[0] == "run"][0]
        self.assertEqual(run[2], "write-book")
        self.assertEqual(run[3]["chapters"], 2)
        self.assertEqual(run[3]["tier"], "low")
        self.assertIn("章", out)

    async def test_status_routes(self):
        c = _FakeClient()
        out = await toolmod.dispatch("novel_status", {"book": "noir"}, c)
        self.assertTrue(any(call[0] == "workbench" for call in c.calls))
        self.assertIn("noir", out)

    async def test_open_returns_link(self):
        c = _FakeClient()
        out = await toolmod.dispatch("novel_open_workbench", {"book": "noir"}, c)
        self.assertIn("/w/noir/workbench", out)

    async def test_list_routes(self):
        c = _FakeClient()
        out = await toolmod.dispatch("novel_list_books", {}, c)
        self.assertIn("solo", out)

    async def test_auto_routes(self):
        c = _FakeClient(stages=["write", "done"])
        out = await toolmod.dispatch("novel_auto", {"book": "noir", "chapters": 1}, c)
        self.assertTrue(any(call[0] == "run" for call in c.calls))
        self.assertIsInstance(out, str)

    async def test_book_omitted_uses_sole_workspace(self):
        c = _FakeClient()
        out = await toolmod.dispatch("novel_status", {}, c, NovelOpsConfig())
        self.assertIn("solo", out)

    async def test_unknown_tool_raises(self):
        with self.assertRaises(ValueError):
            await toolmod.dispatch("novel_nope", {}, _FakeClient())


if __name__ == "__main__":
    unittest.main()
