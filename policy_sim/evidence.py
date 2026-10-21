"""Immutable model payloads and small append-only event references."""
import hashlib
import json
import os
from pathlib import Path
import uuid

from .io import append_jsonl, canonical

PAYLOAD_FIELDS = ("messages", "request_settings", "request_options")


def _store(directory, request_id, kind, value):
    if str(uuid.UUID(request_id)) != request_id:
        raise ValueError("Model evidence requires canonical request UUID")
    relative = Path("model_payloads") / (request_id + "." + kind + ".json")
    path = Path(directory) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    content = canonical(value).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    try:
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("Attempt to overwrite immutable model evidence") from None
    return {"path": relative.as_posix(), "sha256": digest}


def append_model_event(path, row):
    path = Path(path)
    row = dict(row)
    request = {key: row.pop(key) for key in PAYLOAD_FIELDS if key in row}
    if request:
        row["request_payload"] = _store(path.parent, row["request_id"], "request", request)
    if "raw_response" in row:
        row["response_payload"] = _store(path.parent, row["request_id"], "response", row.pop("raw_response"))
    append_jsonl(path, row)


def _read_payload(directory, reference):
    directory = Path(directory).resolve()
    path = (directory / reference["path"]).resolve()
    if not path.is_relative_to(directory / "model_payloads"):
        raise ValueError("Model payload reference escapes its evidence directory")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != reference["sha256"]:
        raise ValueError("Model payload hash mismatch")
    return json.loads(content)


def load_model_events(run_dir):
    path = Path(run_dir)
    if path.is_dir():
        path = path / "model_requests.jsonl"
    if not path.exists():
        return []
    result = []
    requests = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "request_payload" in row:
            payload = _read_payload(path.parent, row["request_payload"])
            prior = requests.setdefault(row["request_id"], payload)
            if prior != payload:
                raise ValueError("Model request payload changed across events")
            row.update(payload)
        elif row.get("request_id") in requests:
            row.update(requests[row["request_id"]])
        if "response_payload" in row:
            row["raw_response"] = _read_payload(path.parent, row["response_payload"])
        result.append(row)
    return result
