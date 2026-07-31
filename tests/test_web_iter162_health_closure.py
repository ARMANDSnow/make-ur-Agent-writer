"""Iteration 162 regressions for the 2026-7-30/31 health reports."""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

from src.web import jobs, routes, static
from tests._drama_base import DramaTestBase


def _slice(source: str, start: str, end: str) -> str:
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


class WebIter162HealthClosureTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.workspace = "iter162"
        self._make_drama_workspace(self.workspace)

    def _node_json(self, script: str) -> dict:
        completed = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_public_job_views_drop_provider_task_identity(self) -> None:
        result = {
            "status": "succeeded",
            "cost_cny": 1.25,
            "task_id": "mvt-synthetic-id",
            "provider": "video.example",
            "provider_model": "model-v1",
        }
        record = jobs._new_job_record(self.workspace, "drama-video", {"episode_no": 1})
        record["result_summary"] = dict(result)
        for view in (
            jobs.public_job_summary_view(record),
            jobs.public_job_detail_view(record),
        ):
            public_result = view["result_summary"]
            self.assertEqual(public_result["status"], "succeeded")
            self.assertEqual(public_result["cost_cny"], 1.25)
            for private_key in ("task_id", "provider", "provider_model"):
                self.assertNotIn(private_key, public_result)
        summarized = jobs._summarize_result("drama-video", result)
        self.assertEqual(summarized["status"], "succeeded")
        for private_key in ("task_id", "provider", "provider_model"):
            self.assertNotIn(private_key, summarized)
        self.assertEqual(result["task_id"], "mvt-synthetic-id")

    def test_episode_two_overview_and_production_dom_keep_public_context(self) -> None:
        episode_helpers = _slice(
            static.JS_DASHBOARD,
            "  function dramaEpisodeFromUrl()",
            "  function hydrateDramaEpisodeInput(",
        )
        overview = _slice(
            static.JS_DASHBOARD,
            "  async function loadDramaOverview()",
            "  function initDeleteWorkspace()",
        )
        overview_result = self._node_json(
            "const links = ["
            "{href:'http://127.0.0.1/w/iter162/',setAttribute(k,v){this[k]=v;}},"
            "{href:'http://127.0.0.1/w/iter162/production',setAttribute(k,v){this[k]=v;}},"
            "{href:'http://127.0.0.1/w/iter162/write',setAttribute(k,v){this[k]=v;}}];\n"
            "const boxes = {}; for (const id of ['drama-overview-progress','drama-next-headline',"
            "'drama-overview-summary','drama-next-reason','drama-next-actions','drama-overview-recent-task']) "
            "boxes[id]={innerHTML:'',textContent:'',querySelector:()=>null};\n"
            "const document={querySelectorAll:()=>links,getElementById:(id)=>boxes[id]};\n"
            "const window={location:{href:'http://127.0.0.1/w/iter162/?episode_no=2',origin:'http://127.0.0.1'},CHAPTER_NO:null};\n"
            "const wsHref=(s)=>'/w/iter162'+s; const wsUrl=String; const requests=[];\n"
            "const fetchJson=async(url)=>{requests.push(url); if(url.includes('/drama/progress')) return {episode_no:2,stations:[{status:'todo',id:'storyboard',label:'分镜'}]}; if(url.includes('/drama/production')) return {state:'incomplete',shots:[]}; return {jobs:[]};};\n"
            "const skeleton=()=>''; const escapeHtml=String; const emptyState=(a,b,c)=>c;"
            "const productionStateLabel=String; const statusBadge=String; const stepLabel=String;"
            "const productionReasonText=String; const publicLoadError=String;\n"
            + episode_helpers
            + overview
            + "\n(async()=>{const valid=dramaEpisodeFromUrl(); await loadDramaOverview();"
            "const cases=[]; for(const value of ['0','101','bad']){window.location.href='http://127.0.0.1/w/iter162/?episode_no='+value;cases.push(dramaEpisodeFromUrl());}"
            "console.log(JSON.stringify({valid,cases,requests,actions:boxes['drama-next-actions'].innerHTML,links:links.map(x=>x.href)}));})().catch(e=>{console.error(e);process.exit(1);});"
        )
        self.assertEqual(overview_result["valid"], 2)
        self.assertEqual(overview_result["cases"], [1, 1, 1])
        self.assertIn("/drama/progress?episode_no=2", overview_result["requests"])
        self.assertIn("/drama/production?episode_no=2", overview_result["requests"])
        self.assertIn("/write?episode=2&step=storyboard", overview_result["actions"])
        self.assertEqual(
            overview_result["links"],
            [
                "/w/iter162/?episode_no=2",
                "/w/iter162/production?episode_no=2",
                "/w/iter162/write?episode=2",
            ],
        )

        production = _slice(
            static.JS_DASHBOARD,
            "  function productionBadge(",
            "  function renderProductionShotDetail(",
        )
        result = self._node_json(
            "const escapeHtml = String;\n"
            "const productionStateLabel = String;\n"
            "const wsHref = (value) => value;\n"
            "const emptyState = (title, body, action) => action;\n"
            "const renderProductionShotDetail = () => '';\n"
            + production
            + "\nconst row = renderProductionList({episode_no:2, shots:[{"
            "shot_id:'stable-private-shot-id',sequence:1,image_state:'missing',"
            "video_state:'missing',target_duration_seconds:3}], timeline:{}});"
            "const empty = renderProductionList({episode_no:2,shots:[],timeline:{}});"
            "console.log(JSON.stringify({row,empty}));"
        )
        self.assertIn('data-shot-sequence="1"', result["row"])
        self.assertNotIn("stable-private-shot-id", result["row"])
        self.assertNotIn("data-shot-id", result["row"])
        self.assertIn("/write?episode=2&step=review", result["empty"])

        production_init = _slice(
            static.JS_DASHBOARD,
            "  async function initDramaProduction()",
            "  function composeStateLabel(",
        )
        selected = self._node_json(
            "let clickHandler=null; const entry={dataset:{shotSequence:'2'},focus(){},addEventListener(t,fn){if(t==='click')clickHandler=fn;}};\n"
            "const root={innerHTML:'',__localDemoHistory:null,setAttribute(){},removeAttribute(){},insertAdjacentHTML(){},querySelectorAll:()=>[entry],querySelector:()=>entry};\n"
            "const input={value:'2',addEventListener(){}}; const document={getElementById:(id)=>id==='production-page-root'?root:id==='production-episode-no'?input:null,querySelectorAll:()=>[]};\n"
            "const window={confirm:()=>false,location:{href:'http://127.0.0.1/w/iter162/production?episode_no=2'}};"
            "const localStorage={getItem:()=>'',removeItem(){},setItem(){}}; const sessionStorage={setItem(){}};\n"
            "const hydrateDramaEpisodeInput=()=>{}; const dramaEpisodeFromInput=()=>2; const wsUrl=String;"
            "const renderLocalDemoHistory=()=>''; const renderProductionSummary=()=>'';"
            "const renderProductionList=(p)=>'selected:'+String(p.__selectedSequence||1); const renderProductionCanvas=()=>'';"
            "const renderErrorCard=String; const localDemoPendingKey=String; const localDemoTarget=()=>null;"
            "const localDemoTargetHref=()=>''; const fetchJson=async(url)=>url.includes('/drama/production')?{list_projection_fingerprint:'same',canvas_projection_fingerprint:'same'}:{jobs:[]};\n"
            + production_init
            + "\n(async()=>{await initDramaProduction(); clickHandler(); console.log(JSON.stringify({html:root.innerHTML,sequence:entry.dataset.shotSequence}));})().catch(e=>{console.error(e);process.exit(1);});"
        )
        self.assertEqual(selected["sequence"], "2")
        self.assertIn("selected:2", selected["html"])

    def test_degraded_insights_render_unknown_instead_of_placeholder_zero(self) -> None:
        insights = _slice(
            static.JS_DASHBOARD,
            "  async function initDramaInsights()",
            "  function renderDramaReviewCard(",
        )
        script = (
            "const boxes = {}; for (const id of ['drama-insights-summary','drama-insights-cost',"
            "'drama-insights-media-metrics','drama-insights-duration','drama-insights-hooks']) "
            "boxes[id] = {innerHTML:''};\n"
            "const document = {getElementById:(id)=>boxes[id]};\n"
            "const skeleton = () => ''; const escapeHtml = String; const tableScroll = String;\n"
            "const wsUrl = String; const renderErrorCard = (e) => String(e);\n"
            "let payload = {llm_cost:{status:'ok',cost_cny:0,calls:0},"
            "episode_meta_cost:{status:'ok',cost_cny:0,episodes:0},"
            "media_pricing:{status:'ok',currencies:[]},"
            "media_metrics:{status:'degraded',task_count:0,succeeded_count:0,failed_count:0,"
            "cancelled_count:0,terminal_count:0,unknown_submission_count:0},"
            "duration:{status:'degraded',total:0},hook_types:[]};\n"
            "const fetchJson = async () => payload;\n"
            + insights
            + "\n(async()=>{await initDramaInsights(); const degraded={summary:boxes['drama-insights-summary'].innerHTML,metrics:boxes['drama-insights-media-metrics'].innerHTML,duration:boxes['drama-insights-duration'].innerHTML};"
            "payload={llm_cost:{status:'ok',cost_cny:0,calls:0},episode_meta_cost:{status:'ok',cost_cny:0,episodes:0},media_pricing:{status:'ok',currencies:[]},media_metrics:{status:'ok',task_count:0,succeeded_count:0,failed_count:0,cancelled_count:0,terminal_count:0,unknown_submission_count:0},duration:{status:'ok',total:0,within_tolerance:0,rate:0,tolerance_seconds:3},hook_types:[]};"
            "await initDramaInsights(); const ok={summary:boxes['drama-insights-summary'].innerHTML,metrics:boxes['drama-insights-media-metrics'].innerHTML,duration:boxes['drama-insights-duration'].innerHTML};"
            "console.log(JSON.stringify({degraded,ok}));})().catch(e=>{console.error(e);process.exit(1);});"
        )
        rendered = self._node_json(script)
        self.assertIn("指标来源待核对", rendered["degraded"]["summary"])
        self.assertIn("时长来源待核对", rendered["degraded"]["summary"])
        self.assertNotIn("当前没有未知样本", rendered["degraded"]["summary"])
        self.assertIn("— · 来源待核对", rendered["degraded"]["metrics"])
        self.assertNotIn("任务</div><div class=\"v\">0", rendered["degraded"]["metrics"])
        self.assertIn("时长来源待核对", rendered["degraded"]["duration"])
        self.assertIn("当前没有未知样本", rendered["ok"]["summary"])
        self.assertIn("任务</div><div class=\"v\">0", rendered["ok"]["metrics"])
        self.assertIn("<strong>0%</strong>", rendered["ok"]["duration"])

    def test_job_cancel_wire_guard_rejects_before_mutation(self) -> None:
        with mock.patch("threading.Thread.start", return_value=None):
            record = jobs.start_job(self.workspace, "drama-plan", {"episode_no": 1})
        path = f"/api/workspace/{self.workspace}/job/{record['job_id']}/cancel"
        invalid = (
            ({"content-type": "application/x-www-form-urlencoded"}, b""),
            ({"content-type": "application/json"}, b"{}"),
            ({
                "content-type": "application/json",
                "x-drama-mutation-intent": "mutate-v1",
                "sec-fetch-site": "cross-site",
                "origin": "https://evil.example",
                "host": "127.0.0.1:8765",
            }, b"{}"),
            ({
                "content-type": "application/json",
                "x-drama-mutation-intent": "mutate-v1",
            }, b"x" * (64 * 1024 + 1)),
            ({
                "content-type": "application/json",
                "x-drama-mutation-intent": "mutate-v1",
            }, b"not-json"),
        )
        for headers, body in invalid:
            with self.subTest(headers=headers, body_length=len(body)):
                status, _ct, _payload = routes.dispatch("POST", path, body, headers)
                self.assertIn(status, {400, 403, 413, 415})
                self.assertFalse(jobs.get_job(record["job_id"])["cancel_requested"])

        status, _ct, body = routes.dispatch(
            "POST",
            path,
            b"{}",
            {
                "content-type": "application/json",
                "x-drama-mutation-intent": "mutate-v1",
                "sec-fetch-site": "same-origin",
                "origin": "http://127.0.0.1:8765",
                "host": "127.0.0.1:8765",
            },
        )
        self.assertEqual(status, 202, body.decode())

        jobs.reset_for_tests()
        with mock.patch("threading.Thread.start", return_value=None):
            trusted = jobs.start_job(self.workspace, "drama-hooks", {"episode_no": 1})
        trusted_path = f"/api/workspace/{self.workspace}/job/{trusted['job_id']}/cancel"
        status, _ct, body = routes.dispatch("POST", trusted_path)
        self.assertEqual(status, 202, body.decode())

    def test_architecture_and_wizard_cancel_contracts_are_current(self) -> None:
        self.assertIn("bounded durable public ledger", jobs.__doc__ or "")
        self.assertNotIn("No persistence", jobs.__doc__ or "")
        wizard_cancel = _slice(
            static.JS_WIZARD,
            'const res = await fetch("/api/workspace/"',
            "        const data = await res.json()",
        )
        self.assertIn('"Content-Type": "application/json"', wizard_cancel)
        self.assertIn('"X-Drama-Mutation-Intent": "mutate-v1"', wizard_cancel)
        self.assertIn("body: JSON.stringify({})", wizard_cancel)


if __name__ == "__main__":
    unittest.main()
