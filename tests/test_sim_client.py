"""Model accounting, failure and immutable-evidence boundaries (no network)."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from policy_sim.client import ModelClient, ModelClientError
from policy_sim.evidence import load_model_events
from policy_sim.profiles import make_profile, validate_profile


class Response(SimpleNamespace):
    def model_dump(self, **kwargs):
        return {"id": self.id, "usage": self.usage,
                "choices": [{"finish_reason": self.choices[0].finish_reason,
                             "message": {"content": "memory"}}]}


class OfficialStub:
    def __init__(self):
        self.options = []
        self.input = self.output = self.calls = 0
        self.finish_reason = "stop"
        self.fail = False

    async def call(self, **kwargs):
        self.options.append(kwargs)
        value = int(kwargs["messages"][0]["content"])
        await asyncio.sleep(0.002 if value == 2 else 0)
        if self.fail:
            raise RuntimeError("sensitive upstream error text")
        self.input += value
        self.output += value + 1
        self.calls += 1
        return Response(id="provider-" + str(value),
            usage={"prompt_tokens": value, "completion_tokens": value + 1},
            choices=[SimpleNamespace(finish_reason=self.finish_reason,
                                     message=SimpleNamespace(content="memory", tool_calls=None))])

    def snapshot_token_stats(self):
        return {"model": {"input": self.input, "output": self.output, "calls": self.calls}}

    def take_token_stats(self):
        result = self.snapshot_token_stats()
        self.input = self.output = self.calls = 0
        return result


class ModelBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stub = OfficialStub()
        self.client = ModelClient("http://127.0.0.1:1/v1", self.root / "model_requests.jsonl",
            profile=make_profile(), client=self.stub,
            context={"run_id": "test", "round": 0})

    def test_concurrent_usage_is_bound_to_response_not_shared_counter_difference(self):
        async def run():
            return await asyncio.gather(*[
                self.client.for_context("memory", actor_id=actor).call(
                    messages=[{"role": "user", "content": str(value)}])
                for actor, value in ((1, 2), (2, 17))])
        responses = asyncio.run(run())
        rows = load_model_events(self.root)
        ends = {r["request_id"]: r for r in rows if r["event"] == "request_finished"}
        for response in responses:
            self.assertEqual(ends[response.request_id]["usage"], response.usage)
        self.assertEqual(sum(row["usage"]["prompt_tokens"] for row in ends.values()), 19)
        self.assertEqual(self.stub.calls, 2)
        self.assertEqual(len({r["request_id"] for r in rows}), 2)
        physical = [json.loads(x) for x in (self.root / "model_requests.jsonl").read_text().splitlines()]
        self.assertTrue(all("messages" not in x and "raw_response" not in x for x in physical))
        self.assertEqual(len(list((self.root / "model_payloads").glob("*.request.json"))), 2)
        self.assertEqual(len(list((self.root / "model_payloads").glob("*.response.json"))), 2)

    def test_actor_truncation_is_settled_and_returned_for_official_correction(self):
        self.stub.finish_reason = "length"
        response = asyncio.run(self.client.for_context("agent_decision", actor_id=1).call(
            messages=[{"role": "user", "content": "2"}], tools=[]))
        self.assertEqual(response.choices[0].finish_reason, "length")
        self.client.raise_if_failed()
        self.assertEqual(load_model_events(self.root)[-1]["response_schema_error"], "output_truncated")
        self.assertEqual(self.stub.options[0]["max_retries"], 1)
        self.assertEqual(self.stub.options[0]["extra_headers"]["X-Client-Request-Id"], response.request_id)

    def test_routing_tools_and_text_completion_share_uuid_accounting(self):
        from uuid import uuid4
        from litellm import ModelResponse
        replies = [ModelResponse(choices=[{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "tool_calls": [{"id": "route", "type": "function",
            "function": {"name": "observe", "arguments": "{}"}}]}}],
            usage={"prompt_tokens": 7, "completion_tokens": 3}),
            ModelResponse(choices=[{"finish_reason": "stop", "message": {"role": "assistant", "content": "Done"}}],
            usage={"prompt_tokens": 9, "completion_tokens": 2})]
        async def call(**kwargs):
            self.stub.options.append(kwargs)
            return replies.pop(0)
        self.stub.call = call
        ask_id = str(uuid4())
        async def run():
            for _ in range(2):
                await self.client.for_context("environment_routing", actor_id=1, ask_id=ask_id).call(
                    messages=[{"role": "user", "content": "route"}],
                    tools=[{"type": "function", "function": {"name": "observe", "parameters": {"type": "object"}}}],
                    tool_choice="auto")
        asyncio.run(run())
        ends = [r for r in load_model_events(self.root) if r["event"] == "request_finished"]
        self.assertEqual(len({r["request_id"] for r in ends}), 2)
        self.assertTrue(all(r["purpose"] == "environment_routing" and r["ask_id"] == ask_id for r in ends))
        self.assertEqual(sum(r["usage"]["prompt_tokens"] + r["usage"]["completion_tokens"] for r in ends), 21)
        self.assertTrue(all(o["extra_headers"]["X-Native-Purpose"] == "environment_routing" for o in self.stub.options))

    def test_service_truncation_and_transport_failures_are_classified(self):
        self.stub.finish_reason = "length"
        with self.assertRaises(ModelClientError) as caught:
            asyncio.run(self.client.for_context("memory", actor_id=1).call(
                messages=[{"role": "user", "content": "2"}]))
        self.assertEqual(caught.exception.error_type, "invalid_service_response")
        self.assertEqual(load_model_events(self.root)[-1]["usage"]["prompt_tokens"], 2)
        with self.assertRaises(ModelClientError):
            self.client.raise_if_failed()

    def test_payload_tampering_is_rejected(self):
        asyncio.run(self.client.for_context("memory", actor_id=1).call(
            messages=[{"role": "user", "content": "2"}]))
        path = next((self.root / "model_payloads").glob("*.response.json"))
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            load_model_events(self.root)

    def test_oversized_request_is_preserved_and_never_sent(self):
        with self.assertRaises(ModelClientError) as caught:
            asyncio.run(self.client.for_context('agent_decision', actor_id=1).call(
                messages=[{'role': 'user', 'content': '汉字' * 50000}], tools=[]))
        self.assertEqual(caught.exception.error_type, 'request_context_too_large_before_send')
        self.assertEqual(self.stub.options, [])
        rows = load_model_events(self.root)
        self.assertEqual([r['event'] for r in rows], ['request_started', 'request_failed'])
        self.assertNotIn('usage', rows[-1])

    def test_old_or_mutated_profiles_and_unowned_upstream_are_rejected(self):
        value = make_profile()
        value["schema_version"] = "native-request-profile-2"
        with self.assertRaises(ValueError):
            validate_profile(value)
        with self.assertRaises(ValueError):
            ModelClient("https://api.deepseek.com/v1", client=self.stub)

    def test_exception_does_not_leak_upstream_text(self):
        self.stub.fail = True
        with self.assertRaises(ModelClientError):
            asyncio.run(self.client.for_context("memory", actor_id=1).call(
                messages=[{"role": "user", "content": "2"}]))
        self.assertNotIn("sensitive upstream", (self.root / "model_requests.jsonl").read_text())
