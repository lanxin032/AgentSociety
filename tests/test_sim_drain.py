"""Failure drain preserves paid responses and blocks world advancement; no network/Ray."""
import asyncio
import os
os.environ.setdefault("AGENTSOCIETY_LLM_API_KEY", "offline")
os.environ.setdefault("AGENTSOCIETY_CODER_LLM_API_KEY", "offline")
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from policy_sim.client import ModelClient, ModelClientError, STOP_FILE
from policy_sim.driver import TaskDrain
from policy_sim.evidence import load_model_events


class Response(SimpleNamespace):
    def model_dump(self, **kwargs):
        return {"id": "settled", "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                "choices": [{"finish_reason": "stop", "message": {"content": "memory"}}]}


class DrainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ready, self.release = asyncio.Event(), asyncio.Event()
        self.sent = 0
        async def call(**kwargs):
            self.sent += 1
            self.ready.set()
            await self.release.wait()
            return Response(choices=[SimpleNamespace(finish_reason="stop",
                message=SimpleNamespace(content="memory"))])
        self.client = ModelClient("http://127.0.0.1:1/v1", self.root / "model_requests.jsonl",
            client=SimpleNamespace(call=call), context={"run_id": "drain-test", "round": 0})

    async def request(self):
        return await self.client.for_context("memory", actor_id=2).call(
            messages=[{"role": "user", "content": "memory"}])

    async def test_cancel_waits_for_paid_response_then_records_terminal_failure(self):
        task = asyncio.create_task(self.request())
        await self.ready.wait()
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        rows = load_model_events(self.root)
        self.assertEqual([r["event"] for r in rows], ["request_started", "request_failed"])
        self.assertEqual(rows[-1]["error_type"], "request_cancelled")
        self.assertEqual(rows[-1]["usage"], {"prompt_tokens": 3, "completion_tokens": 1})
        self.assertEqual(len(list((self.root / "model_payloads").glob("*.response.json"))), 1)
        with self.assertRaises(ModelClientError):
            await self.request()
        self.assertEqual(self.sent, 1)

    async def test_cancelled_transport_has_terminal_event_without_invented_usage(self):
        async def cancel(**kwargs):
            raise asyncio.CancelledError()
        self.client.client.call = cancel
        with self.assertRaises(asyncio.CancelledError):
            await self.request()
        row = load_model_events(self.root)[-1]
        self.assertEqual(row["event"], "request_failed")
        self.assertNotIn("usage", row)

    async def test_official_gather_failure_drains_before_shutdown_without_env_step(self):
        from agentsociety2.society import AgentSociety
        import importlib
        module = importlib.import_module("agentsociety2.society.society")
        drain = TaskDrain(self.root, timeout=2)
        advanced = []
        async def env_step(*args):
            advanced.append("world")
        async def persistence(**kwargs):
            advanced.append("checkpoint")
        async def proxy():
            return None
        async def batch(ids):
            if ids == [1]:
                await self.ready.wait()
                return {"results": [{"ok": False}]}
            await self.request()
            # Same-attempt cross-process client copy must see the durable stop.
            other = ModelClient("http://127.0.0.1:1/v1", self.root / "model_requests.jsonl",
                client=self.client.client, context={"run_id": "drain-test", "round": 0})
            with self.assertRaisesRegex(ModelClientError, "attempt_stopping"):
                await other.for_context("memory", actor_id=2).call(messages=[])
            return {"results": [{"ok": True}]}
        def validate(result):
            if any(not r["ok"] for r in result["results"]):
                raise RuntimeError("agent failed")
        async def await_ref(ref):
            return await drain.wait(ref, validate)
        fake = SimpleNamespace(_agent_ids=[1, 2], _batch_size=1,
            _workspace_root=self.root, _agent_class_name="PolicyOfficer", _t=datetime(2026, 1, 1),
            _step_count=0, _resolve_service_proxy=proxy, _await_ref=await_ref,
            _env_router=SimpleNamespace(set_current_time=lambda t: None, step=env_step),
            to_workspace=persistence)
        with patch.object(module, "step_agent_batch", SimpleNamespace(remote=lambda ids, *a: batch(ids))):
            with self.assertRaisesRegex(RuntimeError, "agent failed"):
                await AgentSociety.step(fake, 60)
        self.assertTrue((self.root / STOP_FILE).exists())
        closing = asyncio.create_task(drain.close())
        await asyncio.sleep(0)
        self.assertFalse(closing.done())
        self.release.set()
        await closing
        self.assertEqual(advanced, [])
        self.assertEqual(fake._step_count, 0)
        self.assertEqual(self.sent, 1)
        self.assertEqual([r["event"] for r in load_model_events(self.root)],
                         ["request_started", "request_finished"])

    async def test_cancel_drain_keeps_original_request_deadline(self):
        with patch("policy_sim.client.REQUEST_TIMEOUT", 0.01):
            task = asyncio.create_task(self.request())
            await self.ready.wait()
            task.cancel()
            with self.assertRaises(ModelClientError):
                await asyncio.wait_for(task, 1)
        rows = load_model_events(self.root)
        self.assertEqual([r["event"] for r in rows], ["request_started", "request_failed"])
        self.assertNotIn("usage", rows[-1])
        self.assertEqual(self.sent, 1)

    async def test_drain_timeout_is_explicit(self):
        drain = TaskDrain(self.root, timeout=0.001)
        pending = asyncio.create_task(drain.wait(self.release.wait(), lambda result: None))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(RuntimeError, "evidence may be incomplete"):
            await drain.close()
        self.release.set()
        await pending
