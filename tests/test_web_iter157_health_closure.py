from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("OPENAI_MODEL", "mock")
os.environ.setdefault("DRAGON_RAJA_SKIP_DOTENV", "1")

from src import paths, workspace_files
from src.web import jobs, routes, safe_log, server, static, wizard, workspace_meta


_SECRET = (
    "sk-SYNTHETICKEY0123456789 prompt=copyright-marker "
    "https://example.invalid/file?signature=secret /private/absolute/path"
)


class _WorkspaceFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.saved_workspace_dir = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = self.root / "workspaces"
        paths.WORKSPACE_DIR.mkdir()
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        paths.WORKSPACE_DIR = self.saved_workspace_dir
        self.tempdir.cleanup()

    def workspace(self, name: str) -> Path:
        root = paths.WORKSPACE_DIR / name
        root.mkdir()
        return root


class WorkspaceFileBoundaryTests(_WorkspaceFixture):
    def test_normal_and_partially_initialized_draft_surfaces(self) -> None:
        root = self.workspace("partial")
        drafts = root / "outputs/drafts"
        drafts.mkdir(parents=True)
        (drafts / "chapter_01.md").write_text("# 第一章\n\n正文。\n", encoding="utf-8")

        status, _ct, body = routes.api_workspace_drafts("partial")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["drafts"][0]["chapter"], 1)
        status, _ct, body = routes.api_workspace_draft("partial", "1")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["meta"], {})

        status, _ct, body = routes.api_workspace_draft_save(
            "partial", "1", json.dumps({"content": "# 第一章\n\n修改。", "expected_sha256": json.loads(body)["draft_sha256"]}).encode()
        )
        self.assertEqual(status, 200, body)
        self.assertTrue((drafts / "chapter_01.meta.json").is_file())
        meta_path = drafts / "chapter_01.meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["snapshot_path"] = str(self.root / "outside-secret-marker")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        status, _ct, body = routes.api_workspace_draft("partial", "1")
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)["meta"]["snapshot_path"])
        self.assertNotIn("outside-secret-marker", body.decode())

        bare = self.workspace("barekb")
        status, _ct, body = routes.api_workspace_kb_save(
            "barekb", json.dumps({"content": "人物：测试"}, ensure_ascii=False).encode()
        )
        self.assertEqual(status, 200, body)
        status, _ct, body = routes.api_workspace_kb_get("barekb")
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["content"], "人物：测试")
        self.assertTrue((bare / "data/knowledge_base/global_knowledge.md").is_file())

    def test_multibyte_content_preserves_existing_character_limits(self) -> None:
        root = self.workspace("multibyte")
        drafts = root / "outputs/drafts"
        drafts.mkdir(parents=True)
        (drafts / "chapter_01.md").write_text("original\n", encoding="utf-8")
        kb_content = "😀" * 500_000
        status, _ct, body = routes.api_workspace_kb_save(
            "multibyte",
            json.dumps({"content": kb_content}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body)
        draft_content = "😀" * 1_000_000
        status, _ct, body = routes.api_workspace_draft_save(
            "multibyte",
            "1",
            json.dumps({"content": draft_content, "expected_sha256": __import__("hashlib").sha256(b"original\n").hexdigest()}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(
            (drafts / "chapter_01.md").stat().st_size,
            4_000_001,
        )

    def test_kb_ancestor_and_final_symlinks_fail_closed(self) -> None:
        outside = self.root / "outside.md"
        outside.write_text("outside-original", encoding="utf-8")

        ancestor = self.workspace("ancestor")
        (ancestor / "data").mkdir()
        external_dir = self.root / "external-kb"
        external_dir.mkdir()
        (external_dir / "global_knowledge.md").write_text("external", encoding="utf-8")
        (ancestor / "data/knowledge_base").symlink_to(external_dir, target_is_directory=True)
        status, _ct, body = routes.api_workspace_kb_get("ancestor")
        self.assertEqual(status, 409, body)
        status, _ct, body = routes.api_workspace_kb_save(
            "ancestor", json.dumps({"content": "replacement"}).encode()
        )
        self.assertEqual(status, 500, body)
        self.assertEqual(
            (external_dir / "global_knowledge.md").read_text(encoding="utf-8"), "external"
        )

        final = self.workspace("final")
        (final / "data/knowledge_base").mkdir(parents=True)
        (final / "data/knowledge_base/global_knowledge.md").symlink_to(outside)
        status, _ct, body = routes.api_workspace_kb_get("final")
        self.assertEqual(status, 409, body)
        status, _ct, body = routes.api_workspace_kb_save(
            "final", json.dumps({"content": "replacement"}).encode()
        )
        self.assertEqual(status, 500, body)
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside-original")

    def test_draft_symlink_fifo_and_oversize_are_rejected(self) -> None:
        outside = self.root / "outside-draft.md"
        outside.write_text("outside-original", encoding="utf-8")

        ancestor = self.workspace("draftancestor")
        (ancestor / "outputs").mkdir()
        external_drafts = self.root / "external-drafts"
        external_drafts.mkdir()
        (external_drafts / "chapter_01.md").write_text("external", encoding="utf-8")
        (ancestor / "outputs/drafts").symlink_to(external_drafts, target_is_directory=True)
        status, _ct, body = routes.api_workspace_drafts("draftancestor")
        self.assertEqual(status, 409, body)
        status, _ct, body = routes.api_workspace_draft_save(
            "draftancestor", "1", json.dumps({"content": "replacement"}).encode()
        )
        self.assertEqual(status, 409, body)
        self.assertEqual(
            (external_drafts / "chapter_01.md").read_text(encoding="utf-8"), "external"
        )

        linked = self.workspace("linked")
        linked_drafts = linked / "outputs/drafts"
        linked_drafts.mkdir(parents=True)
        (linked_drafts / "chapter_01.md").symlink_to(outside)
        status, _ct, body = routes.api_workspace_drafts("linked")
        self.assertEqual(status, 409, body)
        status, _ct, body = routes.api_workspace_draft_save(
            "linked", "1", json.dumps({"content": "replacement"}).encode()
        )
        self.assertEqual(status, 409, body)
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside-original")

        special = self.workspace("special")
        special_drafts = special / "outputs/drafts"
        special_drafts.mkdir(parents=True)
        os.mkfifo(special_drafts / "chapter_01.md")
        status, _ct, body = routes.api_workspace_drafts("special")
        self.assertEqual(status, 409, body)

        large = self.workspace("large")
        large_drafts = large / "outputs/drafts"
        large_drafts.mkdir(parents=True)
        with (large_drafts / "chapter_01.md").open("wb") as handle:
            handle.truncate(4_000_002)
        status, _ct, body = routes.api_workspace_draft("large", "1")
        self.assertEqual(status, 409)

    def test_atomic_failure_preserves_target_and_cleans_temp(self) -> None:
        root = self.workspace("atomic")
        target = root / "data/knowledge_base/global_knowledge.md"
        target.parent.mkdir(parents=True)
        target.write_text("original", encoding="utf-8")
        with mock.patch.object(workspace_files.os, "fsync", side_effect=OSError(_SECRET)):
            with self.assertRaises(workspace_files.WorkspaceFileError):
                workspace_files.write_text_atomic(
                    "atomic",
                    "data/knowledge_base/global_knowledge.md",
                    "replacement",
                    max_bytes=100,
                )
        self.assertEqual(target.read_text(encoding="utf-8"), "original")
        self.assertEqual([p.name for p in target.parent.iterdir()], [target.name])


class SafeExceptionProjectionTests(_WorkspaceFixture):
    @staticmethod
    def _upload_body(workspace: str) -> tuple[bytes, str]:
        boundary = "----ITER157"
        text = ("第一章 起点\n离线测试正文。\n" * 4).encode("utf-8")
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="workspace"\r\n\r\n{workspace}\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="upload"; filename="book.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
        ).encode("utf-8") + text + f"\r\n--{boundary}--\r\n".encode("utf-8")
        return body, f"multipart/form-data; boundary={boundary}"

    def test_safe_logger_never_emits_exception_message_or_frames(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            try:
                raise RuntimeError(_SECRET)
            except RuntimeError as exc:
                trace_id = safe_log.log_exception("test.synthetic", exc)
        output = stderr.getvalue()
        self.assertNotIn(_SECRET, output)
        self.assertNotIn("Traceback", output)
        self.assertRegex(output, rf"event=test\.synthetic .*trace_id={trace_id}")

    def test_route_and_server_catchalls_use_safe_recorder(self) -> None:
        def explode(**_kwargs: object) -> object:
            raise RuntimeError(_SECRET)

        route = ("GET", re.compile(r"^/__iter157_explode$"), explode)
        routes._ROUTES.insert(0, route)
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                status, _ct, body = routes.dispatch("GET", "/__iter157_explode")
        finally:
            routes._ROUTES.remove(route)
        self.assertEqual(status, 500)
        self.assertRegex(json.loads(body)["trace_id"], r"^[a-f0-9]{32}$")
        self.assertNotIn(_SECRET, body.decode())
        self.assertNotIn(_SECRET, stderr.getvalue())

        handler = object.__new__(server.WebHandler)
        handler.headers = {}
        handler.wfile = io.BytesIO()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), mock.patch.object(
            routes, "dispatch", side_effect=RuntimeError(_SECRET)
        ):
            handler._respond_inner("GET", "/")
        projected = json.loads(handler.wfile.getvalue())
        self.assertRegex(projected["trace_id"], r"^[a-f0-9]{32}$")
        self.assertNotIn(_SECRET, handler.wfile.getvalue().decode())
        self.assertNotIn(_SECRET, stderr.getvalue())



    def test_draft_meta_failure_body_and_stderr_are_redacted(self) -> None:
        root = self.workspace("meta")
        drafts = root / "outputs/drafts"
        drafts.mkdir(parents=True)
        (drafts / "chapter_01.md").write_text("original\n", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), mock.patch.object(
            workspace_files, "write_json_atomic", side_effect=OSError(_SECRET)
        ):
            status, _ct, body = routes.api_workspace_draft_save(
                "meta", "1", json.dumps({"content": "replacement", "expected_sha256": __import__("hashlib").sha256(b"original\n").hexdigest()}).encode()
            )
        self.assertEqual(status, 500)
        self.assertNotIn(_SECRET, body.decode())
        self.assertNotIn(_SECRET, stderr.getvalue())


class JobPersistenceAdmissionTests(_WorkspaceFixture):
    def _job_workspace(self, name: str) -> Path:
        root = self.workspace(name)
        (root / "logs").mkdir()
        return root

    def _assert_start_rejected_without_worker(self, workspace: str) -> None:
        with mock.patch.object(jobs.threading, "Thread") as thread_type:
            with self.assertRaisesRegex(jobs.JobPersistenceError, "job_persistence_failed"):
                jobs.start_job(workspace, "normalize", {})
        thread_type.assert_not_called()
        self.assertNotIn(workspace, jobs._WORKSPACE_JOBS)
        self.assertFalse(jobs._JOBS)
        self.assertFalse(jobs._WORKER_THREADS)

    def test_unsafe_or_full_log_rejects_initial_job(self) -> None:
        external = self.root / "external-log"
        external.write_bytes(b"outside-original")
        linked = self._job_workspace("linked")
        (linked / "logs/web_jobs.jsonl").symlink_to(external)
        self._assert_start_rejected_without_worker("linked")
        self.assertEqual(external.read_bytes(), b"outside-original")

        fifo = self._job_workspace("fifo")
        os.mkfifo(fifo / "logs/web_jobs.jsonl")
        self._assert_start_rejected_without_worker("fifo")

        full = self._job_workspace("full")
        with (full / "logs/web_jobs.jsonl").open("wb") as handle:
            handle.truncate(jobs._MAX_JOB_LOG_BYTES)
        self._assert_start_rejected_without_worker("full")

    def test_short_write_and_fsync_failure_restore_original_length(self) -> None:
        for name, failure in (("short", "write"), ("sync", "fsync")):
            root = self._job_workspace(name)
            log = root / "logs/web_jobs.jsonl"
            log.write_bytes(b"old-row\n")
            original_write = os.write

            if failure == "write":
                def short_write(fd: int, payload: bytes) -> int:
                    return original_write(fd, payload[:7])

                patcher = mock.patch.object(jobs.os, "write", side_effect=short_write)
            else:
                patcher = mock.patch.object(jobs.os, "fsync", side_effect=OSError(_SECRET))
            with patcher:
                self._assert_start_rejected_without_worker(name)
            self.assertEqual(log.read_bytes(), b"old-row\n")

    def test_later_failure_sets_public_degraded_projection_only(self) -> None:
        record = jobs._new_job_record("manual", "normalize", {})
        with jobs._JOBS_LOCK:
            jobs._JOBS[record["job_id"]] = record
        with mock.patch.object(jobs, "_persist_job", return_value=False):
            jobs._update(record["job_id"], status="running")
        snapshot = jobs.get_job(record["job_id"])
        self.assertTrue(snapshot["persistence_degraded"])
        self.assertTrue(jobs.public_job_summary_view(snapshot)["persistence_degraded"])
        self.assertTrue(jobs.public_job_detail_view(snapshot)["persistence_degraded"])
        self.assertNotIn("persistence_degraded", jobs.public_job_view(snapshot))


class FrontendPollingContractTests(unittest.TestCase):
    @staticmethod
    def _extract_function(source: str, name: str) -> str:
        start = source.index(f"function {name}(")
        async_start = source.rfind("async ", 0, start)
        if async_start >= 0 and source[async_start:start].strip() == "async":
            start = async_start
        brace = source.index("{", start)
        depth = 0
        quote = ""
        escaped = False
        line_comment = False
        block_comment = False
        index = brace
        while index < len(source):
            char = source[index]
            nxt = source[index + 1] if index + 1 < len(source) else ""
            if line_comment:
                if char == "\n":
                    line_comment = False
            elif block_comment:
                if char == "*" and nxt == "/":
                    block_comment = False
                    index += 1
            elif quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = ""
            elif char in {"'", '"', "`"}:
                quote = char
            elif char == "/" and nxt == "/":
                line_comment = True
                index += 1
            elif char == "/" and nxt == "*":
                block_comment = True
                index += 1
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return source[start : index + 1]
            index += 1
        raise AssertionError(f"unterminated JS function: {name}")

    def test_changed_bundles_pass_node_syntax_check(self) -> None:
        for source in (static.JS_DASHBOARD, static.JS_WIZARD):
            result = subprocess.run(
                ["node", "--check"],
                input=source,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_node_status_matrix_and_stop_contract(self) -> None:
        functions = []
        for source, name in (
            (static.JS_DASHBOARD, "jobPollDisposition"),
            (static.JS_WIZARD, "wizardJobPollDisposition"),
        ):
            match = re.search(
                rf"function {name}\(status\) \{{.*?\n  \}}",
                source,
                flags=re.DOTALL,
            )
            self.assertIsNotNone(match, name)
            functions.append(match.group(0))
        script = "\n".join(functions) + """
const statuses = [undefined, null, '', 'queued-new', 'pending', 'running',
  'succeeded', 'blocked', 'failed', 'aborted', 'lost', 'budget_exceeded'];
const expected = ['invalid','invalid','invalid','invalid','active','active',
  'terminal','terminal','terminal','terminal','terminal','terminal'];
for (const fn of [jobPollDisposition, wizardJobPollDisposition]) {
  const actual = statuses.map(fn);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) process.exit(3);
}
"""
        result = subprocess.run(
            ["node", "-e", script], text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('if (disposition === "invalid")', static.JS_DASHBOARD)
        self.assertIn("setControlBusy(submit, false);", static.JS_DASHBOARD)
        self.assertIn("!res.ok || !job || typeof job !== \"object\"", static.JS_WIZARD)
        self.assertIn("wizardSetFormBusy(novelForm, false);", static.JS_WIZARD)
        self.assertIn("已停止自动刷新", static.JS_DASHBOARD)
        self.assertIn("已停止自动刷新", static.JS_WIZARD)

    def test_node_dom_mock_invalid_polling_stops_after_one_request(self) -> None:
        dashboard = "\n".join(
            self._extract_function(static.JS_DASHBOARD, name)
            for name in ("pollJob", "jobPollDisposition", "renderJobReconcile")
        )
        wizard_source = "\n".join(
            self._extract_function(static.JS_WIZARD, name)
            for name in ("poll", "wizardJobPollDisposition", "renderWizardReconcile")
        )
        script = dashboard + "\n" + wizard_source + r"""
let mode = '';
let fetchCount = 0;
let timerCount = 0;
let busyReleased = false;
const box = {innerHTML: ''};
const submit = {disabled: true};
const progressBody = {innerHTML: ''};
const novelForm = {};
function ensureJobCancelDelegate() {}
function updateWorkbenchActiveJob() {}
function wsUrl(value) { return value; }
function wsHref(value) { return '/w/test' + value; }
function setControlBusy(control, busy) { control.disabled = busy; busyReleased = !busy; }
function wizardSetFormBusy(_form, busy) { busyReleased = !busy; }
function renderProgress() { throw new Error('invalid state rendered as progress'); }
function fetchJson() {
  fetchCount += 1;
  if (mode === '404' || mode === 'bad-json') return Promise.reject(new Error(mode));
  if (mode === 'empty') return Promise.resolve({});
  return Promise.resolve({status: 'queued-new'});
}
function fetch() {
  fetchCount += 1;
  if (mode === '404') return Promise.resolve({ok: false, json: () => Promise.resolve({})});
  if (mode === 'bad-json') return Promise.resolve({ok: true, json: () => Promise.reject(new Error('bad'))});
  if (mode === 'empty') return Promise.resolve({ok: true, json: () => Promise.resolve({})});
  return Promise.resolve({ok: true, json: () => Promise.resolve({status: 'queued-new'})});
}
function setTimeout() { timerCount += 1; throw new Error('timer scheduled'); }
(async () => {
  for (const current of ['404', 'bad-json', 'empty', 'unknown']) {
    mode = current; fetchCount = 0; timerCount = 0; busyReleased = false; box.innerHTML = '';
    await pollJob('id', box, submit);
    if (fetchCount !== 1 || timerCount !== 0 || !busyReleased || !box.innerHTML.includes('/jobs')) process.exit(11);
    mode = current; fetchCount = 0; timerCount = 0; busyReleased = false; progressBody.innerHTML = '';
    await poll('test', 'id');
    if (fetchCount !== 1 || timerCount !== 0 || !busyReleased || !progressBody.innerHTML.includes('/jobs')) process.exit(12);
  }
})().catch((error) => { process.stderr.write(String(error)); process.exit(13); });
"""
        result = subprocess.run(
            ["node", "-e", script], text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_workbench_job_updates_and_terminal_cancel_controls(self) -> None:
        functions = "\n".join(self._extract_function(static.JS_DASHBOARD, name)
                              for name in ("pollJob", "jobPollDisposition", "renderJobReconcile", "updateWorkbenchActiveJob", "setControlBusy", "setWorkbenchMutationLock", "renderWorkbenchHydration"))
        script = functions + r"""
const note = {dataset:{jobId:'current'},innerHTML:''};
const progress = {textContent:''};
const cancel = {disabled:false, addEventListener(){}};
const box = {innerHTML:''};
const submit = {dataset:{}, disabled:false, textContent:"submit", attrs:{}, getAttribute(k){return this.attrs[k];}, setAttribute(k,v){this.attrs[k]=v;}, removeAttribute(k){delete this.attrs[k];}};
const document = {querySelector:() => note, querySelectorAll:() => [submit], getElementById:(id) => id === 'workbench-active-progress' ? progress : cancel};
let lock = false, hydration = '', queue = [], calls = 0, snapshots = [];
let lastWorkbenchStatus = {};
function refreshWorkbench() {}
function ensureJobCancelDelegate() {}
function wsUrl(s) { return s; }
function wsHref(s) { return s; }
function statusLabel(s) { return s; }
function statusBadge(s) { return s; }
function escapeHtml(s) { return String(s); }
function currentStepLabel(s) { return s || ''; }
function stepLabel(s) { return s || ''; }
function showToast() {}
function renderJobFailureCard() { return ''; }
function jobBlockedDetail() { return null; }
const CTA_ACTIONS = {};
function fetchJson() { calls++; const value=queue.shift(); return value instanceof Error ? Promise.reject(value) : Promise.resolve(value); }
function setTimeout(cb) { snapshots.push({html:box.innerHTML, progress:progress.textContent}); cb(); }
(async () => {
  updateWorkbenchActiveJob('old', {job_id:'old',status:'failed'});
  if (cancel.disabled || note.innerHTML || progress.textContent) throw Error('old job overwrote current');
  queue = [{job_id:'current',status:'pending',progress:0}, {job_id:'current',status:'running',progress:.1}, {job_id:'current',status:'succeeded',progress:1}];
  await pollJob('current',box,submit,null);
  if (calls!==3 || snapshots[1].progress!=='running · 10%' || !snapshots[1].html.includes('data-cancel-job')) throw Error('active status failed');
  if (box.innerHTML.includes('data-cancel-job') || !cancel.disabled) throw Error('terminal cancel still active');
  for (const status of ['succeeded','failed','aborted','lost','blocked','budget_exceeded']) {
    queue=[{job_id:'current',status:status,cancel_requested:true}];
    await pollJob('current',box,submit);
    if (box.innerHTML.includes('data-cancel-job') || box.innerHTML.includes('已请求取消')) throw Error('terminal cancel copy leaked');
  }
  note.dataset.jobId='current'; cancel.disabled=false;
  updateWorkbenchActiveJob('current',{job_id:'current',status:'running',cancel_requested:true});
  if (!cancel.disabled) throw Error('pending cancellation enabled');
  note.dataset.jobId='current'; lock=false;
  submit.disabled=false; setControlBusy(submit,true);
  queue=[new Error('offline')];
  await pollJob('current',box,submit,null);
  setControlBusy(submit,false); // outer form finally must not undo unknown-state lock
  if (!submit.disabled || !note.innerHTML.includes('状态读取失败') || lastWorkbenchStatus!==null) throw Error('failed fetch kept active controls');
})().catch((err)=>{process.stderr.write(String(err));process.exit(1);});
"""
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_recovered_job_late_response_cannot_replace_new_job(self) -> None:
        functions = self._extract_function(static.JS_DASHBOARD, "watchRecoveredWorkbenchJob")
        script = functions + r"""
let recoveredWorkbenchJobId='', events=[], resolver, rejecter;
const note={dataset:{jobId:'A'}};
const document={querySelector:()=>note};
function setTimeout(cb){cb();}
function wsUrl(s){return s;}
function fetchJson(){return new Promise((resolve,reject)=>{resolver=resolve;rejecter=reject;});}
function renderWorkbenchHydration(kind){events.push(kind);}
function updateWorkbenchActiveJob(){events.push('updated');}
function setWorkbenchMutationLock(){events.push('locked');}
async function refreshWorkbench(){events.push('refreshed');}
(async()=>{
  for(const failed of [false,true]) {
    recoveredWorkbenchJobId='';note.dataset.jobId='A';events=[];
    const old=watchRecoveredWorkbenchJob({job_id:'A'});
    await Promise.resolve();
    recoveredWorkbenchJobId='B';note.dataset.jobId='B';
    if(failed) rejecter(new Error('old failure'));
    else resolver({job_id:'A',status:'succeeded'});
    await old;
    if(recoveredWorkbenchJobId!=='B'||events.length)throw Error('stale response changed new job');
  }
})().catch((err)=>{process.stderr.write(String(err));process.exit(1);});
"""
        result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_paid_save_review_busy_regression(self) -> None:
        self.assertIn('setControlBusy(saveReviewBtn, true, "正在保存")', static.JS_DASHBOARD)
        self.assertIn("setControlBusy(saveReviewBtn, false)", static.JS_DASHBOARD)


if __name__ == "__main__":
    unittest.main()
