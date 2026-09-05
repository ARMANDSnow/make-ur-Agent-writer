"""Synthetic async transport tests: no network, credentials or workspaces."""
import asyncio
import json
import multiprocessing
import os
import struct
import tempfile
import time
import unittest
from pathlib import Path
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

from src import llm_client as llm
from src import openai_stream as transport


def chunk(text='', finish=None, usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=finish)],
        usage=None if usage is None else SimpleNamespace(model_dump=lambda: usage))


class FakeStream:
    def __init__(self, entries):
        self.entries = iter(entries)
        self.closed = False
        self.pending_reads = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        self.pending_reads += 1
        try:
            try:
                item = next(self.entries)
            except StopIteration:
                raise StopAsyncIteration
            if isinstance(item, float):
                await asyncio.sleep(item)
                return chunk('delayed')
            if isinstance(item, Exception):
                raise item
            return item
        finally:
            self.pending_reads -= 1

    async def close(self):
        self.closed = True


class BoundedStreamTests(unittest.TestCase):
    def setUp(self):
        token = llm._LLM_ACCOUNTING_DEGRADED.set(None)
        self.addCleanup(llm._LLM_ACCOUNTING_DEGRADED.reset, token)
        patcher = patch.object(transport, "receive", side_effect=lambda kwargs, check: asyncio.run(transport._receive(kwargs, check)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def setup_transport(self, entries, connect_delay=0):
        self.stream = FakeStream(entries)
        self.created = []
        self.closed = False
        self.connecting = False

        async def create(**kwargs):
            self.created.append(kwargs)
            self.connecting = True
            try:
                await asyncio.sleep(connect_delay)
                return self.stream
            finally:
                self.connecting = False

        async def close():
            self.closed = True

        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=close)
        patcher = patch('openai.AsyncOpenAI', return_value=fake)
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        self.kwargs = dict(model='openai/test', api_key='synthetic', api_base='https://example.invalid/v1',
                           messages=[{'role':'user','content':'synthetic'}], temperature=0, max_tokens=20, timeout=1)

    def test_native_usage_and_model_mapping(self):
        usage = {'prompt_tokens':7, 'completion_tokens':3}
        self.setup_transport([chunk('hello'), chunk(' world', 'stop'), chunk(usage=usage)])
        text, response = transport.receive(self.kwargs, lambda: None)
        self.assertEqual(text, 'hello world')
        self.assertEqual(response['usage'], usage)
        self.assertEqual(self.created[0]['model'], 'test')
        self.assertEqual(self.factory.call_args.kwargs['max_retries'], 0)
        self.assertTrue(self.stream.closed and self.closed)

    def test_missing_usage_is_not_synthesized(self):
        self.setup_transport([chunk('ok', 'stop')])
        _, response = transport.receive(self.kwargs, lambda: None)
        self.assertNotIn('usage', response)

    def test_reasoning_models_preserve_parameter_compatibility(self):
        for model in ('openai/gpt-5', 'openai/gpt-5.6-luna', 'openai/o3'):
            with self.subTest(model=model):
                self.setup_transport([chunk('ok', 'stop')])
                self.kwargs['model'] = model
                transport.receive(self.kwargs, lambda: None)
                self.assertNotIn('temperature', self.created[0])
                self.assertNotIn('max_tokens', self.created[0])
                self.assertEqual(self.created[0]['max_completion_tokens'], 20)

    def test_connection_is_deadline_bounded(self):
        self.setup_transport([], connect_delay=10)
        self.kwargs['timeout'] = .03
        before = time.monotonic()
        with self.assertRaises(transport.BoundedStreamFailure):
            transport.receive(self.kwargs, lambda: None)
        self.assertLess(time.monotonic() - before, 1)
        self.assertFalse(self.connecting)
        self.assertTrue(self.closed)

    def test_read_stall_closes_without_background_reader(self):
        self.setup_transport([chunk('partial'), 10.0])
        self.kwargs['timeout'] = .03
        with self.assertRaises(transport.BoundedStreamFailure):
            transport.receive(self.kwargs, lambda: None)
        self.assertEqual(self.stream.pending_reads, 0)
        self.assertTrue(self.stream.closed and self.closed)

    def test_continuous_data_does_not_extend_total_deadline(self):
        self.setup_transport([.01] * 30)
        self.kwargs['_deadline'] = time.monotonic() + .04
        before = time.monotonic()
        with self.assertRaises(transport.BoundedStreamFailure):
            transport.receive(self.kwargs, lambda: None)
        self.assertLess(time.monotonic() - before, .5)
        self.assertEqual(self.stream.pending_reads, 0)

    def test_cancel_during_read_discards_partial_and_closes(self):
        self.setup_transport([chunk('partial'), 10.0])
        cancel_at = time.monotonic() + .02
        def check():
            if time.monotonic() >= cancel_at:
                raise llm.LLMExecutionStopped('synthetic cancel')
        with self.assertRaises(llm.LLMExecutionStopped):
            transport.receive(self.kwargs, check)
        self.assertEqual(self.stream.pending_reads, 0)
        self.assertTrue(self.stream.closed)

    def test_disconnect_truncation_and_oversize_never_return_partial(self):
        for entries in ([chunk('partial'), ConnectionError('synthetic')],
                        [chunk('partial')], [chunk('partial', 'length')], [chunk('x' * 20, 'stop')]):
            with self.subTest(entries=len(entries)):
                self.setup_transport(entries)
                with patch.object(transport, 'MAX_RESPONSE_BYTES', 10), self.assertRaises(Exception):
                    transport.receive(self.kwargs, lambda: None)
                self.assertTrue(self.stream.closed and self.closed)

    def test_llm_client_opt_in_uses_native_stream_without_retry(self):
        self.setup_transport([chunk('partial'), ConnectionError('synthetic')])
        client = llm.LLMClient('compress')
        client.model = 'openai/gpt-4o-mini'
        client.config = {**client.config, 'model':client.model, 'openai_web_stream':True,
                         'api_key':'synthetic', 'request_timeout':1, 'retry_attempts':3}
        with patch('litellm.completion') as legacy, patch.object(llm, '_claim_model_request') as claim, \
             patch.object(client, '_try_log_call') as log, patch.object(client, '_count_tokens', return_value=(2,'synthetic')):
            with llm.llm_deadline_scope(time.monotonic()+2), self.assertRaises(llm.LLMProviderFailure):
                client.complete_text([{'role':'user','content':'synthetic'}])
            self.assertEqual(claim.call_count, 1)
            self.assertEqual(len(self.created), 1)
            legacy.assert_not_called()
            self.assertEqual(log.call_count, 2)

    def test_native_missing_usage_stops_next_request_in_parent_context(self):
        self.setup_transport([chunk('ok', 'stop')])
        client = llm.LLMClient('compress')
        client.model = 'openai/gpt-4o-mini'
        client.config = {**client.config, 'model':client.model, 'openai_web_stream':True,
                         'api_key':'synthetic', 'request_timeout':1}
        token = llm._LLM_ACCOUNTING_DEGRADED.set(None)
        self.addCleanup(llm._LLM_ACCOUNTING_DEGRADED.reset, token)
        with patch.object(llm, 'append_jsonl'), patch.object(client, '_count_tokens', return_value=(2,'synthetic')):
            with llm.llm_deadline_scope(time.monotonic()+2):
                self.assertEqual(client.complete_text([{'role':'user','content':'synthetic'}]), 'ok')
                self.assertTrue(llm.llm_accounting_degraded())
                with self.assertRaises(llm.LLMAccountingUnavailable):
                    client.complete_text([{'role':'user','content':'synthetic'}])
            self.assertEqual(len(self.created), 1)

    def test_cancelled_admitted_native_request_is_logged_once(self):
        self.setup_transport([chunk('partial'), 10.0])
        client = llm.LLMClient('compress')
        client.model = 'openai/gpt-4o-mini'
        client.config = {**client.config, 'model':client.model, 'openai_web_stream':True,
                         'api_key':'synthetic', 'request_timeout':1, 'retry_attempts':3}
        cancel_at = time.monotonic() + .02
        def check():
            if time.monotonic() >= cancel_at:
                raise llm.LLMExecutionStopped('synthetic cancel')
        with patch.object(llm, '_claim_model_request') as claim, patch.object(client, '_try_log_call') as log, \
             patch.object(client, '_count_tokens', return_value=(2,'synthetic')):
            with llm.llm_deadline_scope(time.monotonic()+2), llm.llm_request_check_scope(check):
                with self.assertRaises(llm.LLMExecutionStopped):
                    client.complete_text([{'role':'user','content':'synthetic'}])
            self.assertEqual(claim.call_count, 1)
            self.assertEqual(log.call_count, 1)
            self.assertEqual(log.call_args.args[1], 'retry_error')
            self.assertEqual(llm.public_llm_failure_reason(log.call_args.args[3]), 'submission_unknown')
            self.assertTrue(log.call_args.kwargs['request_meta']['usage_unknown'])
            self.assertTrue(llm.llm_accounting_degraded())
            self.assertEqual(self.stream.pending_reads, 0)

    def test_close_failure_does_not_replace_success(self):
        self.setup_transport([chunk('ok', 'stop')])
        async def failed_close():
            raise OSError('synthetic close failure')
        self.stream.close = failed_close
        text, _ = transport.receive(self.kwargs, lambda: None)
        self.assertEqual(text, 'ok')
        self.assertTrue(self.closed)


def blocked_worker(connection, ready):
    # A DNS executor or SDK cleanup that cannot be cooperatively cancelled.
    ready.set()
    time.sleep(60)


def successful_worker(connection):
    kwargs = json.loads(connection.recv_bytes(transport.MAX_REQUEST_BYTES))
    connection.send_bytes(json.dumps([True, kwargs.get("content", "ok"), None]).encode())
    connection.close()


def partial_frame_worker(connection, ready):
    connection.recv_bytes(transport.MAX_REQUEST_BYTES)
    os.write(connection.fileno(), struct.pack('!i', 10000) + b'[')
    ready.set()
    time.sleep(60)


class ProcessBoundaryTests(unittest.TestCase):
    def test_large_request_to_stalled_startup_is_deadline_bounded(self):
        before_children = {p.pid for p in multiprocessing.active_children()}
        ready = multiprocessing.get_context('spawn').Event()
        started = time.monotonic()
        with patch.object(transport, '_worker', partial(blocked_worker, ready=ready)):
            with self.assertRaises(transport.BoundedStreamFailure):
                transport.receive({'timeout':3, 'messages':'x'*(2*1024*1024)}, lambda: None)
        self.assertTrue(ready.is_set())
        self.assertLess(time.monotonic()-started, 4)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before_children)

    def test_large_escaped_response_roundtrip(self):
        content = '\n"\x00' * (transport.MAX_RESPONSE_BYTES // 3)
        with patch.object(transport, '_worker', successful_worker):
            self.assertEqual(transport.receive({'timeout':10, 'content':content}, lambda: None)[0], content)

    def test_unknown_usage_retains_reservation_without_double_counting_summary(self):
        from src.cost_estimator import estimate_cost_since
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'logs').mkdir()
            attempt = {'status':'retry_error', 'usage_unknown':True, 'reserved_cost_cny':2.5,
                       'model':'openai/gpt-4o-mini', 'prompt_tokens':2, 'response_tokens':0}
            summary = {**attempt, 'status':'error', 'prompt_tokens':0, 'final_of_attempts':1}
            (root/'logs/llm_calls.jsonl').write_text('\n'.join(json.dumps(x) for x in (attempt, summary)))
            self.assertEqual(estimate_cost_since(root=root)['cost_cny'], 2.5)

    def test_deadline_terminates_stuck_worker(self):
        before_children = {p.pid for p in multiprocessing.active_children()}
        ready = multiprocessing.get_context('spawn').Event()
        started = time.monotonic()
        with patch.object(transport, '_worker', partial(blocked_worker, ready=ready)):
            with self.assertRaises(transport.BoundedStreamFailure):
                transport.receive({'timeout':3}, lambda: None)
        self.assertTrue(ready.is_set())
        self.assertLess(time.monotonic()-started, 4)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before_children)

    def test_partial_ipc_frame_is_still_deadline_bounded(self):
        before_children = {p.pid for p in multiprocessing.active_children()}
        ready = multiprocessing.get_context('spawn').Event()
        started = time.monotonic()
        with patch.object(transport, '_worker', partial(partial_frame_worker, ready=ready)):
            with self.assertRaises(transport.BoundedStreamFailure):
                transport.receive({'timeout':3}, lambda: None)
        self.assertTrue(ready.is_set())
        self.assertLess(time.monotonic()-started, 4)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before_children)

    def test_cancel_terminates_stuck_cleanup_and_reaps_process(self):
        before_children = {p.pid for p in multiprocessing.active_children()}
        ready = multiprocessing.get_context('spawn').Event()
        def check():
            if ready.is_set():
                raise llm.LLMExecutionStopped('synthetic cancel')
        with patch.object(transport, '_worker', partial(blocked_worker, ready=ready)):
            with self.assertRaises(llm.LLMExecutionStopped):
                transport.receive({'timeout':10}, check)
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before_children)

    def test_successful_worker_is_reaped(self):
        before_children = {p.pid for p in multiprocessing.active_children()}
        with patch.object(transport, '_worker', successful_worker):
            self.assertEqual(transport.receive({'timeout':5}, lambda: None)[0], 'ok')
        self.assertEqual({p.pid for p in multiprocessing.active_children()}, before_children)
