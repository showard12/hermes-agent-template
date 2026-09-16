#!/usr/bin/env python3
"""Merge the Pantryfy PR webhook route into Hermes' persistent config."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml


HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/data/.hermes"))
CONFIG_PATH = HERMES_HOME / "config.yaml"
SECRET = os.environ.get("HERMES_GITHUB_WEBHOOK_SECRET", "").strip()


def main() -> int:
    if not SECRET:
        return 0

    config: dict = {}
    if CONFIG_PATH.exists():
        loaded = yaml.safe_load(CONFIG_PATH.read_text())
        if isinstance(loaded, dict):
            config = loaded

    platforms = config.setdefault("platforms", {})
    webhook = platforms.setdefault("webhook", {})
    webhook["enabled"] = True
    extra = webhook.setdefault("extra", {})
    extra.update(
        {
            "host": "127.0.0.1",
            "port": 8644,
            "rate_limit": 30,
            "max_body_bytes": 1048576,
        }
    )
    routes = extra.setdefault("routes", {})
    routes["github-pr-review"] = {
        "secret": SECRET,
        "events": ["pull_request"],
        "filters": [
            {"field": "repository.full_name", "equals": "showard12/pantry_app"},
            {
                "field": "action",
                "in": ["opened", "reopened", "synchronize", "ready_for_review"],
            },
            {"field": "pull_request.draft", "equals": False},
        ],
        "coalesce": {
            "key": "{repository.full_name}#{pull_request.number}",
            "window_seconds": 30,
            "max_wait_seconds": 120,
        },
        "toolsets": ["terminal"],
        "skills": ["pantryfy-pr-review"],
        "prompt": (
            "GitHub pull_request event for showard12/pantry_app: action={action}, "
            "PR=#{number}, URL={pull_request.html_url}. Follow the loaded "
            "pantryfy-pr-review skill."
        ),
        "deliver": "github_comment",
        "deliver_extra": {
            "repo": "showard12/pantry_app",
            "pr_number": "{number}",
        },
    }

    CONFIG_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="config.yaml.", dir=CONFIG_PATH.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            yaml.safe_dump(config, handle, sort_keys=False, default_flow_style=False)
        os.replace(temp_name, CONFIG_PATH)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    os.chmod(CONFIG_PATH, 0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
