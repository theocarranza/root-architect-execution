#!/usr/bin/env python3
"""Fail-closed, offline feasibility record for bounded host acceptance.

This command deliberately has no model-launch implementation.  A live request
is refused until a Codex transport can prove it enforces both supplied limits.
"""

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def sha256(path):
    """Return a source-artifact digest without reading user configuration."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local_evidence():
    """Collect only repository and executable-discovery facts; never user config."""
    interface = ROOT / "adapters" / "codex" / "agent-interface.json"
    host = ROOT / "hosts" / "codex.json"
    executable = shutil.which("codex")
    return {
        "executable": {
            "availability": "available" if executable else "unavailable",
            "name": "codex",
            "version": "unknown",
            "version_reason": "not executed by this offline probe",
        },
        "configuration": {
            "source_artifacts": {
                "adapters/codex/agent-interface.json": sha256(interface),
                "hosts/codex.json": sha256(host),
            },
            "user_configuration": "not_read",
        },
    }


def record(arguments):
    """Build the durable truth for a trial that was deliberately not launched."""
    return {
        "host": arguments.host,
        "scenario": arguments.scenario,
        "status": "blocked",
        "live_trial": "not_run",
        "model_invoked": False,
        "blocker": {
            "capability": "max_tokens",
            "reason": "No verified Codex transport can enforce the requested token limit.",
        },
        "blockers": [
            {
                "capability": "max_seconds",
                "reason": "No verified Codex transport can enforce the requested time limit.",
            },
            {
                "capability": "max_tokens",
                "reason": "No verified Codex transport can enforce the requested token limit.",
            },
        ],
        "limits": {
            "max_seconds": arguments.max_seconds,
            "max_tokens": arguments.max_tokens,
            "time_enforcement": "unknown",
            "token_enforcement": "unknown",
        },
        "identities": {"root": "unknown", "orchestrator": "unknown", "worker": "unknown"},
        "events": "not_run",
        "observed_events": [],
        "local_evidence": local_evidence(),
    }


def positive_integer(value):
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, choices=("codex",))
    parser.add_argument("--scenario", required=True, choices=("capability-probe",))
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--max-seconds", required=True, type=positive_integer)
    parser.add_argument("--max-tokens", required=True, type=positive_integer)
    return parser.parse_args(argv)


def main(argv=None):
    parsed = arguments(argv)
    print(json.dumps(record(parsed), sort_keys=True))
    # A requested live run is a failed acceptance attempt, never an offline pass.
    return 2 if parsed.require_live else 0


if __name__ == "__main__":
    sys.exit(main())
