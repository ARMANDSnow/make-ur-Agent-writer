"""Synthetic/offline regressions for iter169; no real provider calls."""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from src import paths, start_point
from src.cli_workspace import init_workspace
from src.utils import sha256_text, write_json
from src.web import jobs, routes, static
from src.web.workspace_ctx import use_workspace


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(paths, 'WORKSPACE_DIR', Path(self.tmp.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.env = patch.dict(os.environ, {'OPENAI_MODEL': 'mock', 'WORKSPACE_NAME': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        init_workspace('synthetic', creation_mode='greenfield')
        self.root = Path(self.tmp.name) / 'synthetic'
        jobs.reset_for_tests()
        self.addCleanup(jobs.reset_for_tests)

    def test_proxy_default_preserves_every_variable_without_probe(self):
        from src.llm_client import _setup_proxy
        configured = {k: 'http://127.0.0.1:7897' for k in
                      ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy','NO_PROXY')}
        with patch.dict(os.environ, configured, clear=True), patch('socket.create_connection') as connect:
            _setup_proxy()
            self.assertEqual(dict(os.environ), configured)
            connect.assert_not_called()
        with patch.dict(os.environ, {**configured, 'DRAGON_RAJA_PROXY_MODE':'sandbox-63501'}, clear=True), patch('socket.create_connection', side_effect=OSError):
            _setup_proxy()
            for key, value in configured.items():
                self.assertEqual(os.environ[key], value)

    def test_proxy_shell_preserves_user_settings(self):
        env = {**os.environ, 'HTTP_PROXY':'http://proxy.invalid:1234', 'ALL_PROXY':'socks5://proxy.invalid:4567'}
        env.pop('DRAGON_RAJA_PROXY_MODE', None)
        result = subprocess.run(['bash','-c','source scripts/with_proxy.sh\n[[ "$HTTP_PROXY" == "http://proxy.invalid:1234" && "$ALL_PROXY" == "socks5://proxy.invalid:4567" ]]'], env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_single_steps_forward_cancellation_before_second_unit(self):
        extracted = self.root / 'data/extracted'
        extracted.mkdir(parents=True, exist_ok=True)
        (extracted / 'one.json').write_text('{}')
        write_json(self.root / 'data/chapter_manifest.json', [])
        with use_workspace('synthetic'), patch('src.web.jobs.paths.extracted_dir', return_value=extracted):
            for handler, dependency in ((jobs._step_extract, 'extract_all'), (jobs._step_compress, 'compress_all'), (jobs._step_bootstrap_all, 'bootstrap_all')):
                calls = []
                cancelled = False
                def checkpoint(*args):
                    if cancelled:
                        raise jobs.JobCancelled('test cancel')
                def batch(*args, progress_cb=None, **kwargs):
                    nonlocal cancelled
                    for i in range(2):
                        if progress_cb:
                            progress_cb(str(i), i / 2)
                        calls.append(i)
                        cancelled = True
                with self.subTest(step=dependency), patch('src.web.jobs.' + dependency, side_effect=batch):
                    with self.assertRaises(jobs.JobCancelled):
                        handler({}, checkpoint)
                    self.assertEqual(calls, [0])

    def test_real_normalize_then_web_split(self):
        from src.text_normalizer import normalize_all
        raw = self.root / '小说txt'
        raw.mkdir(exist_ok=True)
        (raw / 'synthetic.txt').write_text('Chapter 1 Test\n\nSynthetic text only.\n\nChapter 2 Next\n\nMore synthetic text.\n', encoding='utf-8')
        with use_workspace('synthetic'):
            normalize_all(lang='en')
            result = jobs._step_split({'lang':'en'}, lambda *_: None)
            self.assertNotEqual(result.get('status') if isinstance(result, dict) else None, 'blocked')
            self.assertTrue(paths.chapter_manifest_path().exists())

    def _outline(self):
        d = self.root / 'outputs/debate'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'outline.md').write_text('original outline')
        write_json(d / 'decisions.json', {'outline_sha256':sha256_text('original outline'), 'start_chapter_id':'', 'start_point_fingerprint':''})
        return d

    def test_manual_outline_hash_allows_planning(self):
        d = self._outline()
        st, _, body = routes.api_workspace_outline_save('synthetic', json.dumps({'outline':'manual\r\noutline'}).encode())
        self.assertEqual(st, 200, body)
        with use_workspace('synthetic'):
            from src.plot_planner import generate_chapter_plan
            plan = generate_chapter_plan(target_chapters=2)
            self.assertGreaterEqual(len(plan['chapters']), 2)
            decisions = json.loads((d/'decisions.json').read_text())
            self.assertEqual(decisions['manual_edit']['source'], 'web')
            self.assertEqual(start_point.outline_consistency_failures(decisions, outline_text=(d/'outline.md').read_text()), [])

    def test_manual_outline_does_not_launder_start_or_corruption(self):
        d = self._outline()
        with patch('src.start_point.get_start_chapter_id', return_value='different-start'):
            st, _, _ = routes.api_workspace_outline_save('synthetic', b'{"outline":"new"}')
        self.assertEqual(st,409)
        self.assertEqual((d/'outline.md').read_text(),'original outline')
        (d/'outline.md').write_text('unacknowledged change')
        st, _, _ = routes.api_workspace_outline_save('synthetic', b'{"outline":"new"}')
        self.assertEqual(st,409)

    def test_manual_outline_second_write_failure_is_not_success(self):
        self._outline()
        with patch('src.web.routes.workspace_files.write_json_atomic', side_effect=OSError('synthetic failure')):
            st, _, _ = routes.api_workspace_outline_save('synthetic', b'{"outline":"new"}')
        self.assertEqual(st,500)
        with use_workspace('synthetic'):
            from src.plot_planner import generate_chapter_plan, OutlineStale
            with self.assertRaises(OutlineStale): generate_chapter_plan(target_chapters=2)

    def test_actual_draft_editor_preserves_new_input_during_save(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node required for real JS regression')
        js = static.JS_DASHBOARD
        helpers = js[js.index('  function captureEditSnapshot('):js.index('  async function clickAndAwaitClean(')]
        editor = js[js.index('  function bindDraftEditor('):js.index('  function ', js.index('  function bindDraftEditor(')+12)]
        # The next function is nested, so delimit against the next page-level renderer.
        start=js.index('  function bindDraftEditor(')
        end=js.index('\n  function ',start+5)
        editor=js[start:end]
        harness = r'''
const assert=require('node:assert/strict');
function el(value='') { return {value,dataset:{},isConnected:true,disabled:false,addEventListener(){},focus(){},matches(){return true}}; }
const area=el('A'), save=el(), review=el(), status=el();
const document={getElementById(id){return {'draft-edit-area':area,'draft-save':save,'draft-save-review':review,'draft-edit-status':status}[id]}};
const showToast=()=>{}; const wsUrl=x=>x; let finish, sent, registered, chapterDetailRequest=0;
const putJson=(_url,body)=>{sent=body.content;return new Promise(r=>finish=r)};
const registerDirtyEditor=(_id,value)=>{registered=value};
(async()=>{bindDraftEditor(1);area.dataset.dirty='1';
const pending=area._saveBeforeLeave(); area.value='B'; finish({saved:true});
assert.equal(await pending,false); assert.equal(sent,'A'); assert.equal(registered.isDirty(),true);
assert.match(status.textContent,/尚未保存/);
const again=area._saveBeforeLeave(); finish({saved:true}); assert.equal(await again,true);assert.equal(sent,'B');assert.equal(registered.isDirty(),false);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result=subprocess.run([node,'-e',helpers+editor+harness],text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def _approved(self, chapter=1, text='The clue is resolved here.\n'):
        from src.plot_planner import generate_chapter_plan
        from src.writer import _load_chapter_plan, _chapter_plan_item, _run_context
        d=self.root/'outputs/drafts'; d.mkdir(parents=True,exist_ok=True)
        if not (self.root/'outputs/debate/chapter_plan.json').exists():
            self._outline(); generate_chapter_plan(target_chapters=5)
        item=_chapter_plan_item(_load_chapter_plan(),chapter)
        context=_run_context(item,chapter_no=chapter)
        meta={'verdict':'Approve','needs_human_review':False,'draft_sha256':sha256_text(text),'run_context':context}
        (d/f'chapter_{chapter:02d}.md').write_text(text)
        write_json(d/f'chapter_{chapter:02d}.meta.json',meta)
        write_json(d.parent/'reviews'/f'chapter_{chapter:02d}.review.json',meta)
        return d,meta

    def test_edit_review_refreshes_summary_and_disables_old_advances(self):
        from src import story_memory, chapter_summary
        with use_workspace('synthetic'):
            d,meta=self._approved()
            chapter_summary.append_chapter_summary(1,'OLD SUMMARY',[],'OLD END',text_snippet='OLD SNIPPET',path=d/'rolling_chapter_summary.json')
            state=chapter_summary.load_rolling_summary(d/'rolling_chapter_summary.json')
            state['compressed_older']=[{'chapter_no':1,'text':'OLD COMPACT'}]
            chapter_summary.save_rolling_summary(state,d/'rolling_chapter_summary.json')
            graph={'relationships':[{'timeline':[{'anchor_chapter':'source','state':'baseline','active':False},{'anchor_chapter':'续写第01章','state':'OLD ENTITY','active':True}]}]}
            write_json(self.root/'data/entity_graph.json',graph)
            write_json(d/'chapter_01.entity_advance_proposals.json',{'proposed_advances':[{'new_state':'OLD PROPOSAL'}]})
            st,_,body=routes.api_workspace_draft_save('synthetic',1,json.dumps({'content':'New current city is south.'}).encode())
            self.assertEqual(st,200,body)
            with self.assertRaisesRegex(ValueError,'story_memory_stale'): story_memory.require_current(d,2)
            new=json.loads((d/'chapter_01.meta.json').read_text());new.update(verdict='Approve',needs_human_review=False)
            write_json(d/'chapter_01.meta.json',new);write_json(d.parent/'reviews/chapter_01.review.json',new)
            self.assertTrue(story_memory.refresh_after_review(d,1))
            story_memory.require_current(d,2)
            rendered=chapter_summary.render_rolling_context(path=d/'rolling_chapter_summary.json')
            self.assertIn('south',rendered)
            for stale in ('OLD SUMMARY','OLD END','OLD SNIPPET','OLD COMPACT'):self.assertNotIn(stale,rendered)
            updated=json.loads((self.root/'data/entity_graph.json').read_text())
            self.assertFalse(any(x['active'] for x in updated['relationships'][0]['timeline']))
            self.assertEqual(json.loads((d/'chapter_01.entity_advance_proposals.json').read_text())['proposed_advances'],[])
            self.assertFalse(story_memory.refresh_after_review(d,1))

    def test_memory_reject_and_failed_recovery_remain_blocked(self):
        from src import story_memory
        with use_workspace('synthetic'):
            d,meta=self._approved()
            story_memory.invalidate_from(d,1)
            self.assertFalse(story_memory.refresh_after_review(d,1))
            meta.update(story_memory_invalidated=True,edited=True)
            write_json(d/'chapter_01.meta.json',meta)
            with patch('src.story_memory._write',side_effect=OSError('mock write failure')):
                with self.assertRaises(OSError): story_memory.refresh_after_review(d,1)
            with self.assertRaisesRegex(ValueError,'story_memory_stale'): story_memory.require_current(d,2)
            from src.chapter_status import chapter_status
            self.assertFalse(chapter_status(1,d,validate_context=True,require_external_review=True,expected_context=meta['run_context'])['approved'])
            self.assertTrue(story_memory.refresh_after_review(d,1))
            self.assertTrue(chapter_status(1,d,validate_context=True,require_external_review=True,expected_context=meta['run_context'])['approved'])

    def test_exact_lint_failure_archive_but_unknown_failure_preserved(self):
        from src.book_runner import _sync_meta_with_external_review
        with use_workspace('synthetic'):
            d,meta=self._approved()
            failure=d/'chapter_01.failure.json'
            for payload,cleared in (({'lint_issues':[{'severity':'error'}]},True),({'reason':'submission_unknown','lint_issues':[]},False)):
                write_json(failure,payload)
                with patch('src.linter.NovelLinter.lint',return_value=[]): _sync_meta_with_external_review(d,1)
                self.assertEqual(not failure.exists(),cleared)
            write_json(failure,{'lint_issues':[]})
            review=dict(meta,draft_sha256='different')
            write_json(d.parent/'reviews/chapter_01.review.json',review)
            with patch('src.linter.NovelLinter.lint',return_value=[]): _sync_meta_with_external_review(d,1)
            self.assertTrue(failure.exists())

    def test_foreshadowing_requires_current_review_and_matching_quote(self):
        from src import foreshadowing
        with use_workspace('synthetic'):
            d,meta=self._approved()
            write_json(paths.foreshadowing_registry_path(),{'items':[{'id':'clue','origin':'continuation','planted_chapter':1,'ttl':1,'must_resolve':True,'status':'open'}]})
            with self.assertRaises(ValueError):foreshadowing.confirm_resolution('clue',1,'not in draft',confirm=True)
            result=foreshadowing.confirm_resolution('clue',1,'clue is resolved',confirm=True)
            self.assertEqual(result['status'],'resolved')
            self.assertEqual(foreshadowing.overdue_must_resolve(20),[])
            meta.update(draft_sha256='modified',needs_human_review=True)
            write_json(d/'chapter_01.meta.json',meta)
            self.assertEqual(len(foreshadowing.overdue_must_resolve(20)),1)
            foreshadowing.configure_ttl('clue',100,confirm=True)
            self.assertEqual(foreshadowing.overdue_must_resolve(20),[])
            with self.assertRaises(ValueError):foreshadowing.configure_ttl('clue',-1,confirm=True)

    def test_append_can_preserve_far_tail(self):
        from src.plot_planner import generate_chapter_plan
        with use_workspace('synthetic'):
            self._outline();old=generate_chapter_plan(target_chapters=5)
            new=generate_chapter_plan(append_count=1,from_chapter=2,force=True,preserve_tail=True)
            self.assertEqual(new['chapters'][:2],old['chapters'][:2])
            self.assertEqual(new['chapters'][3:],old['chapters'][3:])
            self.assertEqual(len(new['chapters']),5)

    def test_two_five_chapter_segments_replan_without_losing_tail(self):
        from src.plot_planner import generate_chapter_plan
        from src.book_runner import run_write_book, check_write_readiness
        with use_workspace('synthetic'):
            self._outline();generate_chapter_plan(target_chapters=5)
            generate_chapter_plan(append_count=5,from_chapter=5,force=True)
            writes=[]
            def approved_writer(*args,**kwargs):
                no=kwargs['resume_from'];writes.append(no);self._approved(no,f'Synthetic chapter {no}.\n');return []
            with patch('src.book_runner.run_preflight',return_value={'fatal':[],'warn':[]}), patch('src.book_runner.write_chapters',side_effect=approved_writer), patch('src.book_runner.review_target'):
                first=run_write_book(chapters=5,replan_every=2,require_start_point=False,auto_advance=False)
                self.assertEqual(first['status'],'succeeded',first)
                before=json.loads(paths.chapter_plan_path().read_text())
                self.assertGreaterEqual(len(before['chapters']),10)
                second=run_write_book(chapters=5,resume_from=6,replan_every=2,require_start_point=False,auto_advance=False)
                self.assertEqual(second['status'],'succeeded',second)
                self.assertEqual(writes,list(range(1,11)))
                # Resuming approved chapters must not regenerate their plan.
                with patch('src.plot_planner.generate_chapter_plan') as planner:
                    replay=run_write_book(chapters=5,resume_from=6,replan_every=2,require_start_point=False,auto_advance=False)
                    self.assertEqual(replay['status'],'succeeded')
                    planner.assert_not_called()

    def test_missing_valid_plan_tail_readiness_is_readonly_then_runner_repairs(self):
        from src.plot_planner import generate_chapter_plan
        from src.book_runner import run_write_book,check_write_readiness
        with use_workspace('synthetic'):
            self._outline();generate_chapter_plan(target_chapters=5)
            old=generate_chapter_plan(append_count=1,from_chapter=5,force=True)
            for no in range(1,6):self._approved(no)
            with patch('src.book_runner.run_preflight',return_value={'fatal':[],'warn':[]}):
                with patch('src.plot_planner.generate_chapter_plan') as planner:
                    readiness=check_write_readiness(chapters=5,resume_from=6,replan_every=2,require_start_point=False)
                    self.assertNotEqual(readiness['status'],'blocked',readiness)
                    planner.assert_not_called()
                def approved_writer(*args,**kwargs):self._approved(kwargs['resume_from']);return []
                with patch('src.book_runner.write_chapters',side_effect=approved_writer),patch('src.book_runner.review_target'):
                    result=run_write_book(chapters=5,resume_from=6,replan_every=2,require_start_point=False,auto_advance=False)
                self.assertEqual(result['status'],'succeeded',result)
                new=json.loads(paths.chapter_plan_path().read_text())
                self.assertEqual(old['chapters'][5],new['chapters'][5])

    def test_foreshadowing_checks_before_each_chapter_not_only_batch_start(self):
        from src.plot_planner import generate_chapter_plan
        from src.book_runner import run_write_book
        with use_workspace('synthetic'):
            self._outline();generate_chapter_plan(target_chapters=5)
            write_json(paths.foreshadowing_registry_path(),{'items':[{'id':'clue','origin':'continuation','planted_chapter':0,'ttl':1,'must_resolve':True,'status':'open'}]})
            writes=[]
            def approved_writer(*args,**kwargs):
                no=kwargs['resume_from'];writes.append(no);self._approved(no);return []
            with patch('src.book_runner.run_preflight',return_value={'fatal':[],'warn':[]}),patch('src.book_runner.write_chapters',side_effect=approved_writer),patch('src.book_runner.review_target'):
                result=run_write_book(chapters=5,require_start_point=False,auto_advance=False)
            self.assertEqual(result['status'],'blocked')
            self.assertEqual(writes,[1,2])
            self.assertEqual(result['blocked'][0]['chapter'],3)

    def test_corrupt_memory_or_graph_never_clears_invalidation(self):
        from src import story_memory
        with use_workspace('synthetic'):
            d,meta=self._approved()
            (d/'chapter_01.meta.json').write_text('{broken')
            with self.assertRaises(ValueError):story_memory.require_current(d,2)
            meta.update(edited=True,story_memory_invalidated=True)
            write_json(d/'chapter_01.meta.json',meta)
            (self.root/'data/entity_graph.json').write_text('{broken')
            with self.assertRaises(ValueError):story_memory.refresh_after_review(d,1)
            self.assertTrue(json.loads((d/'chapter_01.meta.json').read_text())['story_memory_invalidated'])

    def test_lint_failure_archive_does_not_follow_history_symlink(self):
        from src.book_runner import _sync_meta_with_external_review
        with use_workspace('synthetic'),tempfile.TemporaryDirectory() as outside:
            d,meta=self._approved();failure=d/'chapter_01.failure.json'
            write_json(failure,{'lint_issues':[]})
            (d/'history').symlink_to(outside,target_is_directory=True)
            with patch('src.linter.NovelLinter.lint',return_value=[]),self.assertRaises((OSError,ValueError)):
                _sync_meta_with_external_review(d,1)
            self.assertTrue(failure.exists())
            self.assertEqual(list(Path(outside).iterdir()),[])

    def test_js_dynamic_fields_detached_editor_and_out_of_order_get(self):
        js=static.JS_DASHBOARD
        helpers=js[js.index('  function captureEditSnapshot('):js.index('  async function clickAndAwaitClean(')]
        refresh=js[js.index('  let chapterDetailRequest ='):js.index('  async function initChapterDetail(')]
        harness=r'''
const assert=require('node:assert/strict'); const showToast=()=>{};
function field(value){return {value,isConnected:true,dataset:{}}}
let fields=[field('a'),field('b')];
const root={isConnected:true,dataset:{dirty:'1'},matches(){return false},querySelectorAll(){return fields}};
let s=captureEditSnapshot(root);fields.push(field('c'));assert.equal(acknowledgeEditSnapshot(s),false);
s=captureEditSnapshot(root);fields=fields.slice(1);assert.equal(acknowledgeEditSnapshot(s),false);
s=captureEditSnapshot(root);fields.reverse();assert.equal(acknowledgeEditSnapshot(s),false);
s=captureEditSnapshot(root);fields[0]=field(fields[0].value);assert.equal(acknowledgeEditSnapshot(s),false);
s=captureEditSnapshot(root);root.isConnected=false;assert.equal(acknowledgeEditSnapshot(s),false);
root.isConnected=true;s=captureEditSnapshot(root);assert.equal(acknowledgeEditSnapshot(s),true);
const waiting=[],rendered=[];const wsUrl=x=>x;
const fetchJson=()=>new Promise(r=>waiting.push(r));const renderChapterDetail=x=>rendered.push(x);
(async()=>{const a=refreshChapterDetail(1),b=refreshChapterDetail(1);
waiting[1]('B');await b;waiting[0]('A');await a;assert.deepEqual(rendered,['B']);
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        result=subprocess.run([shutil.which('node'),'-e',helpers+refresh+harness],text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_resolution_invalid_after_review_change_plan_change_or_draft_deleted(self):
        from src import foreshadowing
        from src.plot_planner import _attach_plan_fingerprints
        with use_workspace('synthetic'):
            d,meta=self._approved()
            write_json(paths.foreshadowing_registry_path(),{'items':[{'id':'clue','origin':'continuation','planted_chapter':1,'ttl':1,'must_resolve':True,'status':'open'}]})
            foreshadowing.confirm_resolution('clue',1,'clue is resolved',confirm=True)
            review=d.parent/'reviews/chapter_01.review.json'
            write_json(review,{**meta,'verdict':'Reject'})
            self.assertEqual(len(foreshadowing.overdue_must_resolve(20)),1)
            write_json(review,meta)
            plan=json.loads(paths.chapter_plan_path().read_text());plan['chapters'][0]['title']='Changed'
            _attach_plan_fingerprints(plan,start_chapter_id='');write_json(paths.chapter_plan_path(),plan)
            self.assertEqual(len(foreshadowing.overdue_must_resolve(20)),1)
            (d/'chapter_01.md').unlink()
            self.assertEqual(len(foreshadowing.overdue_must_resolve(20)),1)

    def test_writer_relints_polished_draft_before_persisting_failure(self):
        from src.writer import write_chapters
        from src.book_runner import _sync_meta_with_external_review
        from src.chapter_status import chapter_status
        from src.plot_planner import generate_chapter_plan
        with use_workspace('synthetic'):
            self._outline();generate_chapter_plan(target_chapters=5)
            config={'max_review_attempts':1,'polish_pass':True,'review_during_lint_block':False,'continuation_anchor':''}
            issue={'rule':'test','severity':'error','message':'synthetic lint issue'}
            with patch('src.writer.load_config',return_value=config),patch('src.writer.NovelLinter.lint',side_effect=[[issue],[]]),patch('src.writer._polish_draft',return_value='Polished synthetic chapter.'),patch('src.writer._summarize_chapter',return_value={'summary':'summary','key_events':[],'ending_state':'end'}),patch('src.writer._propose_entity_advance',return_value=[]):
                write_chapters(chapters=1,force=True,max_attempts=1)
            drafts=paths.drafts_dir()
            self.assertFalse((drafts/'chapter_01.failure.json').exists())
            meta=json.loads((drafts/'chapter_01.meta.json').read_text())
            review={**meta,'verdict':'Approve','needs_human_review':False}
            write_json(drafts.parent/'reviews/chapter_01.review.json',review)
            _sync_meta_with_external_review(drafts,1)
            self.assertTrue(chapter_status(1,drafts,validate_context=True,require_external_review=True,expected_context=meta['run_context'])['approved'])

    def test_plan_tail_repair_on_global_boundary_calls_planner_once(self):
        from src.plot_planner import generate_chapter_plan
        from src.book_runner import run_write_book
        with use_workspace('synthetic'):
            self._outline();generate_chapter_plan(target_chapters=5)
            generate_chapter_plan(append_count=1,from_chapter=5,force=True)
            for no in range(1,7):self._approved(no)
            def approved_writer(*args,**kwargs):self._approved(kwargs['resume_from']);return []
            with patch('src.book_runner.run_preflight',return_value={'fatal':[],'warn':[]}),patch('src.book_runner.write_chapters',side_effect=approved_writer),patch('src.book_runner.review_target'),patch('src.plot_planner.generate_chapter_plan',wraps=generate_chapter_plan) as planner:
                result=run_write_book(chapters=2,resume_from=7,replan_every=2,require_start_point=False,auto_advance=False)
                self.assertEqual(result['status'],'succeeded',result)
                self.assertEqual(planner.call_count,1)
