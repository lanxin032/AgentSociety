"""Public, frozen upstream routes. Credentials never belong in this module."""
from copy import deepcopy

_ROUTES = {
    "competition": {"provider": "competition", "base_url": "https://llmapi.fiblab.net/v1", "model": "deepseek-v4-flash"},
    "deepseek_official": {"provider": "deepseek_official", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-flash"},
}


def provider_route(provider=None):
    name = "deepseek_official" if provider is None else provider
    if not isinstance(name, str) or name not in _ROUTES:
        raise ValueError("Unknown approved upstream provider")
    return deepcopy(_ROUTES[name])


def validate_route(route):
    if not isinstance(route, dict) or route != provider_route(route.get("provider")):
        raise ValueError("Upstream route differs from its approved provider")
    return deepcopy(route)


def authorization_route(authorization):
    return validate_route(authorization["provider_route"]) if "provider_route" in authorization else provider_route()


def secret_filename(route):
    return ".env.deepseek" if validate_route(route)["provider"] == "deepseek_official" else ".env"
