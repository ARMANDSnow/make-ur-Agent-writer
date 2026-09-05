"""Regression evidence for the iter170 audit. Synthetic data, zero providers."""
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from src import paths, llm_client, story_memory
from src.chapter_splitter import candidate_headings, split_file
from src.cli_workspace import init_workspace
from src.web import jobs, routes
from src.web.workspace_ctx import use_workspace


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = patch.object(paths, 'WORKSPACE_DIR', self.root)
        p.start(); self.addCleanup(p.stop)
        p = patch.dict(os.environ, {'WORKSPACE_NAME':'','BOOK':'','OPENAI_MODEL':'mock'})
        p.start(); self.addCleanup(p.stop)
        init_workspace('audit', creation_mode='greenfield')
        self.ws = self.root/'audit'
        jobs.reset_for_tests(); self.addCleanup(jobs.reset_for_tests)

    def test_repeated_volume_headings_and_epilogues_survive(self):
        lines=['第一章', '正文'*100, '尾声', '结束'*100, '第一章', '后文'*100, '尾声', '结束'*100]
        self.assertEqual([n for n,_ in candidate_headings(lines,'upload')],[1,3,5,7])

    def test_toc_bilingual_titles_do_not_swallow_bare_body_or_prior_ending(self):
        lines=['尾声','前卷结束'*100,'目录','楔子 Title','第一章 One','第二章 Two','第三章 Three',
               '楔子','正文'*100,'第一章','正文'*100,'第二章','正文'*100]
        p=self.root/'upload.txt';p.write_text('\n'.join(lines))
        entries=split_file(p,lang='zh')
        self.assertEqual([e.title for e in entries],['尾声','楔子','第一章','第二章'])
        self.assertEqual(entries[0].end_line,2)

    def test_unlisted_prologue_and_short_body_are_preserved(self):
        lines=['目录','第一章 出发','第二章 途中','第三章 抵达','序章','正文'*100,
               '第一章 出发','正文'*100,'第二章 途中','正文'*100]
        self.assertIn((5,'序章'), candidate_headings(lines,'upload'))
        short=['目录','第一章','短文甲','第二章','短文乙','第三章','短文丙']
        self.assertEqual(len(candidate_headings(short,'upload')),3)

    def test_five_short_chapters_without_toc_are_not_deleted(self):
        lines=sum(([f'第{i}章','文字'] for i in range(1,6)),[])
        self.assertEqual(len(candidate_headings(lines,'upload')),5)

    def test_save_requires_current_version_and_rejects_stale_tab(self):
        d=self.ws/'outputs/drafts';d.mkdir()
        (d/'chapter_01.md').write_text('original\n')
        _,_,body=routes.api_workspace_draft('audit','1')
        version=json.loads(body)['draft_sha256']
        self.assertEqual(routes.api_workspace_draft_save('audit','1',b'{"content":"blind"}')[0],428)
        payload=lambda text:json.dumps({'content':text,'expected_sha256':version}).encode()
        self.assertEqual(routes.api_workspace_draft_save('audit','1',payload('A'))[0],200)
        self.assertEqual(routes.api_workspace_draft_save('audit','1',payload('B'))[0],409)
        self.assertEqual((d/'chapter_01.md').read_text(),'A\n')

    def _job(self, jid='a'*32, status='running'):
        return {'job_id':jid,'workspace':'audit','step':'write-book','status':status,
                'params':{'resume_from':1,'chapters':1},'current_step':status}

    def test_cancel_and_terminal_are_persisted_in_transition_order(self):
        jid='a'*32; jobs._JOBS[jid]=self._job()
        entered=threading.Event(); release=threading.Event(); order=[]
        def persist(row):
            if row['status']=='running': entered.set(); release.wait(2)
            order.append(row['status']);return True
        with patch.object(jobs,'_persist_job',side_effect=persist):
            cancel=threading.Thread(target=lambda:jobs.request_cancel(jid))
            cancel.start();self.assertTrue(entered.wait(2))
            finish=threading.Thread(target=lambda:jobs._complete_job(jid,'succeeded','write-book',{'committed':True}))
            finish.start();release.set();cancel.join(3);finish.join(3)
            self.assertFalse(cancel.is_alive() or finish.is_alive())
        self.assertEqual(order,['running','succeeded'])

    def test_compaction_preserves_claim_unknown_and_creation_order(self):
        jid='a'*32; own='b'*32
        with patch.object(jobs,'_MAX_JOB_LOG_ROWS',4):
            for progress in range(4):
                self.assertTrue(jobs._persist_job({**self._job(jid,'blocked'),'progress':progress/4}))
            claim=jobs.write_recovery_job_claim('audit',1)[2]
            self.assertTrue(jobs._persist_job(self._job(own)))
            self.assertEqual(jobs.write_recovery_job_claim('audit',1,exclude_job_id=own)[2],claim)
            self.assertEqual(len(jobs._read_job_rows('audit')),2)
            self.assertEqual(jobs.latest_write_job_for_chapter('audit',1)['job_id'],own)
            self.assertEqual(jobs.latest_write_job_for_chapter('audit',1)['status'],'lost')
            old_claim=jobs.write_recovery_job_claim('audit',1)[2]
            self.assertTrue(jobs._persist_job(self._job(own,'blocked')))
            self.assertTrue(jobs._persist_job(self._job(own)))
            self.assertNotEqual(jobs.write_recovery_job_claim('audit',1)[2],old_claim)

    def test_old_over_row_limit_ledger_can_compact(self):
        log=self.ws/'logs/web_jobs.jsonl'
        log.write_text((json.dumps(self._job())+'\n')*5010)
        self.assertTrue(jobs._persist_job(self._job(status='blocked')))
        self.assertEqual(len(jobs._read_job_rows('audit')),1)

    def test_reader_rejects_replaced_inode(self):
        self.assertTrue(jobs._persist_job(self._job()))
        log=self.ws/'logs/web_jobs.jsonl'
        original_read=jobs.os.read
        replaced=False
        def swap(fd, count):
            nonlocal replaced
            value=original_read(fd,count)
            if value and not replaced:
                replacement=log.with_suffix('.replacement')
                replacement.write_text(json.dumps(self._job('c'*32))+'\n')
                os.replace(replacement,log);replaced=True
            return value
        with patch.object(jobs.os,'read',side_effect=swap):
            self.assertEqual(jobs._read_job_rows_for_recovery('audit')[0],'indeterminate')

    def test_unscoped_cli_usage_failure_stops_next_request(self):
        token=llm_client._LLM_ACCOUNTING_DEGRADED.set(None)
        self.addCleanup(llm_client._LLM_ACCOUNTING_DEGRADED.reset,token)
        client=object.__new__(llm_client.LLMClient);client.task='write';client.model='openai/gpt-5.5-low'
        with patch.object(client,'_count_tokens',return_value=(1,'mock')),patch.object(llm_client,'append_jsonl'):
            client._try_log_call('complete_text','ok',time.monotonic(),response_text='accepted',response={})
        with self.assertRaises(llm_client.LLMAccountingUnavailable):
            llm_client._claim_model_request(client.model,reserved_cost_cny=1)

    def test_compaction_failure_preserves_previous_ledger(self):
        with patch.object(jobs,'_MAX_JOB_LOG_ROWS',1):
            self.assertTrue(jobs._persist_job(self._job()))
            log=self.ws/'logs/web_jobs.jsonl';old=log.read_bytes()
            with patch.object(jobs.os,'replace',side_effect=OSError):
                self.assertFalse(jobs._persist_job(self._job(status='blocked')))
            self.assertEqual(log.read_bytes(),old)

    def test_missing_or_bad_usage_blocks_next_claim_without_losing_response(self):
        client=object.__new__(llm_client.LLMClient);client.task='write';client.model='openai/gpt-5.5-low'
        for usage in (None,{}, {'prompt_tokens':1}, {'prompt_tokens':True,'completion_tokens':2}, {'prompt_tokens':-1,'completion_tokens':2}):
            with self.subTest(usage=usage), llm_client.llm_budget_limit_scope(10,lambda:0,required=True), patch.object(client,'_count_tokens',return_value=(1,'mock')),patch.object(llm_client,'append_jsonl'):
                client._try_log_call('complete_text','ok',time.monotonic(),response_text='accepted',response={'usage':usage})
                self.assertTrue(llm_client.llm_accounting_degraded())
                with self.assertRaises(llm_client.LLMAccountingUnavailable):llm_client._claim_model_request(client.model,reserved_cost_cny=1)

    def test_unscoped_bad_usage_and_sink_failure_are_total(self):
        class BadUsage:
            def model_dump(self): raise RuntimeError('synthetic conversion failure')
        client=object.__new__(llm_client.LLMClient);client.task='write';client.model='openai/gpt-5.5-low'
        for response, failure in [({'usage':BadUsage()},None), ({'usage':{'prompt_tokens':1,'completion_tokens':2}},OSError('synthetic sink failure'))]:
            token=llm_client._LLM_ACCOUNTING_DEGRADED.set(None)
            try:
                with patch.object(client,'_count_tokens',return_value=(1,'mock')),patch.object(llm_client,'append_jsonl',side_effect=failure):
                    client._try_log_call('complete_text','ok',time.monotonic(),response_text='accepted',response=response)
                with self.assertRaises(llm_client.LLMAccountingUnavailable):llm_client._claim_model_request(client.model,reserved_cost_cny=1)
            finally: llm_client._LLM_ACCOUNTING_DEGRADED.reset(token)

    def test_legacy_force_prompt_excludes_current_and_future_memory(self):
        from contextlib import ExitStack
        from tests.test_writer_progress import _write_fixture, _agent_config
        from src.writer import write_chapters
        from src.chapter_summary import append_chapter_summary
        d,outline,kb,index=_write_fixture(self.root/'writer-fixture')
        for number in (1,2,3):
            append_chapter_summary(number,f'SENTINEL{number}',[],f'ENDING{number}',path=d/'rolling_chapter_summary.json')
            (d/f'chapter_{number:02d}.meta.json').write_text('{}')
        (d/'chapter_02.md').write_text('old chapter')
        captured=[]
        def complete(*args,**kwargs):
            captured.append(str(args)+str(kwargs))
            return '干净正文'
        with ExitStack() as stack:
            for name,value in [('DRAFTS_DIR',d),('OUTLINE_PATH',outline),('KB_PATH',kb),('INDEX_PATH',index)]:
                stack.enter_context(patch('src.writer.'+name,value))
            stack.enter_context(patch('src.writer.load_config',return_value=_agent_config()))
            linter=stack.enter_context(patch('src.writer.NovelLinter'))
            linter.return_value.lint.return_value=[]
            stack.enter_context(patch('src.writer.review_text',return_value={'verdict':'Approve','lint_issues':[],'agent_reviews':[]}))
            stack.enter_context(patch('src.writer._complete_write_text',side_effect=complete))
            stack.enter_context(patch('src.writer._summarize_chapter',return_value={'summary':'new','key_events':[],'ending_state':'new'}))
            stack.enter_context(patch('src.writer._propose_entity_advance',return_value=[]))
            write_chapters(chapters=1,resume_from=2,force=True,max_attempts=1)
            self.assertIn('SENTINEL1',captured[0])
            for old in ('SENTINEL2','SENTINEL3','ENDING2','ENDING3'): self.assertNotIn(old,captured[0])
            self.assertTrue(json.loads((d/'chapter_03.meta.json').read_text())['story_memory_invalidated'])
            snapshot={p.name:p.read_bytes() for p in d.iterdir() if p.is_file()}
            captured.clear()
            write_chapters(chapters=1,resume_from=2,force=False,max_attempts=1)
            self.assertFalse(captured)
            self.assertEqual({p.name:p.read_bytes() for p in d.iterdir() if p.is_file()},snapshot)

    def test_valid_usage_allows_next_claim(self):
        client=object.__new__(llm_client.LLMClient);client.task='write';client.model='openai/gpt-5.5-low'
        with llm_client.llm_budget_limit_scope(10,lambda:0,required=True),patch.object(client,'_count_tokens',return_value=(1,'mock')),patch.object(llm_client,'append_jsonl'):
            client._try_log_call('complete_text','ok',time.monotonic(),response_text='accepted',response={'usage':{'prompt_tokens':1,'completion_tokens':2}})
            self.assertFalse(llm_client.llm_accounting_degraded())
            llm_client._claim_model_request(client.model,reserved_cost_cny=1)

    def test_rewrite_invalidates_descendants_without_inventing_next_meta(self):
        d=self.ws/'outputs/drafts';d.mkdir()
        for n in (1,2): (d/f'chapter_{n:02d}.meta.json').write_text('{"verdict":"Approve"}')
        with use_workspace('audit'):
            story_memory.invalidate_from(d,1,include_target=False)
            self.assertEqual(json.loads((d/'chapter_01.meta.json').read_text()),{'verdict':'Approve'})
            self.assertTrue(json.loads((d/'chapter_02.meta.json').read_text())['story_memory_invalidated'])
            story_memory.invalidate_from(d,2,include_target=False)
            self.assertFalse((d/'chapter_03.meta.json').exists())

    def test_wrapper_tier_argv_and_missing_value(self):
        fake=self.root/'python3';fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n');fake.chmod(0o700)
        env={**os.environ,'PATH':str(self.root)+os.pathsep+os.environ['PATH']}
        for args in (['--tier','mid'],['--tier=mid']):
            r=subprocess.run(['bash','scripts/write_book.sh',*args],env=env,text=True,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout.splitlines()[-2:],['--tier','mid'])
        r=subprocess.run(['bash','scripts/write_book.sh','--tier'],env=env,capture_output=True)
        self.assertEqual(r.returncode,64)

    def _planner_response(self, numbers):
        from src.schemas import ChapterPlan
        return ChapterPlan(target_chapters=99, overall_arc='synthetic arc', chapters=[
            dict(chapter_no=n, title=f'item-{i}', opening_scene='arrival',
                 key_events=['arrive', 'investigate'], ending_hook='a clue', plot_purpose='progress')
            for i, n in enumerate(numbers)])

    def test_fresh_plan_rejects_incomplete_without_replacing_existing(self):
        from src.plot_planner import generate_chapter_plan
        with use_workspace('audit'):
            paths.outline_path().parent.mkdir(parents=True, exist_ok=True)
            paths.outline_path().write_text('# Synthetic outline')
            for count in (0, 2):
                for existing in (False, True):
                    with self.subTest(count=count, existing=existing):
                        plan = paths.chapter_plan_path()
                        if existing:
                            plan.write_text('{"prior": "preserved"}')
                        else:
                            plan.unlink(missing_ok=True)
                        with patch('src.plot_planner.LLMClient') as client:
                            client.return_value.complete_json.return_value = self._planner_response(range(count))
                            with self.assertRaisesRegex(ValueError, 'incomplete_generated_plan'):
                                generate_chapter_plan(target_chapters=3, force=True)
                            self.assertEqual(client.return_value.complete_json.call_count, 1)
                        self.assertEqual(plan.exists(), existing)
                        if existing:
                            self.assertEqual(plan.read_text(), '{"prior": "preserved"}')

    def test_fresh_plan_normalizes_requested_coverage_before_fingerprinting(self):
        from src.plot_planner import generate_chapter_plan, chapter_plan_item_fingerprint
        with use_workspace('audit'):
            paths.outline_path().parent.mkdir(parents=True, exist_ok=True)
            paths.outline_path().write_text('# Synthetic outline')
            for numbers in ([9, 9, 2], [0, 7, 7, 99]):
                with self.subTest(numbers=numbers), patch('src.plot_planner.LLMClient') as client:
                    client.return_value.complete_json.return_value = self._planner_response(numbers)
                    data = generate_chapter_plan(target_chapters=3, force=True)
                    self.assertEqual(data['target_chapters'], 3)
                    self.assertEqual([c['chapter_no'] for c in data['chapters']], [1, 2, 3])
                    self.assertEqual([c['title'] for c in data['chapters']], ['item-0', 'item-1', 'item-2'])
                    for chapter in data['chapters']:
                        self.assertEqual(chapter['chapter_plan_item_fingerprint'], chapter_plan_item_fingerprint(chapter))
                    self.assertEqual(json.loads(paths.chapter_plan_path().read_text()), data)


