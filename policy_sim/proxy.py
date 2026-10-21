"""A loopback-only, allowlisted API proxy with a persistent smoke-test budget."""

import hashlib
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid
import errno
import socket
import ssl
from http.client import HTTPSConnection
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen, build_opener, ProxyHandler, HTTPSHandler


MODEL = "deepseek-v4-flash"
UPSTREAM = "https://llmapi.fiblab.net/v1/chat/completions"
MAX_REQUESTS = 16
MAX_RMB = 0.5
MAX_OUTPUT = 4096
MAX_BODY = 96 * 1024
INPUT_RATE = 1.2
OUTPUT_RATE = 2.4
LOCAL_KEY = "smoke-loopback-only"

# At most 33 seconds of connection setup, then the existing 600-second I/O
# timeout. No HTTP bytes are sent until a TCP/TLS connection succeeds.
CONNECT_ATTEMPTS = 3
CONNECT_TIMEOUT_SECONDS = 10
CONNECT_BACKOFF_SECONDS = (1, 2)


def transport_error_fields(error):
    """Keep diagnostic types/codes, never exception text or request headers."""
    cause = getattr(error, "reason", error)
    fields = {"exception_type": type(error).__name__, "cause_type": type(cause).__name__}
    code = getattr(cause, "errno", None)
    if isinstance(code, int):
        fields["errno"] = code
    return fields


class _ConnectingHTTPSConnection(HTTPSConnection):
    def __init__(self, *args, record_event, **kwargs):
        super().__init__(*args, **kwargs)
        self.record_event = record_event
        self._send_recorded = False

    def connect(self):
        io_timeout = self.timeout
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            self.timeout = min(io_timeout, CONNECT_TIMEOUT_SECONDS)
            self.record_event({"phase": "connect_or_tls", "attempt": attempt, "status": "started"})
            try:
                super().connect()
            except OSError as error:
                if self.sock is not None:
                    self.sock.close()
                    self.sock = None
                self.timeout = io_timeout
                transient = (not isinstance(error, ssl.SSLError) and (
                    isinstance(error, (TimeoutError, ConnectionError)) or
                    error.errno in {errno.ECONNREFUSED, errno.ECONNRESET, errno.ETIMEDOUT,
                                    errno.ENETUNREACH, errno.EHOSTUNREACH, socket.EAI_AGAIN}))
                retry = transient and attempt < CONNECT_ATTEMPTS
                self.record_event({"phase": "connect_or_tls", "attempt": attempt,
                    "status": "failed", "request_sent": False, "retry": retry,
                    **transport_error_fields(error)})
                if not retry:
                    raise
                time.sleep(CONNECT_BACKOFF_SECONDS[attempt - 1])
            else:
                self.timeout = io_timeout
                self.sock.settimeout(io_timeout)
                self.record_event({"phase": "connect_or_tls", "attempt": attempt, "status": "connected"})
                return

    def send(self, data):
        if self.sock is None:
            self.connect()
        if not self._send_recorded:
            self.record_event({"phase": "http_send", "status": "started"})
            self._send_recorded = True
        # Never retry after this boundary: a write/read failure can leave an
        # upstream completion with unknown usage, even if no response arrived.
        return super().send(data)


class _DirectRetryHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        def connection(*args, **kwargs):
            return _ConnectingHTTPSConnection(*args,
                record_event=getattr(request, "transport_record", lambda event: None), **kwargs)
        return self.do_open(connection, request, context=self._context)


class BudgetError(ValueError):
    def __init__(self, message, *, error_type="invalid_request", request_bytes=None,
                 max_body_bytes=None):
        super().__init__(message)
        self.error_type = error_type
        self.request_bytes = request_bytes
        self.max_body_bytes = max_body_bytes


class ControllerLockError(BudgetError):
    pass


