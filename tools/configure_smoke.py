"""Receive a test API key through a hidden prompt and save it on the cloud only."""

import getpass
import os
from pathlib import Path
import sys


def main():
    if not sys.stdin.isatty():
        raise SystemExit("A real terminal is required for hidden key entry.")
    target = Path(__file__).resolve().parents[1] / ".env.smoke"
    if target.exists():
        raise SystemExit("Existing .env.smoke was not overwritten.")
    key = getpass.getpass("LLM API key (input hidden): ").strip()
    if len(key) < 16 or any(character.isspace() for character in key):
        raise SystemExit("API key format is invalid; nothing was saved.")
    if any(character in key for character in "'\"\\"):
        raise SystemExit("Unsupported key characters; nothing was saved.")
    content = (
        f"AGENTSOCIETY_LLM_API_KEY={key}\n"
        "AGENTSOCIETY_LLM_API_BASE=https://llmapi.fiblab.net/v1\n"
        "AGENTSOCIETY_LLM_MODEL=deepseek-v4-flash\n"
        "AGENTSOCIETY_EMBEDDING_MODEL=bge-m3\n"
    )
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(content)
    print("Saved cloud-only .env.smoke with permissions 0600; no API call was made.")


if __name__ == "__main__":
    main()
