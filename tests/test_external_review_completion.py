import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src import reviewer
from src.book_runner import _sync_meta_with_external_review
from src.chapter_status import chapter_status, classify_disposition, ChapterDisposition
from src.llm_client import LLMExecutionStopped
from src.utils import sha256_text, write_json


class ExternalReviewCompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.drafts = self.root / 'drafts'; self.drafts.mkdir()
        self.reviews = self.root / 'reviews'; self.reviews.mkdir()
        self.draft = self.drafts / 'chapter_01.md'; self.draft.write_text('正文。\n')
        self.meta = self.drafts / 'chapter_01.meta.json'
        self.report = self.reviews / 'chapter_01.review.json'
        self.ctx = {'start_chapter_id':'source1', 'start_point_fingerprint':'s', 'plan_fingerprint':'p', 'chapter_plan_item_fingerprint':'i'}
        self.inner = {'verdict':'Approve', 'needs_human_review':False, 'run_context':self.ctx, 'draft_sha256':sha256_text('正文。\n')}
        write_json(self.meta,self.inner); write_json(self.report,self.inner)
    def status(self):
        return chapter_status(1,self.drafts,validate_context=True,require_external_review=True,expected_context=self.ctx)
    def test_inner_report_and_wrong_marker_types_never_count_as_external(self):
        for marker in (None, False, 1, 'true'):
            write_json(self.report,dict(self.inner,external_review_completed=marker))
            status=self.status()
            self.assertFalse(status['approved'])
            self.assertEqual(status['strict_failures'],['external_review_incomplete'])
            self.assertEqual(classify_disposition(status,force=False,require_external_review=True),ChapterDisposition.SUPPLEMENT_EXTERNAL_REVIEW)
            for flag in ('failure','panel_halted','needs_review','hard_reject'):
                self.assertEqual(classify_disposition(dict(status,**{flag:True}),force=False,require_external_review=True),ChapterDisposition.BLOCK)
            before=self.meta.read_bytes()
            self.assertEqual(_sync_meta_with_external_review(self.drafts,1),{})
            self.assertEqual(self.meta.read_bytes(),before)
        for changes in ({'draft_sha256':'stale'}, {'run_context':dict(self.ctx,plan_fingerprint='stale')}, {'verdict':'Reject'}):
            write_json(self.report,dict(self.inner,external_review_completed=True,**changes))
            self.assertFalse(self.status()['approved'])
    def test_only_finished_external_review_marks_completion(self):
        agents=[{'name':f'agent{i}','system_prompt':'review'} for i in range(5)]
        for cancel_advisor in (True,False):
            calls=[]
            def complete(client,messages):
                prompt='\n'.join(m['content'] for m in messages); calls.append(prompt)
                if 'advisor_name:' in prompt and cancel_advisor:
                    raise LLMExecutionStopped('synthetic cancellation')
                return '{"verdict":"Approve","score":8,"issues":[],"suggestions":[]}'
            write_json(self.report,self.inner)
            with self.subTest(cancel=cancel_advisor), patch('src.reviewer._reviews_dir',return_value=self.reviews), patch('src.reviewer.load_review_agents',return_value=agents), patch('src.reviewer.load_advisor_agents',return_value=[{'name':'advisor','system_prompt':'advise'}]), patch('src.llm_client.LLMClient.complete_text',complete), patch('src.reviewer.log_event'), patch('src.reviewer.NovelLinter.lint',return_value=[]):
                if cancel_advisor:
                    with self.assertRaises(LLMExecutionStopped): reviewer.review_target(self.draft)
                    self.assertFalse(self.status()['approved'])
                    self.assertNotIn('external_review_completed',json.loads(self.report.read_text()))
                else:
                    reviewer.review_target(self.draft)
                    self.assertTrue(self.status()['approved'])
                    # A subsequent internal review must replace, not retain, the marker.
                    reviewer.review_text('正文。\n',self.draft.name,precomputed_lint_issues=[],run_context=self.ctx,draft_sha256=self.inner['draft_sha256'])
                    self.assertFalse(self.status()['approved'])
            self.assertGreaterEqual(len(calls),6)
    def test_completion_write_failure_leaves_unfinished_report(self):
        def saving(path,value):
            if value.get('external_review_completed') is True: raise OSError('synthetic write failure')
            write_json(path,value)
        with patch('src.reviewer._reviews_dir',return_value=self.reviews), patch('src.reviewer.review_text',return_value=dict(self.inner)), patch('src.reviewer.write_json',side_effect=saving):
            with self.assertRaises(OSError):reviewer.review_target(self.draft)
        self.assertFalse(self.status()['approved'])
