"""No-network proof of durable UUID claims and legacy preservation."""
import json
from pathlib import Path
import tempfile
import unittest
from policy_sim.proxy import BudgetLedger, BudgetProxy, BudgetError
from policy_sim.profiles import make_profile, settings_for_purpose, validate_payload, profile_digest


class ProxyTests(unittest.TestCase):
    def test_durable_replay_conflict_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = BudgetLedger(Path(tmp)/"budget.json", max_output_tokens=16384, model="deepseek-flash")
            profile = make_profile()
            proxy = BudgetProxy("not-a-key", ledger, native_idempotency=True,
                                native_profiles=[profile], upstream_timeout_seconds=600)
            self.assertIsNone(proxy._native_claim("one", b"body", "router", "digest"))
            with self.assertRaisesRegex(BudgetError, "unknown"):
                proxy._native_claim("one", b"body", "router", "digest")
            proxy._native_complete("one", 200, b'{"raw": true}')
            reopened = BudgetProxy("not-a-key", ledger, native_idempotency=True,
                                native_profiles=[profile], upstream_timeout_seconds=600)
            self.assertEqual(reopened._native_claim("one", b"body", "router", "digest"), (200, b'{"raw": true}'))
            with self.assertRaisesRegex(BudgetError, "conflicting"):
                reopened._native_claim("one", b"different", "router", "digest")
            self.assertEqual(ledger.records, [])

    def test_profile_purpose_binding(self):
        profile = make_profile()
        payload = {**settings_for_purpose(profile, "agent_decision"), "messages": [{"role":"user","content":"hello"}]}
        validate_payload(payload, [profile], "agent_decision", profile_digest(profile))
        with self.assertRaises(ValueError):
            validate_payload(payload, [profile], "router", profile_digest(profile))
        with self.assertRaises(ValueError):
            validate_payload(payload, [profile], "agent_decision", "changed")

    def test_official_client_proxy_wire_and_duplicate_http(self):
        self._official_client_wire("disabled")

    def test_official_deepseek_route_wire_and_duplicate_http(self):
        self._official_client_wire("disabled", provider="deepseek_official")

    def _official_client_wire(self, thinking, provider=None):
        import asyncio
        import os
        import subprocess
        import sys
        from unittest.mock import patch
        from urllib.request import Request, urlopen
        from policy_sim.client import ModelClient
        import importlib.util
        if importlib.util.find_spec("agentsociety2") is None:
            self.skipTest("Official AgentSociety2 environment unavailable")
        if os.environ.get("NATIVE_WIRE_TEST_CHILD") != "1":
            # Timeout is read at framework import. Isolate this real-SDK check
            # from earlier legacy tests rather than patch installed globals.
            env = {**os.environ, "NATIVE_WIRE_TEST_CHILD": "1", "AGENTSOCIETY_LLM_REQUEST_TIMEOUT": "660",
                   "LITELLM_LOCAL_MODEL_COST_MAP": "True"}
            result = subprocess.run([sys.executable, "-B", "-m", "unittest",
                "tests.test_sim_proxy.ProxyTests." + self._testMethodName],
                cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        os.environ.setdefault("AGENTSOCIETY_LLM_API_KEY", "offline")
        os.environ.setdefault("AGENTSOCIETY_LLM_API_BASE", "http://127.0.0.1:1/v1")
        os.environ["AGENTSOCIETY_LLM_REQUEST_TIMEOUT"] = "660"
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, *args):
                return json.dumps({"id":"offline", "object":"chat.completion", "created":0,
                    "model":"deepseek-v4-flash", "choices":[{"index":0,"finish_reason":"stop",
                    "message":{"role":"assistant","content":"ok"}}],
                    "usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            profile = make_profile(provider=provider)
            ledger = BudgetLedger(Path(tmp)/"budget.json", max_output_tokens=16384, model=profile["model"])
            captured = []
            from policy_sim.profiles import validate_payload as real_validate
            def capture(payload, *args):
                captured.append(payload.copy())
                return real_validate(payload, *args)
            with patch("policy_sim.proxy.urlopen", return_value=Response()) as upstream, patch("policy_sim.profiles.validate_payload", side_effect=capture), patch("policy_sim.proxy.build_opener") as opener_factory:
                opener_factory.return_value.open = upstream
                with BudgetProxy("fake-offline", ledger, native_idempotency=True,
                        native_profiles=[profile], upstream_timeout_seconds=600, provider_route=profile.get("provider_route")) as proxy:
                    client = ModelClient(proxy.base_url, Path(tmp)/"model_requests.jsonl", profile=profile,
                        context={"run_id":"offline", "round":1,"actor_id":1,"purpose":"agent_decision"})
                    claims = []
                    original_claim = proxy._native_claim
                    def claim(*args):
                        claims.append(args)
                        return original_claim(*args)
                    proxy._native_claim = claim
                    tool = {"type": "function", "function": {"name": "finish", "description": "offline",
                            "parameters": {"type": "object", "properties": {"answer": {"type": "string"}},
                                           "required": ["answer"], "additionalProperties": False}}}
                    response = asyncio.run(client.call(messages=[{"role":"user","content":"hello"}],
                                                        tools=[tool], tool_choice="auto"))
                    self.assertEqual(captured[0]["model"], profile["model"])
                    expected_url = "https://api.deepseek.com/v1/chat/completions"
                    self.assertEqual(upstream.call_args.args[0].full_url, expected_url)
                    self.assertEqual(ledger.records[0]["model"], profile["model"])
                    self.assertEqual(captured[0]["tools"], [tool])
                    self.assertEqual(captured[0]["tool_choice"], "auto")
                    self.assertEqual(captured[0]["thinking"], {"type": thinking})
                    if thinking == "enabled":
                        self.assertEqual(captured[0]["reasoning_effort"], "high")
                    else:
                        self.assertNotIn("reasoning_effort", captured[0])
                    self.assertNotIn("allowed_openai_params", captured[0])
                    self.assertEqual(response.choices[0].message.content, "ok")
                    self.assertEqual(upstream.call_count, 1)
                    self.assertEqual(len(ledger.records), 1)
                    terminal = json.loads((Path(tmp) / 'model_requests.jsonl').read_text().splitlines()[-1])
                    self.assertEqual(terminal['usage']['prompt_tokens'], 2)
                    self.assertEqual(terminal['usage']['completion_tokens'], 3)
                    self.assertEqual(terminal['usage_source'], 'provider_response')
                    request_id, wire, purpose, digest = claims[0]
                    duplicate = Request(proxy.base_url + "/chat/completions", data=wire,
                        headers={"Authorization":"Bearer smoke-loopback-only", "Content-Type":"application/json",
                                 "X-Client-Request-Id": request_id, "X-Native-Purpose":purpose,
                                 "X-Native-Profile-Sha256":digest})
                    with urlopen(duplicate) as result:
                        self.assertEqual(json.load(result)["choices"][0]["message"]["content"], "ok")
                    self.assertEqual(upstream.call_count, 1)
                    self.assertEqual(len(ledger.records), 1)
                    cached = json.loads(proxy._idempotency_path.read_text())[response.request_id]
                    self.assertEqual(cached["response_status"], 200)
                    self.assertEqual(ledger.records[0]["client_request_id"], response.request_id)
                    from urllib.error import HTTPError
                    from io import BytesIO
                    from policy_sim.client import ModelClientError
                    upstream.side_effect = HTTPError("https://upstream.invalid", 500, "mock", {}, BytesIO(b'{}'))
                    with self.assertRaises(ModelClientError):
                        asyncio.run(client.call(messages=[{"role":"user","content":"failure"}]))
                    self.assertEqual(upstream.call_count, 2)  # one paid send for each logical call
                    self.assertEqual(len(ledger.records), 2)
                    self.assertEqual(ledger.records[-1]["status"], 500)
