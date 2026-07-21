"""iter147: unified, redacted production-workbench projection and Web page."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from src import drama_production_workbench, paths
from src.schemas import model_to_dict
from src.web import routes
from tests._drama_base import DramaTestBase


SHA_A = "a" * 64
SHA_B = "b" * 64
SHOT_1 = "shot_" + "1" * 24
TASK_1 = "dmt_" + "2" * 24


def _render_summary(state: str = "ready"):
    summary = drama_production_workbench.WorkbenchRenderSummary(
        state=state,
        reasons=[],
        season_no=1,
        creative_revision=SHA_A,
        plan_fingerprint=SHA_B,
        shot_count=1,
        spoken_segment_count=1,
        source_event_binding_state="fresh",
        source_event_counts={"source_derived": 1, "invented": 1, "mixed": 0},
    )
    plan = SimpleNamespace(
        shots=[
            SimpleNamespace(
                shot_id=SHOT_1,
                target_duration_seconds=5,
                is_highlight=True,
                spoken_segment_ids=["seg_ignored"],
                source_event_ids=["dse_ignored"],
            )
        ]
    )
    return summary, plan


def _asset_overview():
    version = SimpleNamespace(
        version_id="c001_v1",
        status="active",
        references=[SimpleNamespace(shot_ids=[SHOT_1])],
    )
    item = SimpleNamespace(
        kind="character",
        asset_id="c001",
        scope=None,
        selected_version_id="c001_v1",
        versions=[version],
        impact_complete=True,
    )
    return SimpleNamespace(
        blockers=[],
        sections=[SimpleNamespace(state="fresh", items=[item])],
    )


def _image_overview():
    shot = SimpleNamespace(
        shot_id=SHOT_1,
        coverage_state="covered",
        candidates=[SimpleNamespace(candidate_id="sic_" + "3" * 24)],
        first_binding={"kind": "direct"},
        tail_binding={"kind": "none"},
    )
    return SimpleNamespace(state="fresh", shots=[shot])


def _video_overview():
    shot = SimpleNamespace(
        shot_id=SHOT_1,
        coverage_state="ready",
        candidate_count=1,
        selected={"candidate_id": "svc_" + "4" * 24},
        attempt=SimpleNamespace(outcome="terminal"),
    )
    return SimpleNamespace(
        state="fresh",
        attempts=SimpleNamespace(
            state="fresh",
            not_sent_count=0,
            unknown_count=0,
            submitted_count=0,
            terminal_count=1,
        ),
        shots=[shot],
    )


def _task_projection(tasks=None):
    rows = tasks if tasks is not None else [
        {
            "task_id": TASK_1,
            "media_kind": "video",
            "stage": "video-generate",
            "subject_id": SHOT_1,
            "dependency_task_ids": [],
            "blocked_dependency_ids": [],
            "state": "succeeded",
            "revision": 2,
            "outcome_code": None,
            "backend_binding_status": "frozen",
        }
    ]
    return {
        "schema_version": 1,
        "episode_no": 1,
        "ledger_revision": 3,
        "ledger_fingerprint": SHA_A,
        "task_count": len(rows),
        "state_counts": {},
        "tasks": rows,
    }


def _compose_overview():
    return {
        "schema_version": 1,
        "episode_no": 1,
        "state": "complete",
        "ready_to_compose": False,
        "timeline_fingerprint": SHA_B,
        "duration_ms": 5000,
        "shot_count": 1,
        "subtitle_count": 1,
        "warnings": [],
        "qa": {
            "status": "passed",
            "acceptance_level": "local-e2e",
            "profile": "vertical-1080x1920-v1",
            "required_shot_count": 1,
            "covered_shot_count": 1,
            "output_size_bytes": 1234,
            "output_sha256": SHA_A,
            "qa_fingerprint": SHA_B,
        },
        "deliverables": [
            {
                "kind": "mp4",
                "filename": "episode_01.mp4",
                "url": "/api/workspace/demo/drama/compose/1/" + SHA_B + "/mp4",
            }
        ],
    }


class DramaProductionWorkbenchTests(DramaTestBase):
    def _patch_sources(self, *, task_projection=None, compose=None, video=None):
        return (
            patch.object(drama_production_workbench, "_render_summary", return_value=_render_summary()),
            patch.object(drama_production_workbench, "build_asset_web_overview", return_value=_asset_overview()),
            patch.object(drama_production_workbench, "build_shot_image_web_overview", return_value=_image_overview()),
            patch.object(
                drama_production_workbench,
                "build_shot_video_web_overview",
                return_value=video or _video_overview(),
            ),
            patch.object(
                drama_production_workbench,
                "build_media_task_projection",
                return_value=task_projection or _task_projection(),
            ),
            patch.object(
                drama_production_workbench,
                "build_compose_web_overview_readonly",
                return_value=compose or _compose_overview(),
            ),
        )

    def _build(self, **kwargs):
        patches = self._patch_sources(**kwargs)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            return drama_production_workbench.build_production_workbench("demo", episode_no=1)

    def test_projection_is_deterministic_and_list_canvas_share_source(self) -> None:
        first = self._build()
        second = self._build()
        self.assertEqual(model_to_dict(first), model_to_dict(second))
        self.assertEqual(first.state, "ready")
        self.assertEqual(first.source_projection_fingerprint, first.list_projection_fingerprint)
        self.assertEqual(first.list_projection_fingerprint, first.canvas_projection_fingerprint)
        self.assertEqual(first.render.source_event_counts["source_derived"], 1)
        self.assertEqual(first.render.source_event_counts["invented"], 1)
        self.assertEqual(first.shots[0].shot_id, SHOT_1)
        self.assertIn("shot:" + SHOT_1, {item.node_id for item in first.canvas_nodes})
        self.assertIn("task:" + TASK_1, {item.node_id for item in first.canvas_nodes})

        forged = model_to_dict(first)
        forged["render"]["shot_count"] = 2
        forged["projection_fingerprint"] = drama_production_workbench._fingerprint(
            {key: value for key, value in forged.items() if key != "projection_fingerprint"}
        )
        with self.assertRaises(ValidationError):
            drama_production_workbench.DramaProductionWorkbench(**forged)

    def test_projection_is_allowlisted_and_does_not_copy_media_urls_or_secrets(self) -> None:
        payload = json.dumps(model_to_dict(self._build()), ensure_ascii=False)
        for forbidden in (
            "/Users/private",
            "positive_tokens",
            "negative_tokens",
            "signed_url",
            "provider_raw",
            "OPENAI_API_KEY",
            "sk-secret",
            "prompt",
            "receipt_body",
        ):
            self.assertNotIn(forbidden, payload)
        self.assertNotIn("preview_url", payload)
        self.assertNotIn("created_at_ms", payload)
        self.assertNotIn("updated_at_ms", payload)

    def test_optional_missing_components_are_explicitly_incomplete(self) -> None:
        missing_asset = SimpleNamespace(
            blockers=[], sections=[SimpleNamespace(state="needs_catalog", items=[])]
        )
        missing_image = SimpleNamespace(state="needs_shot_image_assets", shots=[])
        missing_video = SimpleNamespace(
            state="needs_shot_video_assets",
            attempts=SimpleNamespace(
                state="needs_attempts",
                not_sent_count=0,
                unknown_count=0,
                submitted_count=0,
                terminal_count=0,
            ),
            shots=[],
        )
        missing_compose = {
            "state": "needs_timeline",
            "ready_to_compose": False,
            "timeline_fingerprint": None,
            "duration_ms": None,
            "shot_count": 0,
            "subtitle_count": 0,
            "warnings": [],
            "qa": None,
            "deliverables": [],
        }
        with (
            patch.object(drama_production_workbench, "_render_summary", return_value=_render_summary()),
            patch.object(drama_production_workbench, "build_asset_web_overview", return_value=missing_asset),
            patch.object(drama_production_workbench, "build_shot_image_web_overview", return_value=missing_image),
            patch.object(drama_production_workbench, "build_shot_video_web_overview", return_value=missing_video),
            patch.object(drama_production_workbench, "build_media_task_projection", return_value=_task_projection([])),
            patch.object(drama_production_workbench, "build_compose_web_overview_readonly", return_value=missing_compose),
        ):
            result = drama_production_workbench.build_production_workbench("demo")
        self.assertEqual(result.state, "incomplete")
        self.assertEqual(result.assets.state, "missing")
        self.assertEqual(result.tasks.state, "missing")
        self.assertEqual(result.timeline.state, "missing")
        self.assertEqual(result.image_state, "missing")
        self.assertEqual(result.video_state, "missing")
        self.assertEqual(result.shots[0].image_state, "missing")
        self.assertEqual(result.shots[0].video_state, "missing")

    def test_invalid_component_fails_closed_without_echoing_exception(self) -> None:
        with (
            patch.object(drama_production_workbench, "_render_summary", return_value=_render_summary()),
            patch.object(
                drama_production_workbench,
                "build_asset_web_overview",
                side_effect=ValueError("secret /Users/private/.env sk-secret"),
            ),
            patch.object(
                drama_production_workbench,
                "build_shot_image_web_overview",
                side_effect=ValueError("bad symlink"),
            ),
            patch.object(
                drama_production_workbench,
                "build_shot_video_web_overview",
                side_effect=ValueError("bad provider raw"),
            ),
            patch.object(
                drama_production_workbench,
                "build_media_task_projection",
                side_effect=ValueError("receipt body"),
            ),
            patch.object(
                drama_production_workbench,
                "build_compose_web_overview_readonly",
                side_effect=ValueError("signed url"),
            ),
        ):
            result = drama_production_workbench.build_production_workbench("demo")
        payload = json.dumps(model_to_dict(result))
        self.assertEqual(result.state, "blocked")
        self.assertEqual(result.assets.state, "invalid")
        self.assertEqual(result.tasks.state, "invalid")
        self.assertEqual(result.timeline.state, "invalid")
        self.assertEqual(result.image_state, "invalid")
        self.assertEqual(result.video_state, "invalid")
        self.assertNotIn("secret", payload)
        self.assertNotIn("receipt", payload)
        self.assertNotIn("signed url", payload)

    def test_video_overview_capacity_is_explicitly_busy(self) -> None:
        patches = self._patch_sources()
        with (
            patches[0],
            patches[1],
            patches[2],
            patch.object(
                drama_production_workbench,
                "build_shot_video_web_overview",
                side_effect=RuntimeError("overview busy"),
            ),
            patches[4],
            patches[5],
        ):
            result = drama_production_workbench.build_production_workbench("demo")
        self.assertEqual(result.video_state, "busy")
        self.assertEqual(result.state, "busy")

    def test_active_failed_and_unknown_attempt_never_present_green(self) -> None:
        for task_state in ("planned", "polling", "failed", "cancelled"):
            task = _task_projection()["tasks"][0]
            task["state"] = task_state
            result = self._build(task_projection=_task_projection([task]))
            self.assertEqual(result.tasks.state, "incomplete")
            self.assertEqual(result.state, "incomplete")

        video = _video_overview()
        video.shots[0].attempt.outcome = "unknown"
        patches = self._patch_sources()
        with (
            patches[0],
            patches[1],
            patches[2],
            patch.object(
                drama_production_workbench,
                "build_shot_video_web_overview",
                return_value=video,
            ),
            patches[4],
            patches[5],
        ):
            result = drama_production_workbench.build_production_workbench("demo")
        self.assertEqual(result.state, "blocked")
        self.assertIn("attempt_submission_unknown", result.reasons)

        # The ledger can retain a non-terminal attempt for a retired shot that
        # is absent from the current ordered-shot projection.
        video = _video_overview()
        video.attempts.unknown_count = 1
        result = self._build(video=video)
        self.assertEqual(result.video_attempts.unknown_count, 1)
        self.assertEqual(result.shots[0].latest_attempt_outcome, "terminal")
        self.assertEqual(result.state, "blocked")
        self.assertIn("attempt_submission_unknown", result.reasons)

        video = _video_overview()
        video.attempts.state = "reconciliation_required"
        result = self._build(video=video)
        self.assertEqual(result.state, "blocked")
        self.assertIn("attempt_ledger_blocked", result.reasons)

    def test_partial_stale_asset_sections_and_prop_clue_kinds_are_preserved(self) -> None:
        overview = _asset_overview()
        overview.sections.extend(
            [
                SimpleNamespace(state="needs_catalog", items=[]),
                SimpleNamespace(
                    state="fresh",
                    items=[
                        SimpleNamespace(
                            kind=kind,
                            asset_id=f"{kind}001",
                            scope=None,
                            selected_version_id=f"{kind}001_v1",
                            versions=[
                                SimpleNamespace(
                                    version_id=f"{kind}001_v1",
                                    status="active",
                                    references=[],
                                )
                            ],
                            impact_complete=True,
                        )
                        for kind in ("prop", "clue")
                    ],
                ),
            ]
        )
        with patch.object(
            drama_production_workbench,
            "build_asset_web_overview",
            return_value=overview,
        ):
            summary = drama_production_workbench._safe_asset_summary("demo", 1, 1)
        self.assertEqual(summary.state, "incomplete")
        self.assertEqual({item.kind for item in summary.items}, {"character", "prop", "clue"})

        overview.sections[0].state = "stale"
        with patch.object(
            drama_production_workbench,
            "build_asset_web_overview",
            return_value=overview,
        ):
            summary = drama_production_workbench._safe_asset_summary("demo", 1, 1)
        self.assertEqual(summary.state, "stale")

    def test_unknown_task_subject_is_redacted_and_long_timeline_is_valid(self) -> None:
        task = _task_projection()["tasks"][0]
        task["subject_id"] = "sk-secret"
        compose = _compose_overview()
        compose["duration_ms"] = 600_000
        result = self._build(
            task_projection=_task_projection([task]),
            compose=compose,
        )
        self.assertIsNone(result.tasks.tasks[0].subject_id)
        self.assertEqual(result.timeline.duration_ms, 600_000)
        self.assertNotIn("sk-secret", json.dumps(model_to_dict(result)))

    def test_task_projection_is_bounded_and_submission_unknown_blocks(self) -> None:
        tasks = []
        for index in range(260):
            dependencies = [
                "dmt_" + f"{previous:024x}"
                for previous in range(max(0, index - 32), index)
            ]
            tasks.append(
                {
                    "task_id": "dmt_" + f"{index:024x}",
                    "media_kind": "image",
                    "stage": "image-generate",
                    "subject_id": SHOT_1,
                    "dependency_task_ids": dependencies,
                    "blocked_dependency_ids": dependencies,
                    "state": "submission_unknown" if index == 0 else "planned",
                    "revision": 1,
                    "outcome_code": None,
                    "backend_binding_status": "frozen",
                }
            )
        result = self._build(task_projection=_task_projection(tasks))
        self.assertEqual(len(result.tasks.tasks), 256)
        self.assertEqual(result.tasks.omitted_count, 4)
        self.assertEqual(result.tasks.unknown_count, 1)
        self.assertEqual(result.tasks.state, "blocked")
        self.assertEqual(result.state, "blocked")
        self.assertEqual(len(result.canvas_edges), 1500)
        self.assertGreater(result.canvas_omitted_edge_count, 0)

    def test_page_api_and_frontend_are_drama_only_and_read_only(self) -> None:
        self._make_drama_workspace("production-web")
        status, _content_type, body = routes.dispatch("GET", "/w/production-web/production")
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn("生产工作台", html)
        self.assertIn('window.PAGE_KIND = "drama_production"', html)
        self.assertIn("production-page-root", html)
        self.assertIn('role="tab"', html)
        self.assertIn('aria-controls="production-panel-canvas"', html)
        js = routes.static.JS_DASHBOARD
        self.assertIn("initDramaProduction", js)
        self.assertIn("list_projection_fingerprint !== projection.canvas_projection_fingerprint", js)
        self.assertIn('["ArrowLeft", "ArrowRight", "Home", "End"]', js)
        self.assertIn('role="tabpanel"', js)
        self.assertIn("data.video_attempts", js)
        self.assertNotIn('wsUrl("/drama/production"),', js)

        projection = self._build()
        with patch.object(
            drama_production_workbench,
            "build_production_workbench",
            return_value=projection,
        ):
            status, content_type, body = routes.dispatch(
                "GET", "/api/workspace/production-web/drama/production?episode_no=1"
            )
        self.assertEqual(status, 200)
        self.assertIn("application/json", content_type)
        self.assertEqual(json.loads(body)["projection_fingerprint"], projection.projection_fingerprint)

        from src.cli_workspace import init_workspace

        init_workspace("production-novel", type="novel")
        self.assertEqual(routes.dispatch("GET", "/w/production-novel/production")[0], 404)
        self.assertEqual(
            routes.dispatch("GET", "/api/workspace/production-novel/drama/production")[0],
            400,
        )

    def test_real_missing_workspace_projection_is_zero_network_and_graceful(self) -> None:
        self._make_drama_workspace("production-empty")
        lock = paths.workspace_root("production-empty") / "write.lock"
        self.assertFalse(lock.exists())
        with patch("socket.socket.connect", side_effect=AssertionError("network forbidden")):
            status, content_type, body = routes.dispatch(
                "GET", "/api/workspace/production-empty/drama/production?episode_no=1"
            )
        self.assertEqual(status, 200, body.decode(errors="replace"))
        self.assertIn("application/json", content_type)
        payload = json.loads(body)
        self.assertEqual(payload["state"], "blocked")
        self.assertEqual(payload["render"]["state"], "blocked")
        self.assertEqual(payload["shots"], [])
        self.assertEqual(
            payload["list_projection_fingerprint"],
            payload["canvas_projection_fingerprint"],
        )
        self.assertFalse(lock.exists())

    def test_invalid_episode_is_rejected_before_projection(self) -> None:
        self._make_drama_workspace("production-bad-episode")
        with patch.object(
            drama_production_workbench,
            "build_production_workbench",
        ) as builder:
            response = routes.dispatch(
                "GET",
                "/api/workspace/production-bad-episode/drama/production?episode_no=101",
            )
        self.assertEqual(response[0], 400)
        builder.assert_not_called()


if __name__ == "__main__":
    import unittest

    unittest.main()
