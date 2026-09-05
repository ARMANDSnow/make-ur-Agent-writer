"""Only synthetic workspaces; failed review does not force another writing call."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src import paths, writer, partial_recovery as recovery
from src.cli_workspace import init_workspace
from src.web.workspace_ctx import use_workspace


class PartialRecoveryTests(unittest.TestCase):
    def setUp(self):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(paths,'WORKSPACE_DIR',root))
        self.enterContext(patch.dict(os.environ,OPENAI_MODEL='mock',WORKSPACE_NAME='',BOOK=''))
        init_workspace('partial',creation_mode='greenfield')
        self.enterContext(use_workspace('partial'))
        self.drafts=paths.drafts_dir();self.drafts.mkdir(exist_ok=True)
        paths.outline_path().parent.mkdir(exist_ok=True);paths.outline_path().write_text('# outline')
        paths.kb_path().parent.mkdir(exist_ok=True);paths.kb_path().write_text('# knowledge');paths.index_path().write_text('{}')
        self.enterContext(patch.object(writer,'load_config',return_value={'max_review_attempts':2,'polish_pass':False,'review_during_lint_block':False}))
        self.enterContext(patch.object(writer,'_load_chapter_plan',return_value=None))
        self.enterContext(patch.object(writer.NovelLinter,'lint',return_value=[]))
        self.write=self.enterContext(patch.object(writer,'_complete_write_text',return_value='完整合成正文'))
        self.review=self.enterContext(patch.object(writer,'review_text',side_effect=RuntimeError('synthetic review interruption')))
        self.enterContext(patch.object(writer,'_summarize_chapter',return_value={'summary':'summary','key_events':[],'ending_state':'end'}))
        self.enterContext(patch.object(writer,'_propose_entity_advance',return_value=[]))
        self.partial=self.drafts/'chapter_01.partial.md';self.failure=self.drafts/'chapter_01.failure.json'

    def fail_review(self):
        with self.assertRaisesRegex(RuntimeError,'synthetic review'):
            writer.write_chapters(chapters=1,force=True,max_attempts=1)
        self.write.reset_mock();self.review.reset_mock()
        self.context=json.loads(self.failure.read_text())['run_context']
        return self.partial.read_bytes(),self.failure.read_bytes()

    def test_resume_skips_write_but_runs_review_and_preserves_snapshot(self):
        before=self.fail_review()
        self.review.side_effect=None;self.review.return_value={'verdict':'Approve','agent_reviews':[],'lint_issues':[]}
        writer.write_chapters(chapters=1,force=True,resume_partial=True,max_attempts=1)
        self.write.assert_not_called();self.review.assert_called_once()
        self.assertEqual((self.drafts/'chapter_01.md').read_bytes(),before[0])
        snapshots=list((self.drafts/'snapshots').glob('partial_*'))
        self.assertEqual(len(snapshots),1)
        self.assertEqual((snapshots[0]/self.partial.name).read_bytes(),before[0])
        self.assertEqual((snapshots[0]/self.failure.name).read_bytes(),before[1])

    def test_again_failed_review_keeps_previous_generation_and_retry_rewrites_only_once(self):
        before=self.fail_review()
        with self.assertRaisesRegex(RuntimeError,'synthetic review'):
            writer.write_chapters(chapters=1,force=True,resume_partial=True,max_attempts=1)
        self.write.assert_not_called()
        self.assertEqual(self.partial.read_bytes(),before[0])
        self.assertEqual(len(list((self.drafts/'snapshots').glob('partial_*'))),1)
        self.review.side_effect=[{'verdict':'Reject','agent_reviews':[],'lint_issues':[]}, {'verdict':'Approve','agent_reviews':[],'lint_issues':[]}]
        writer.write_chapters(chapters=1,force=True,resume_partial=True,max_attempts=2)
        self.write.assert_called_once()

    def test_legacy_bad_context_hash_or_stage_not_reused(self):
        raw,failure_raw=self.fail_review();original=json.loads(failure_raw)
        variants=[]
        for field,value in [('schema_version',1),('stage','write'),('draft_sha256','wrong'),('chapter',2)]:
            item=copy.deepcopy(original);item[field]=value;variants.append(item)
        for field in ('start_point_fingerprint','chapter_plan_item_fingerprint','plan_fingerprint','model','review_tier'):
            item=copy.deepcopy(original);item['run_context'][field]='changed';variants.append(item)
        for item in variants:
            self.failure.write_text(json.dumps(item))
            self.assertEqual(recovery.prepare_partial_resume(1,self.context,allow_resume=True),'')
            self.assertEqual(self.partial.read_bytes(),raw)
        self.failure.write_bytes(failure_raw)
        self.assertEqual(recovery.prepare_partial_resume(1,self.context,allow_resume=False),'')

    def test_snapshot_failure_is_zero_call_and_keeps_old_evidence(self):
        before=self.fail_review()
        with patch.object(recovery,'_snapshot',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):writer.write_chapters(chapters=1,force=True,resume_partial=True)
        self.write.assert_not_called();self.review.assert_not_called()
        self.assertEqual((self.partial.read_bytes(),self.failure.read_bytes()),before)

    def test_unsafe_evidence_and_canonical_race_stop_before_reuse(self):
        before=self.fail_review()
        self.partial.unlink();self.partial.symlink_to(self.failure)
        with self.assertRaises(OSError):recovery.prepare_partial_resume(1,self.context,allow_resume=True)
        self.partial.unlink();os.mkfifo(self.partial)
        with self.assertRaises(OSError):recovery.prepare_partial_resume(1,self.context,allow_resume=True)
        self.partial.unlink();self.partial.write_bytes(before[0])
        with patch.object(recovery,'DRAFT_LIMIT',1):
            with self.assertRaises(OSError):recovery.prepare_partial_resume(1,self.context,allow_resume=True)
        snapshot=recovery._snapshot
        def race(*args):
            snapshot(*args);(self.drafts/'chapter_01.md').write_text('new canonical')
        with patch.object(recovery,'_snapshot',side_effect=race):
            with self.assertRaises(OSError):recovery.prepare_partial_resume(1,self.context,allow_resume=True)
        self.write.assert_not_called();self.review.assert_not_called()