class ModelRequestCancellationTests(unittest.TestCase):
    def test_cancelled_before_request_has_no_provider_or_usage(self):
        from src.llm_client import LLMClient, llm_request_check_scope, llm_request_limit_scope
        with patch.object(llm_client, 'resolved_model_config', return_value={'model':'openai/gpt-5.5','max_tokens':32}):
            client=LLMClient()
        def stopped(): raise jobs.JobCancelled('test cancel')
        with patch('litellm.completion') as provider, patch.object(client,'_try_log_call') as log:
            with llm_request_limit_scope(2), llm_request_check_scope(stopped):
                with self.assertRaises(jobs.JobCancelled): client.complete_text([{'role':'user','content':'test'}])
                self.assertEqual(llm_client._LLM_REQUEST_LIMIT.get(),(2,0))
            provider.assert_not_called(); log.assert_not_called()

    def test_cancel_after_bad_response_prevents_json_repair(self):
        from pydantic import BaseModel
        from src.llm_client import LLMClient, llm_request_check_scope
        class Answer(BaseModel):
            answer: str
        cancelled=False
        def check():
            if cancelled: raise jobs.JobCancelled('test cancel')
        def complete(**kwargs):
            nonlocal cancelled
            cancelled=True
            return {'choices':[{'message':{'content':'{broken'}}],'usage':{'prompt_tokens':3,'completion_tokens':2}}
        with patch.object(llm_client,'resolved_model_config',return_value={'model':'openai/gpt-5.5','max_tokens':32,'json_repair':True}):
            client=LLMClient()
        with patch('litellm.completion',side_effect=complete) as provider, patch.object(client,'_try_log_call') as log, llm_request_check_scope(check):
            with self.assertRaises(jobs.JobCancelled): client.complete_json([{'role':'user','content':'test'}],Answer)
            self.assertEqual(provider.call_count,1)
            self.assertEqual(log.call_count,1)
            self.assertEqual(log.call_args.args[1],'ok')

    def test_success_in_flight_is_retained_then_next_call_stops(self):
        from src.llm_client import LLMClient, llm_request_check_scope
        cancelled=False
        def check():
            if cancelled: raise jobs.JobTimeout('test timeout')
        def complete(**kwargs):
            nonlocal cancelled
            cancelled=True
            return {'choices':[{'message':{'content':'OK'}}],'usage':{'prompt_tokens':3,'completion_tokens':2}}
        with patch.object(llm_client,'resolved_model_config',return_value={'model':'openai/gpt-5.5','max_tokens':32}): client=LLMClient()
        with patch('litellm.completion',side_effect=complete) as provider, patch.object(client,'_try_log_call') as log, llm_request_check_scope(check):
            self.assertEqual(client.complete_text([{'role':'user','content':'test'}]),'OK')
            with self.assertRaises(jobs.JobTimeout):client.complete_text([{'role':'user','content':'next'}])
            self.assertEqual(provider.call_count,1);self.assertEqual(log.call_count,1)
        self.assertIsNone(llm_client._LLM_REQUEST_CHECK.get())

    def test_nested_cancel_scope_restores_parent(self):
        from src.llm_client import llm_request_check_scope
        def parent(): pass
        def child(): raise jobs.JobCancelled('test')
        with llm_request_check_scope(parent):
            with self.assertRaises(jobs.JobCancelled), llm_request_check_scope(child):
                llm_client._claim_model_request()
            self.assertIs(llm_client._LLM_REQUEST_CHECK.get(),parent)
        self.assertIsNone(llm_client._LLM_REQUEST_CHECK.get())
