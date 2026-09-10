"""A loopback-only, allowlisted API proxy with a persistent smoke-test budget."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


MODEL = "deepseek-v4-flash"
UPSTREAM = "https://llmapi.fiblab.net/v1/chat/completions"
MAX_REQUESTS = 16
MAX_RMB = 0.5
MAX_OUTPUT = 4096
MAX_BODY = 96 * 1024
INPUT_RATE = 1.2
OUTPUT_RATE = 2.4
LOCAL_KEY = "smoke-loopback-only"


class BudgetError(ValueError):
    pass


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
                 request_metadata=None):
        self.path = Path(path)
        self.max_requests = max_requests
        self.max_rmb = max_rmb
        self.input_rate = self._valid_rate(input_rate)
        self.output_rate = self._valid_rate(output_rate)
        self.price_version = self._valid_price_version(price_version)
        self.request_metadata = self._valid_metadata(request_metadata)
        self.lock = threading.Lock()
        self.records_validator = None
        self.reload()

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
        if payload.get("model") != MODEL:
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
        payload["max_tokens"] = min(requested, MAX_OUTPUT)
        payload["stream"] = False
        payload["n"] = 1
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(body) > MAX_BODY:
            raise BudgetError("Request is too large for this smoke test")
        # UTF-8 bytes plus padding conservatively reserve input tokens, including tools.
        with self.lock:
            input_rate = self._valid_rate(self.input_rate)
            output_rate = self._valid_rate(self.output_rate)
            price_version = self._valid_price_version(self.price_version)
            metadata = self._valid_metadata(self.request_metadata)
            reservation = ((len(body) + 4096) * input_rate + payload["max_tokens"] * output_rate) / 1_000_000
            if not math.isfinite(reservation):
                raise BudgetError("Rate calculation exceeded finite accounting range")
            if len(self.records) >= self.max_requests:
                raise BudgetError("Smoke-test request limit reached")
            if self._accounted() + reservation > self.max_rmb:
                raise BudgetError("Smoke-test estimated budget limit reached")
            index = len(self.records)
            self.records.append({
                "request": index + 1,
                "started_unix": time.time(),
                "model": MODEL,
                "request_sha256": hashlib.sha256(body).hexdigest(),
                "request_bytes": len(body),
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
    def __init__(self, api_key, ledger):
        self.api_key = api_key
        self.ledger = ledger
        self.server = None
        self.thread = None
        self.controller_lock = None
        self.fatal_event = threading.Event()
        self.fatal_reason = None

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

    def _start(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, status, body):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def reject(self, status, message):
                message = message.replace(owner.api_key, "<redacted>") if owner.api_key else message
                owner.fatal_reason = owner.fatal_reason or message
                owner.fatal_event.set()
                self.respond(status, json.dumps({"error": {"message": message, "type": "smoke_test_guard", "retryable": False}}).encode())

            def do_POST(self):
                if owner.fatal_event.is_set():
                    return self.reject(400, owner.fatal_reason or "Controller stopped")
                if self.path != "/v1/chat/completions":
                    return self.reject(404, "Only chat completions are enabled")
                if self.headers.get("Authorization") != f"Bearer {LOCAL_KEY}":
                    return self.reject(401, "Local test authorization is required")
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 1 or length > MAX_BODY:
                        raise BudgetError("Invalid request size")
                    payload = json.loads(self.rfile.read(length))
                    index, body = owner.ledger.reserve(payload)
                except (ValueError, TypeError) as error:
                    return self.reject(400, str(error))
                try:
                    request = Request(UPSTREAM, data=body, headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {owner.api_key}",
                    })
                    with urlopen(request, timeout=75) as response:
                        raw = response.read(2 * 1024 * 1024)
                        status = response.status
                    decoded = json.loads(raw)
                    choices = decoded.get("choices") or [{}]
                    owner.ledger.finish(index, status, decoded.get("usage"), finish_reason=choices[0].get("finish_reason"))
                    self.respond(status, raw)
                except HTTPError as error:
                    # Never echo upstream error bodies: they may contain credentials.
                    detail = f"Upstream returned HTTP {error.code}"
                    owner.ledger.finish(index, error.code, error_message=detail)
                    self.reject(error.code, f"Upstream returned HTTP {error.code}: {detail}")
                except Exception:
                    owner.ledger.finish(index, "transport_or_decode_error")
                    self.reject(502, "Upstream transport or decoding failed; reservation retained")

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
