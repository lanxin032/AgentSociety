"""One frozen, official-first execution profile; historical profiles are rejected."""
from copy import deepcopy
import hashlib
import json

from .providers import provider_route

SCHEMA_VERSION = "native-tools-profile-4"
EXECUTION_POLICY = "official-finite-4"
PURPOSES = ("agent_decision", "environment_routing", "memory", "policy_A", "policy_C")
MODEL = "deepseek-flash"


def make_profile(thinking="disabled", *, provider=None):
    if thinking != "disabled":
        raise ValueError("The current experiment freezes thinking disabled")
    route = provider_route(provider)
    return {
        "schema_version": SCHEMA_VERSION, "framework_version": "2.8.7",
        "execution_policy": EXECUTION_POLICY, "agent_thinking": "disabled",
        "model": route["model"], "provider_route": route,
        "max_tokens": 16384, "temperature": 0.2,
        "upstream_timeout_seconds": 600, "client_timeout_seconds": 660,
        "max_react_turns": 10, "router_kind": "deterministic_dispatch", "memory_enabled": True,
        "todo_enabled": False, "memory_context_max_chars": 4000,
        "recent_memory_limit": 8, "memory_consolidation_pending_threshold": 10,
        "memory_consolidation_interval_steps": 8,
        "memory_high_importance_threshold": 0.75,
        "workload_mode": "finite", "prompt_version": "official-native-16",
        "token_metric": "T_system", "max_material_reads_per_round": None,
    }


def is_profile(profile):
    return isinstance(profile, dict) and profile.get("schema_version") == SCHEMA_VERSION


def validate_profile(profile):
    if not is_profile(profile):
        raise ValueError("Unsupported execution profile; old runs cannot be resumed")
    try:
        expected = make_profile(profile["agent_thinking"],
                                provider=profile["provider_route"]["provider"])
        if json.dumps(profile, sort_keys=True) != json.dumps(expected, sort_keys=True):
            raise ValueError("Profile differs from the frozen current protocol")
    except (KeyError, TypeError) as exc:
        raise ValueError("Malformed execution profile") from exc
    return deepcopy(expected)


def profile_digest(profile):
    return hashlib.sha256(json.dumps(validate_profile(profile), sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def settings_for_purpose(profile, purpose="agent_decision"):
    profile = validate_profile(profile)
    if purpose not in PURPOSES:
        raise ValueError("Unknown model request purpose")
    result = {"model": profile["model"], "max_tokens": profile["max_tokens"],
              "temperature": profile["temperature"], "thinking": {"type": "disabled"}}
    if purpose in ("policy_A", "policy_C"):
        result["response_format"] = {"type": "json_object"}
    return result


def validate_payload(payload, profiles, purpose=None, expected_digest=None):
    if purpose not in PURPOSES or not expected_digest:
        raise ValueError("Payload requires explicit purpose and profile digest")
    profile = next((p for p in profiles if profile_digest(p) == expected_digest), None)
    if profile is None:
        raise ValueError("Request profile is not authorized")
    settings = settings_for_purpose(profile, purpose)
    allowed = set(settings) | {"messages", "stream", "n", "tools", "tool_choice"}
    if not isinstance(payload, dict) or set(payload) - allowed or any(payload.get(k) != v for k, v in settings.items()):
        raise ValueError("Wire settings differ from frozen profile")
    if payload.get("stream", False) is not False or payload.get("n", 1) != 1:
        raise ValueError("Only one nonstreaming completion is supported")
    if purpose not in ("agent_decision", "environment_routing") and ("tools" in payload or "tool_choice" in payload):
        raise ValueError("Memory and policy services cannot use tools")
    return settings
