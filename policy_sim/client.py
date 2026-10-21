"""Auditable purpose-bound wrapper around the official LLMClient; no ReAct loop."""
from copy import deepcopy
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import time
from urllib.parse import urlparse
import uuid

from .profiles import (MODEL, PURPOSES, make_profile, validate_profile,
                              profile_digest, settings_for_purpose)


# Shared by driver and Ray workers on the owned local attempt filesystem.
STOP_FILE = "request_stop.json"
REQUEST_TIMEOUT = 660


def stop_requests(run_dir, reason="attempt_failed"):
    path = Path(run_dir) / STOP_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump({"reason": reason, "unix": time.time()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        pass


class ModelClientError(RuntimeError):
    def __init__(self, error_type):
        super().__init__(error_type)
        self.error_type = error_type


def validate_native_response(response):
    """Reject ambiguous native arguments before the official permissive parser.

    This returns feedback only: it neither repairs nor replaces the raw choice.
    The public agent dispatcher refuses that response's tool executions.
    """
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("non-finite JSON number")

    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        elif isinstance(value, list):
            for item in value:
                finite(item)

    try:
        choices = response.choices
        if len(choices) != 1:
            return "输出必须包含一个回答。"
        calls = getattr(choices[0].message, "tool_calls", None)
        if not calls:
            return "请通过提供的工具提交操作，不能用正文代替工具调用。"
        for call in calls:
            if getattr(call, "type", "function") != "function":
                return "工具调用类型必须为 function。"
            function = call.function
            if not isinstance(function.name, str) or not function.name:
                return "工具调用缺少名称。"
            if not isinstance(function.arguments, str):
                return "工具参数必须是一个 JSON 对象。"
            value = json.loads(function.arguments, object_pairs_hook=pairs,
                               parse_constant=constant)
            finite(value)
            if not isinstance(value, dict):
                return "工具参数必须是一个 JSON 对象。"
    except (AttributeError, TypeError, ValueError, IndexError) as error:
        if isinstance(error, ValueError) and str(error) == "duplicate JSON field":
            return "工具参数存在重复字段；请每个字段仅提供一次。"
        return "工具参数不是合法 JSON 对象；不接受重复字段、非有限数值或文本包装。"
    return None


class ModelClient:
    def __init__(self, base_url, request_log=None, *, profile=None, context=None, client=None):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Native client requires the owned loopback budget proxy")
        self.profile = validate_profile(profile if profile is not None else make_profile())
        self.runtime_profile = self.profile
        self.base_url = base_url
        self.model_name = self.profile["model"]
        self.request_log = Path(request_log) if request_log is not None else None
        self.context = dict(context or {})
        if client is None:
            from agentsociety2.config import llm_dispatcher
            if llm_dispatcher._LLM_REQUEST_TIMEOUT != 660:
                raise ValueError("Set AGENTSOCIETY_LLM_REQUEST_TIMEOUT=660 before framework import")
            client = llm_dispatcher.LLMClient(self.model_name, base_url, "smoke-loopback-only")
        self.client = client
        self._shared = {"fatal_error": None, "calls": 0, "last_response_error": None, "counter_source": "provider_response"}

    @property
    def fatal_error(self):
        return self._shared["fatal_error"]

    @property
    def calls(self):
        return self._shared["calls"]

    @property
    def last_response_error(self):
        return self._shared["last_response_error"]

    def raise_if_failed(self):
        if self.fatal_error:
            raise self.fatal_error
        if self.request_log is not None and (self.request_log.parent / STOP_FILE).exists():
            raise ModelClientError("attempt_stopping")

    def for_context(self, context=None, **fields):
        bound = object.__new__(type(self))
        bound.__dict__ = dict(self.__dict__)
        if isinstance(context, str):
            context = {"purpose": context}
        nested = fields.pop("audit_context", None) or {}
        bound.context = {**self.context, **dict(context or {}), **nested, **fields}
        return bound

    with_context = for_context

    def take_token_stats(self):
        return self.client.take_token_stats()

    def snapshot_token_stats(self):
        return self.client.snapshot_token_stats()

    @staticmethod
    def _dump(value):
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    def _audit(self, path, row):
        from .evidence import append_model_event
        append_model_event(path, row)

    async def call(self, model=None, messages=None, stream=False, *, audit_context=None, **kwargs):
        # Per-request provider usage is authoritative; no shared counter subtraction.
        return await self._call(model, messages, stream, audit_context=audit_context, **kwargs)

    async def _call(self, model=None, messages=None, stream=False, *, audit_context=None, **kwargs):
        self.raise_if_failed()
        context = {**self.context, **dict(audit_context or {})}
        path = context.pop("trace_path", self.request_log)
        purpose = context.get("purpose")
        if path is None or purpose not in PURPOSES:
            raise ValueError("Native calls require a durable log and explicit purpose")
        if set(context) - {"purpose", "run_id", "attempt_id", "actor_id", "round", "substep", "ask_id"}:
            raise ValueError("Unknown native audit context field")
        for value in context.values():
            if not (value is None or type(value) is int or isinstance(value, str) and len(value) <= 500):
                raise ValueError("Native audit context requires short scalar identifiers")
        if not context.get("run_id") or type(context.get("round")) is not int:
            raise ValueError("Native calls require run_id and round")
        if purpose in ("agent_decision", "environment_routing", "memory") and type(context.get("actor_id")) is not int:
            raise ValueError("Agent and memory calls require actor_id")
        if stream or (model or self.model_name) != self.model_name:
            raise ValueError("Native calls require frozen model and nonstreaming output")
        # Framework call sites may repeat these defaults; conflicting overrides fail.
        settings = settings_for_purpose(self.profile, purpose)
        for key in list(kwargs):
            if key in settings and kwargs[key] == settings[key]:
                kwargs.pop(key)
        if set(kwargs) - {"tools", "tool_choice"}:
            raise ValueError("Unsupported native per-call override")
        if purpose in ("policy_A", "policy_C", "memory") and kwargs:
            raise ValueError("Memory/material calls cannot use tool calls")
        messages = deepcopy(messages)
        request_id = str(uuid.uuid4())
        digest = profile_digest(self.profile)
        row = {"schema_version": "business-request-audit-1", "request_id": request_id,
               **context, "model": self.model_name, "runtime_profile_sha256": digest,
               "request_settings": settings, "messages": messages, "request_options": deepcopy(kwargs),
               "input_sha256": hashlib.sha256(json.dumps(messages, sort_keys=True,
                    ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()}
        path = Path(path)
        def counter_snapshot():
            return self.snapshot_token_stats() if hasattr(self.client, "snapshot_token_stats") else None
        try:
            self._audit(path, {**row, "event": "request_started", "unix": time.time()})
            from .work import REQUEST_BYTES
            wire_bytes = len(json.dumps({**settings, **kwargs, "messages": messages},
                ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if wire_bytes > REQUEST_BYTES:
                raise ModelClientError("request_context_too_large_before_send")
            options = {k: v for k, v in settings.items() if k != "model"}
            options.update(kwargs)
            options["extra_body"] = {"thinking": options.pop("thinking")}
            if "reasoning_effort" in options:
                # LiteLLM 1.100.1 lacks this gateway model in its OpenAI
                # capability table. Its per-call allowlist preserves the
                # frozen parameter on the wire; never drop or rewrite it.
                options["allowed_openai_params"] = ["reasoning_effort"]
            options.update(cache={"no-cache": True, "no-store": True},
                           extra_headers={"X-Client-Request-Id": request_id,
                               "X-Native-Purpose": purpose, "X-Native-Profile-Sha256": digest})
            # Cancellation must not discard an already paid response. The
            # original request deadline remains fixed during drain; never retry.
            self.raise_if_failed()
            async def dispatch():
                self.raise_if_failed()
                return await self.client.call(model=self.model_name, messages=messages,
                    stream=False, max_retries=1, **options)
            pending = asyncio.create_task(asyncio.wait_for(dispatch(), timeout=REQUEST_TIMEOUT))
            cancelled = False
            while True:
                try:
                    response = await asyncio.shield(pending)
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    stop_requests(path.parent, "request_cancelled")
                    if pending.done():
                        # A transport may itself cancel. Preserve a terminal
                        # event even when no provider response is available.
                        response = pending.result()
                        break
            raw = self._dump(response)
            self._shared["calls"] += 1
            if cancelled:
                raise asyncio.CancelledError()
            choices = response.choices
            response_error = validate_native_response(response) if purpose == "agent_decision" else None
            if purpose == "agent_decision" and len(choices) == 1 and choices[0].finish_reason == "length":
                response_error = "output_truncated"
            if purpose not in ("agent_decision", "environment_routing") and (len(choices) != 1 or choices[0].finish_reason != "stop"
                    or not isinstance(choices[0].message.content, str) or not choices[0].message.content.strip()):
                raise ModelClientError("invalid_service_response")
            self._shared["last_response_error"] = response_error
            self._audit(path, {**row, "event": "request_finished", "unix": time.time(),
                              "raw_response": raw, "usage": raw.get("usage"),
                              "response_schema_error": response_error,
                              "usage_source": "provider_response", "official_token_snapshot": counter_snapshot()})
            response.request_id = request_id
            return response
        except asyncio.CancelledError:
            error = ModelClientError("request_cancelled")
            self._shared["fatal_error"] = error
            stop_requests(path.parent, error.error_type)
            self._audit(path, {**row, "event": "request_failed", "unix": time.time(),
                "error_type": error.error_type, "official_token_snapshot": counter_snapshot(),
                **({"raw_response": raw, "usage": raw.get("usage")} if "raw" in locals() else {})})
            raise
        except Exception as exc:
            error = exc if isinstance(exc, ModelClientError) else ModelClientError("model_dispatch_or_evidence_error")
            self._shared["fatal_error"] = error
            stop_requests(path.parent, error.error_type)
            # Exception text can contain request headers. Only a classified error is persisted.
            self._audit(path, {**row, "event": "request_failed", "unix": time.time(), "error_type": error.error_type,
                "official_token_snapshot": counter_snapshot(),
                **({"raw_response": raw, "usage": raw.get("usage")} if "raw" in locals() else {})})
            raise error from None

    async def json(self, messages, *, audit_context=None):
        response = await self.call(messages=messages, audit_context=audit_context)
        value = json.loads(response.choices[0].message.content)
        if not isinstance(value, dict):
            raise ValueError("Material response must be a strict JSON object")
        return value
