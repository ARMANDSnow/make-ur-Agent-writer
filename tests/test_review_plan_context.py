import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from src import reviewer


class ReviewPlanContextTests(unittest.TestCase):
    def test_bounded_whitelist_and_bad_types(self):
        for plan in (None, {}, [], {'title': {'private': 'HIDDEN'}, 'key_events': [False, {}], 'target_chinese_chars': True}):
            self.assertEqual(reviewer._review_plan_block(plan), '')
        plan = {'title': '\x00' * 100000, 'opening_scene': 'O' * 100000,
                'key_events': ['EVENT' + '\x00' * 10000] * 10000,
                'relationships_in_play': ['REL' * 10000] * 100,
                'chapter_plan_item_fingerprint': 'HIDDEN', 'continuity_constraints': 'HIDDEN',
                'chapters': [{'title': 'FUTURE'}], 'target_chinese_chars': 4000}
        block = reviewer._review_plan_block(plan)
        self.assertLessEqual(len(block), 6000)
        self.assertIn('EVENT', block)
        self.assertNotIn('HIDDEN', block)
        self.assertNotIn('FUTURE', block)
        payload = json.loads(block.split('\n')[-3])
        self.assertEqual(len(payload['key_events']), 7)
        self.assertEqual(len(payload['relationships_in_play']), 8)
        self.assertIn('已有硬事实', block)
        self.assertIn('摘要可能截断', block)

    def test_all_reviewers_advisor_and_parse_fallback_receive_same_plan(self):
        plan = {'title': 'PLAN_MARKER', 'key_events': ['找钥匙', '开门'],
                'opening_scene': '门外', 'ending_hook': '门开', 'plot_purpose': '推进'}
        block = reviewer._review_plan_block(plan)
        for malformed in (None, 'not json', 'schema_error'):
            captured = []
            def complete(client, messages):
                prompt = '\n'.join(m['content'] for m in messages)
                captured.append(prompt)
                if 'advisor_name:' in prompt:
                    return '{"suggestions":[]}'
                if '最简化' in prompt:
                    return '{"verdict":"Approve","reason":"ok"}'
                if malformed == 'not json':
                    return malformed
                return '{"verdict":"Approve","score":8,"issues":[],"suggestions":[]}'
            with self.subTest(malformed=malformed), tempfile.TemporaryDirectory() as tmp, patch(
                'src.reviewer._reviews_dir', return_value=Path(tmp)
            ), patch('src.reviewer.load_review_agents', return_value=[{'name': 'agent'+str(i), 'system_prompt': 'review'} for i in range(5)]), patch(
                'src.reviewer.load_advisor_agents', return_value=[{'name':'advisor', 'system_prompt':'advise'}]
            ), patch('src.llm_client.LLMClient.complete_text', complete), patch('src.reviewer.log_event'), patch(
                'src.reviewer.AgentReview', side_effect=ValueError('synthetic schema failure') if malformed == 'schema_error' else reviewer.AgentReview
            ):
                reviewer.review_text('合成正文。', precomputed_lint_issues=[], chapter_plan_item=plan, persist=False)
            self.assertEqual(len(captured), 6 if malformed is None else 11)
            self.assertTrue(all(block in prompt for prompt in captured))
