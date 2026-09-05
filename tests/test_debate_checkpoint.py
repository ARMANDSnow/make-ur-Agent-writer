"""Synthetic interruption/resume evidence; every model boundary is mocked."""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import debater, paths
from src.cli_workspace import init_workspace
from src.web.workspace_ctx import use_workspace


class DebateCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(paths, 'WORKSPACE_DIR', Path(self.temp)))
        self.enterContext(patch.dict(os.environ, {'OPENAI_MODEL': 'mock', 'WORKSPACE_NAME': '', 'BOOK': ''}))
        init_workspace('checkpoint', creation_mode='greenfield')
        self.enterContext(use_workspace('checkpoint'))
        paths.kb_path().parent.mkdir(parents=True, exist_ok=True)
        paths.kb_path().write_text('# synthetic knowledge')
        paths.index_path().write_text('{}')
        self.enterContext(patch.object(debater, 'load_personas', return_value={}))
        self.enterContext(patch.object(debater, 'ROUNDS', ['synthetic']))
        self.enterContext(patch.object(debater, 'load_agents', return_value=[{'name': n} for n in ('a', 'b', 'c')]))
        self.text = self.enterContext(patch.object(debater.LLMClient, 'complete_text', return_value='synthetic response'))
        self.build = self.enterContext(patch.object(debater, 'build_decisions', side_effect=lambda *a: {
            'votes': [{'question': 'fixed question', 'result': 'proposal', 'for': [], 'against': []}],
            'transcript_items': 3, 'aggregation_method': 'majority'}))
        self.outline = self.enterContext(patch.object(debater, 'build_outline', return_value='# synthetic outline'))
        self.collect = self.enterContext(patch.object(debater, '_collect_agent_votes', side_effect=self.ballot))
        self.log = paths.debate_dir() / 'debate_log.jsonl'

    def ballot(self, agent, *args):
        return {'response': 'synthetic vote', 'ballots': [{'agent_name': agent['name'], 'question_index': 0,
                'position': 'agree', 'reason': 'synthetic'}]}

    def rows(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def interrupt_after_one_ballot(self):
        def fail(agent, *args):
            if agent['name'] == 'b':
                raise RuntimeError('synthetic interruption')
            return self.ballot(agent)
        self.collect.side_effect = fail
        with self.assertRaises(RuntimeError):
            debater.run_debate()
        self.collect.reset_mock()
        self.build.reset_mock()
        self.text.reset_mock()
        self.collect.side_effect = self.ballot

    def test_partial_ballots_and_outline_failure_resume_same_questions(self):
        self.interrupt_after_one_ballot()
        original = next(x for x in self.rows() if x.get('meta') == 'debate_decisions_checkpoint')
        self.outline.side_effect = RuntimeError('synthetic outline failure')
        with self.assertRaises(RuntimeError):
            debater.run_debate()
        self.assertEqual([c.args[0]['name'] for c in self.collect.call_args_list], ['b', 'c'])
        self.build.assert_not_called()
        self.text.assert_not_called()
        self.collect.reset_mock()
        self.outline.side_effect = None
        result = debater.run_debate()
        self.collect.assert_not_called()
        self.build.assert_not_called()
        self.assertEqual(len(result['decisions']['votes'][0]['agent_votes']), 3)
        checkpoints = [x for x in self.rows() if x.get('meta') == 'debate_decisions_checkpoint']
        self.assertEqual(checkpoints, [original])
        self.assertEqual(len([x for x in self.rows() if x.get('round_name') == '裁决投票']), 3)

    def test_corrupt_or_legacy_checkpoint_preserves_log_and_sends_nothing(self):
        self.interrupt_after_one_ballot()
        original = self.rows()
        variants = []
        missing = [x for x in original if x.get('meta') != 'debate_decisions_checkpoint']
        variants.append(missing)
        changed = copy.deepcopy(original)
        next(x for x in changed if x.get('round') == 1)['response'] = 'changed'
        variants.append(changed)
        changed = copy.deepcopy(original)
        next(x for x in changed if x.get('round_name') == '裁决投票')['decisions_fingerprint'] = 'wrong'
        variants.append(changed)
        variants.append(original + [copy.deepcopy(next(x for x in original if x.get('meta') == 'debate_decisions_checkpoint'))])
        variants.append(original + [copy.deepcopy(next(x for x in original if x.get('round_name') == '裁决投票'))])
        for rows in variants:
            with self.subTest(rows=len(rows)):
                self.log.write_text(''.join(json.dumps(x) + '\n' for x in rows))
                before = self.log.read_bytes()
                with self.assertRaises(ValueError):
                    debater.run_debate()
                self.assertEqual(self.log.read_bytes(), before)
        self.collect.assert_not_called()
        self.build.assert_not_called()
        self.text.assert_not_called()

    def test_checkpoint_write_failure_prevents_all_ballots(self):
        with patch.object(debater, 'write_text_atomic', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                debater.run_debate()
        self.collect.assert_not_called()
        self.assertFalse(any(x.get('round_name') == '裁决投票' for x in self.rows()))

    def test_broken_checkpoint_before_first_ballot_cannot_be_discarded(self):
        self.collect.side_effect = RuntimeError('synthetic interruption before first ballot')
        with self.assertRaises(RuntimeError):
            debater.run_debate()
        original = self.rows()
        self.collect.reset_mock()
        self.build.reset_mock()
        self.text.reset_mock()
        prefix = ''.join(json.dumps(x) + '\n' for x in original if x.get('meta') != 'debate_decisions_checkpoint')
        for broken in ('{"meta":"debate_decisions_checkpoint",', '[]', 'null'):
            self.log.write_text(prefix + broken + '\n')
            before = self.log.read_bytes()
            with self.assertRaises(ValueError):
                debater.run_debate()
            self.assertEqual(self.log.read_bytes(), before)
        self.collect.assert_not_called()
        self.build.assert_not_called()
        self.text.assert_not_called()