class ControllerLock:
    """Nonblocking OS lock shared by every controller of one ledger."""

    def __init__(self, ledger_path):
        self.path = Path(str(Path(ledger_path).resolve()) + ".lock")
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise ControllerLockError("Another controller owns this budget ledger") from error
        self.handle = handle
        return self

    def __exit__(self, *args):
        if self.handle is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            finally:
                self.handle.close()
                self.handle = None


class BudgetLedger:
    def __init__(self, path, max_requests=MAX_REQUESTS, max_rmb=MAX_RMB, *,
                 input_rate=INPUT_RATE, output_rate=OUTPUT_RATE, price_version=None,
                 request_metadata=None, max_body_bytes=MAX_BODY, max_output_tokens=MAX_OUTPUT,
                 enforce_limits=True, model=MODEL):
        self.path = Path(path)
        if model not in (MODEL, "deepseek-flash"):
            raise BudgetError("Unsupported approved model")
        self.model = model
        if type(max_output_tokens) is not int or max_output_tokens not in (4096, 16384):
            raise BudgetError("Output capacity must be an explicitly supported 4096 or 16384 tokens")
        self.max_output_tokens = max_output_tokens
        self.max_body_bytes = self._valid_max_body_bytes(max_body_bytes)
        self.max_requests = max_requests
        self.max_rmb = max_rmb
        if type(enforce_limits) is not bool:
            raise BudgetError("enforce_limits must be explicit boolean")
        if not enforce_limits and (max_requests is not None or max_rmb is not None):
            raise BudgetError("Record-only accounting uses null request and money caps")
        if enforce_limits and (max_requests is None or max_rmb is None):
            raise BudgetError("Enforced accounting requires request and money caps")
        self.enforce_limits = enforce_limits
        self.input_rate = self._valid_rate(input_rate)
        self.output_rate = self._valid_rate(output_rate)
        self.price_version = self._valid_price_version(price_version)
        self.request_metadata = self._valid_metadata(request_metadata)
        self.lock = threading.Lock()
        self.records_validator = None
        self.reload()

    @staticmethod
    def _valid_max_body_bytes(value):
        if type(value) is not int or not 1 <= value <= 1024 * 1024:
            raise BudgetError("Request capacity must be a positive integer at most 1 MiB")
        return value

    @staticmethod
    def _valid_rate(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise BudgetError("Rates must be finite nonnegative numbers")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise BudgetError("Rates must be finite nonnegative numbers")
        return value

    @staticmethod
    def _valid_price_version(value):
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 200):
            raise BudgetError("Price version must be a short nonempty string or None")
        return value

    @staticmethod
    def _valid_metadata(value):
        if value is None:
            return {}
        if not isinstance(value, dict) or set(value) - {"authorization_id", "price_evidence_sha256"}:
            raise BudgetError("Only authorization_id and price_evidence_sha256 metadata are allowed")
        value = dict(value)
        for key, item in value.items():
            if not isinstance(item, str) or not item.strip() or len(item) > 200:
                raise BudgetError("Request metadata must contain short nonempty strings")
            if key == "price_evidence_sha256" and (len(item) != 64 or any(c not in "0123456789abcdef" for c in item)):
                raise BudgetError("Price evidence digest must be lowercase SHA256")
        return value

    def reload(self):
        self.records = json.loads(self.path.read_text()) if self.path.exists() else []
        if not isinstance(self.records, list):
            raise BudgetError("Budget ledger must be a list")
        for index, row in enumerate(self.records):
            if not isinstance(row, dict) or row.get("request") != index + 1 or "status" not in row:
                raise BudgetError("Invalid budget ledger record")
            for field in ("reserved_rmb", "estimated_rmb"):
                value = row.get(field)
                if field == "estimated_rmb" and field not in row:
                    continue
                if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                    raise BudgetError("Invalid budget ledger amount")
            if "input_rate" in row or "output_rate" in row:
                self._valid_rate(row.get("input_rate"))
                self._valid_rate(row.get("output_rate"))
                self._valid_price_version(row.get("price_version"))
        if self.records_validator:
            self.records_validator(self.records)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as output:
            output.write(json.dumps(self.records, indent=2))
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(self.path)

    def _accounted(self):
        return sum(row.get("estimated_rmb", row["reserved_rmb"]) for row in self.records)

    def reserve(self, payload):
        if not isinstance(payload, dict):
            raise BudgetError("Request must be a JSON object")
        payload = dict(payload)
        if payload.get("model") != self.model:
            raise BudgetError("Only the approved low-cost smoke-test model is allowed")
        if payload.get("stream"):
            raise BudgetError("Streaming is disabled for auditable usage accounting")
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise BudgetError("Nonempty messages are required")
        if any(not isinstance(message, dict) or not isinstance(message.get("content", ""), (str, type(None))) for message in messages):
            raise BudgetError("Only text messages are allowed")
        requested = payload.pop("max_completion_tokens", payload.get("max_tokens", MAX_OUTPUT))
        if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
            raise BudgetError("A positive output token limit is required")
        payload["max_tokens"] = min(requested, self.max_output_tokens)
        payload["stream"] = False
        payload["n"] = 1
        body = json.dumps(payload, ensure_ascii=False, sort_keys=self.max_output_tokens == 16384).encode("utf-8")
        if len(body) > self.max_body_bytes:
            raise BudgetError("Request is too large for this smoke test",
                              error_type="request_too_large", request_bytes=len(body),
                              max_body_bytes=self.max_body_bytes)
        # UTF-8 bytes plus padding conservatively reserve input tokens, including tools.
        with self.lock:
            input_rate = self._valid_rate(self.input_rate)
            output_rate = self._valid_rate(self.output_rate)
            price_version = self._valid_price_version(self.price_version)
            metadata = self._valid_metadata(self.request_metadata)
            reservation = ((len(body) + 4096) * input_rate + payload["max_tokens"] * output_rate) / 1_000_000
            if not math.isfinite(reservation):
                raise BudgetError("Rate calculation exceeded finite accounting range")
            if self.enforce_limits and len(self.records) >= self.max_requests:
                raise BudgetError("Smoke-test request limit reached", error_type="budget_exhausted")
            if self.enforce_limits and self._accounted() + reservation > self.max_rmb:
                raise BudgetError("Smoke-test estimated budget limit reached", error_type="budget_exhausted")
            index = len(self.records)
            self.records.append({
                "request": index + 1,
                "started_unix": time.time(),
                "model": self.model,
                "request_sha256": hashlib.sha256(body).hexdigest(),
                "request_bytes": len(body),
                "max_body_bytes": self.max_body_bytes,
                "max_output_tokens": payload["max_tokens"],
                "reserved_rmb": reservation,
                "status": "reserved",
                "input_rate": input_rate,
                "output_rate": output_rate,
                "price_version": price_version,
                **metadata,
            })
            self._save()
        return index, body

    def bind_client_request(self, index, request_id):
        """Persist local provenance before upstream I/O; never modify authorization."""
        if request_id is None:
            return
        try:
            if str(uuid.UUID(request_id)) != request_id:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise BudgetError("Client request id must be a canonical UUID") from None
        with self.lock:
            if "client_request_id" in self.records[index]:
                raise BudgetError("Client request binding is immutable")
            if any(row.get("client_request_id") == request_id for row in self.records):
                raise BudgetError("Client request id was already used")
            self.records[index]["client_request_id"] = request_id
            self._save()

    def record_transport(self, index, event):
        with self.lock:
            row = self.records[index]
            if row.get("status") != "reserved":
                raise BudgetError("Transport event after request settlement")
            row.setdefault("transport_events", []).append({"unix": time.time(), **event})
            self._save()

    def finish(self, index, status, usage=None, error_message=None, finish_reason=None):
        with self.lock:
            row = self.records[index]
            # Legacy records without frozen rates retain the original price;
            # new requests settle at their own reservation-time price.
            input_rate = self._valid_rate(row.get("input_rate", INPUT_RATE))
            output_rate = self._valid_rate(row.get("output_rate", OUTPUT_RATE))
            row["status"] = status
            row["finished_unix"] = time.time()
            if error_message:
                row["error"] = error_message
            if finish_reason:
                row["finish_reason"] = finish_reason
            if isinstance(usage, dict) and type(usage.get("prompt_tokens")) is int and type(usage.get("completion_tokens")) is int:
                prompt = usage["prompt_tokens"]
                completion = usage["completion_tokens"]
                if prompt >= 0 and completion >= 0:
                    row["prompt_tokens"] = prompt
                    row["completion_tokens"] = completion
                    details = usage.get("completion_tokens_details")
                    row["reasoning_tokens"] = details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0
                    estimated = (prompt * input_rate + completion * output_rate) / 1_000_000
                    if not math.isfinite(estimated):
                        raise BudgetError("Usage calculation exceeded finite accounting range")
                    row["estimated_rmb"] = estimated
            self._save()

    def summary(self):
        with self.lock:
            return {
                "requests": len(self.records),
                "max_requests": self.max_requests,
                "max_estimated_rmb": self.max_rmb,
                "accounted_rmb": self._accounted(),
                "prompt_tokens": sum(row.get("prompt_tokens", 0) for row in self.records),
                "completion_tokens": sum(row.get("completion_tokens", 0) for row in self.records),
                "unknown_usage_requests": sum("estimated_rmb" not in row for row in self.records),
                "successful_requests": sum(row["status"] == 200 for row in self.records),
            }


