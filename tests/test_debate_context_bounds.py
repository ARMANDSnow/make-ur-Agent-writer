"""Long synthetic debate prompts must preserve coverage within finite budgets."""
import copy
import json
import unittest
from unittest.mock import PropertyMock, patch
from src import debater
from src.llm_client import LLMClient, LLMContextOverflowError
from src.schemas import DebateDecisions


class DebateContextBoundsTests(unittest.TestCase):
    def rows(self, count=36):
        return [{'round': i // 6 + 1, 'round_name': 'round', 'agent': f'agent_{i%6}',
                 'response': f'HEAD_{i} ' + '\\"\n中' * 4000 + f' TAIL_{i}'} for i in range(count)]

    def test_each_speaker_and_round_survives_serialized_length_bound(self):
        for count in (30, 36):
            rows=self.rows(count);before=copy.deepcopy(rows)
            summary=debater._transcript_summary(rows,max_chars=6000)
            self.assertLessEqual(len(summary),6000)
            parsed=json.loads(summary)
            self.assertEqual(len(parsed),count)
            for i,item in enumerate(parsed):
                self.assertEqual((item['round'],item['agent']),(rows[i]['round'],rows[i]['agent']))
                self.assertIn(f'HEAD_{i}',item['response']);self.assertIn(f'TAIL_{i}',item['response'])
            self.assertEqual(rows,before)

    def test_frozen_context_budget_shrinks_excerpt_and_keeps_fixed_content(self):
        client=LLMClient('debate');client.config={**client.config,'context_limit':2000,'max_tokens':100}
        rows=self.rows(2)
        with patch.object(client,'_count_tokens',side_effect=lambda s:(len(s),'synthetic')):
            messages=debater._fit_transcript_messages(client,rows,lambda excerpt:[{'role':'user','content':'fixed question\n'+excerpt}])
            self.assertIn('fixed question',messages[0]['content'])
            self.assertLessEqual(len(messages[0]['content'])+100,1800)
            with self.assertRaises(LLMContextOverflowError):
                debater._fit_transcript_messages(client,rows,lambda excerpt:[{'role':'user','content':'x'*2000+excerpt}])

    def test_narrow_valid_window_and_short_responses_remain_usable(self):
        client=LLMClient('debate');client.config={**client.config,'context_limit':6112,'max_tokens':100}
        rows=self.rows()
        for row in rows:row['round_name']='round descriptive name'
        with patch.object(client,'_count_tokens',side_effect=lambda s:(len(s),'synthetic')):
            messages=debater._fit_transcript_messages(client,rows,lambda excerpt:[{'role':'user','content':excerpt}])
        parsed=json.loads(messages[0]['content'])
        self.assertLessEqual(len(messages[0]['content']),5400)
        for i,item in enumerate(parsed):
            self.assertIn(f'HEAD_{i}',item['response']);self.assertIn(f'TAIL_{i}',item['response'])
        short=[{'round':1,'agent':str(i),'response':'x'} for i in range(35)]
        short.append({'round':1,'agent':'last','response':'HEAD'+'z'*10000+'TAIL'})
        minimum=len(debater._transcript_excerpt(short,0))
        result=json.loads(debater._transcript_summary(short,max_chars=minimum+20))
        self.assertEqual([x['response'] for x in result[:-1]],['x']*35)
        self.assertIn('HEAD',result[-1]['response']);self.assertIn('TAIL',result[-1]['response'])

    def test_decisions_and_other_consumers_include_last_speaker_and_full_questions(self):
        client=LLMClient('debate');rows=self.rows();agents=[{'name':f'agent_{i}'} for i in range(6)]
        decisions={'votes':[{'question':'Q'+str(i)+'x'*1400+'END_Q'+str(i),'result':'RESULT_'+str(i),'for':[],'against':[]} for i in range(5)]}
        with patch.object(LLMClient,'is_mock',new_callable=PropertyMock,return_value=False), \
             patch.object(debater,'_start_point_prompt_block',return_value=''), \
             patch.object(debater,'_anchor_prompt_block',return_value=''), \
             patch.object(debater,'_style_prompt_block',return_value=''), \
             patch.object(debater,'load_entity_graph',return_value={}), \
             patch.object(debater,'load_personas',return_value=None), \
             patch.object(debater,'global_facts_summary',return_value=''), \
             patch.object(debater,'log_event'):
            with patch.object(client,'complete_json',return_value=DebateDecisions(**decisions)) as call:
                debater.build_decisions(agents,rows,client)
                content=call.call_args.args[0][1]['content']
                self.assertIn('TAIL_35',content)
                tokens,_=client._count_tokens(content);client._check_context(tokens,client.config['max_tokens'])
            with patch.object(client,'complete_text',return_value='# outline') as call:
                debater.build_outline('topic',decisions,rows,client)
                content=call.call_args.args[0][1]['content']
                self.assertIn('TAIL_35',content)
                for vote in decisions['votes']:self.assertIn(vote['question'],content)
            ballots={'ballots':[{'question_index':i,'position':'agree','reason':'ok'} for i in range(5)]}
            with patch.object(client,'complete_text',return_value=json.dumps(ballots)) as call:
                debater._collect_agent_votes(agents[0],decisions['votes'],rows,client)
                content=call.call_args.args[0][1]['content']
                self.assertIn('TAIL_35',content)
                for vote in decisions['votes']:self.assertIn(vote['question'],content)
            with patch.object(client,'complete_text',return_value=json.dumps(decisions)) as call:
                debater._legacy_llm_derived_votes(agents,rows,client)
                self.assertIn('TAIL_35',call.call_args.args[0][1]['content'])