class BudgetProxy:
    def __init__(self, api_key, ledger, *, transport_retries=False, upstream_timeout_seconds=600,
                 native_idempotency=True, native_profiles=None, provider_route=None):
        from .profiles import validate_profile
        from .providers import validate_route
        if (native_idempotency is not True or upstream_timeout_seconds != 600
                or ledger.max_output_tokens != 16384 or not native_profiles):
            raise BudgetError("Current proxy requires explicit profiles, durable UUID deduplication, 600s timeout and 16384 tokens")
        self.native_idempotency = True
        self.native_profiles = [validate_profile(p) for p in native_profiles]
        route = validate_route(provider_route or self.native_profiles[0]["provider_route"])
        if route["model"] != ledger.model:
            raise BudgetError("Upstream model differs from ledger authorization")
        for profile in self.native_profiles:
            if profile["model"] != route["model"] or profile["provider_route"] != route:
                raise BudgetError("Upstream route differs from frozen native profile")
        self.upstream = route["base_url"] + "/chat/completions"
        # A dedicated opener bypasses both environment and macOS proxy discovery.
        # Do not install it globally: other providers retain their existing routing.
        self._upstream_opener = (build_opener(ProxyHandler({}), _DirectRetryHTTPSHandler())
                                 if route["provider"] == "deepseek_official" else None)
        self._idempotency_lock = threading.Lock()
        self._idempotency_path = Path(str(ledger.path) + ".native-requests.json")
        self.upstream_timeout_seconds = upstream_timeout_seconds
        self.transport_retries = transport_retries
        self.api_key = api_key
        self.ledger = ledger
        self.server = None
        self.thread = None
        self.controller_lock = None
        self.fatal_event = threading.Event()
        self.fatal_reason = None
        self.fatal_details = None
        self._fatal_lock = threading.Lock()

    def __enter__(self):
        self.controller_lock = ControllerLock(self.ledger.path)
        self.controller_lock.__enter__()
        try:
            self.ledger.reload()
            return self._start()
        except BaseException:
            if self.server is not None:
                self.server.server_close()
            self.controller_lock.__exit__()
            raise

    def _open_upstream(self, request, index=None):
        if index is not None:
            request.transport_record = lambda event: self.ledger.record_transport(index, event)
        if self._upstream_opener is not None:
            return self._upstream_opener.open(request, timeout=self.upstream_timeout_seconds)
        return urlopen(request, timeout=self.upstream_timeout_seconds)

    def _native_claim(self, request_id, raw, purpose, digest):
        """Durably claim before reservation. A crash leaves a non-retryable pending ID."""
        fingerprint = hashlib.sha256(raw + b"\0" + purpose.encode() + b"\0" + digest.encode()).hexdigest()
        with self._idempotency_lock:
            records = json.loads(self._idempotency_path.read_text()) if self._idempotency_path.exists() else {}
            prior = records.get(request_id)
            if prior is not None:
                if prior["fingerprint"] != fingerprint:
                    raise BudgetError("Native request UUID reused with conflicting body or profile", error_type="idempotency_conflict")
                if "response_body" not in prior:
                    raise BudgetError("Native request in flight or outcome unknown; upstream resend forbidden", error_type="idempotency_unknown")
                return prior["response_status"], base64.b64decode(prior["response_body"])
            records[request_id] = {"fingerprint": fingerprint, "state": "pending"}
            self._native_save(records)
        return None

    def _native_save(self, records):
        self._idempotency_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._idempotency_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as output:
            json.dump(records, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(self._idempotency_path)

    def _native_complete(self, request_id, status, body):
        with self._idempotency_lock:
            records = json.loads(self._idempotency_path.read_text())
            records[request_id].update(state="completed", response_status=status,
                                      response_body=base64.b64encode(body).decode("ascii"))
            self._native_save(records)

    def _start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, status, body):
                if getattr(self, "native_claimed_id", None):
                    owner._native_complete(self.native_claimed_id, status, body)
                    self.native_claimed_id = None
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def reject(self, status, message, *, error_type="invalid_request",
                       retryable=False, request_bytes=None, max_body_bytes=None, settled_index=None):
                message = message.replace(owner.api_key, "<redacted>") if owner.api_key else message
                details = {"error_type": error_type, "http_status": status, "retryable": retryable}
                if request_bytes is not None:
                    details["request_bytes"] = request_bytes
                if max_body_bytes is not None:
                    details["max_body_bytes"] = max_body_bytes
                transient = (error_type == "transport_error" or
                    error_type == "upstream_http_error" and status in {429, 500, 502, 503, 504})
                completed = False
                if owner.transport_retries and settled_index is not None:
                    with owner.ledger.lock:
                        row = dict(owner.ledger.records[settled_index])
                    completed = row.get("status") != "reserved" and "finished_unix" in row
                    if completed:
                        proof = {"request_id": row.get("client_request_id"),
                            "request_sha256": row.get("request_sha256"), "http_status": status,
                            "error_type": error_type, "finished": True,
                            "usage": {k: row[k] for k in ("prompt_tokens", "completion_tokens") if k in row}}
                        details["completion"] = proof
                if not (owner.transport_retries and completed and transient and retryable):
                    with owner._fatal_lock:
                        if owner.fatal_details is None:
                            owner.fatal_reason = message
                            owner.fatal_details = {k: v for k, v in details.items() if not k.startswith("completion")}
                        owner.fatal_event.set()
                self.respond(status, json.dumps({"error": {"message": message,
                             "type": "smoke_test_guard", **details}}).encode())

            def settle(self, index, status, usage=None, **fields):
                try:
                    owner.ledger.finish(index, status, usage, **fields)
                    return True
                except Exception:
                    self.reject(502, "Budget settlement evidence failed", error_type="evidence_or_authorization")
                    return False

            def do_POST(self):
                if owner.fatal_event.is_set() and not owner.native_idempotency:
                    details = dict(owner.fatal_details or {})
                    status = details.pop("http_status", 400)
                    return self.reject(status, owner.fatal_reason or "Controller stopped", **details)
                if self.path != "/v1/chat/completions":
                    return self.reject(404, "Only chat completions are enabled")
                if self.headers.get("Authorization") != f"Bearer {LOCAL_KEY}":
                    return self.reject(401, "Local test authorization is required",
                                       error_type="authentication_failed")
                length = None
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 1:
                        raise BudgetError("Invalid request size")
                    if length > owner.ledger.max_body_bytes:
                        raise BudgetError("Request is too large for this smoke test",
                                          error_type="request_too_large", request_bytes=length,
                                          max_body_bytes=owner.ledger.max_body_bytes)
                    wire_body = self.rfile.read(length)
                    payload = json.loads(wire_body)
                    request_id = self.headers.get("X-Client-Request-Id")
                    if request_id is not None:
                        try:
                            if str(uuid.UUID(request_id)) != request_id:
                                raise ValueError
                        except (ValueError, TypeError, AttributeError):
                            raise BudgetError("Client request id must be a canonical UUID") from None
                    if owner.native_idempotency:
                        from .profiles import validate_payload
                        purpose = self.headers.get("X-Native-Purpose")
                        profile_digest = self.headers.get("X-Native-Profile-Sha256")
                        if request_id is None:
                            raise BudgetError("Native requests require a UUID")
                        validate_payload(payload, owner.native_profiles, purpose, profile_digest)
                        replay = owner._native_claim(request_id, wire_body, purpose, profile_digest)
                        if replay is not None:
                            return self.respond(*replay)
                        self.native_claimed_id = request_id
                        if owner.fatal_event.is_set():
                            return self.reject(400, "Native controller stopped", error_type="controller_stopped")
                    index, body = owner.ledger.reserve(payload)
                    owner.ledger.bind_client_request(index, request_id)
                except BudgetError as error:
                    status = 413 if error.error_type == "request_too_large" else 409 if error.error_type.startswith("idempotency_") else 400
                    return self.reject(status, str(error), error_type=error.error_type,
                                       request_bytes=error.request_bytes if error.request_bytes is not None else length,
                                       max_body_bytes=owner.ledger.max_body_bytes)
                except (ValueError, TypeError):
                    return self.reject(400, "Invalid JSON request", request_bytes=length,
                                       max_body_bytes=owner.ledger.max_body_bytes)
                try:
                    request = Request(owner.upstream, data=body, headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {owner.api_key}",
                    })
                    with owner._open_upstream(request, index) as response:
                        owner.ledger.record_transport(index, {"phase": "response_headers", "status": "received", "http_status": response.status})
                        raw = response.read(2 * 1024 * 1024)
                        status = response.status
                    decoded = json.loads(raw)
                    choices = decoded.get("choices") or [{}]
                    if not self.settle(index, status, decoded.get("usage"), finish_reason=choices[0].get("finish_reason")):
                        return
                    self.respond(status, raw)
                except HTTPError as error:
                    # Never echo upstream error bodies: they may contain credentials.
                    detail = f"Upstream returned HTTP {error.code}"
                    usage = None
                    try:
                        decoded_error = json.loads(error.read(8192))
                        usage = decoded_error.get("usage") if isinstance(decoded_error, dict) else None
                    except Exception:
                        pass
                    if not self.settle(index, error.code, usage, error_message=detail):
                        return
                    self.reject(error.code, detail,
                                error_type="authentication_failed" if error.code in (401, 403) else "upstream_http_error",
                                retryable=error.code in {429, 500, 502, 503, 504}, settled_index=index,
                                request_bytes=len(body), max_body_bytes=owner.ledger.max_body_bytes)
                except (URLError, TimeoutError, ConnectionError) as error:
                    owner.ledger.record_transport(index, {"phase": "transport_terminal", "status": "failed", **transport_error_fields(error)})
                    if not self.settle(index, "transport_or_decode_error"):
                        return
                    self.reject(502, "Upstream transport or decoding failed; reservation retained",
                                error_type="transport_error", retryable=True, settled_index=index,
                                request_bytes=len(body), max_body_bytes=owner.ledger.max_body_bytes)

                except Exception:
                    if not self.settle(index, "evidence_error"):
                        return
                    self.reject(502, "Upstream evidence or settlement failed", error_type="evidence_or_authorization")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __exit__(self, *args):
        try:
            self.server.shutdown()
            self.server.server_close()  # Join handlers before releasing ledger ownership.
            self.thread.join(timeout=5)
        finally:
            self.api_key = None
            self.controller_lock.__exit__()
