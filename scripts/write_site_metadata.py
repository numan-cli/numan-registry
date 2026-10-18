#!/usr/bin/env python3
"""Write public, unsigned publication-build metadata beside the registry site."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def build_metadata(environment: str, revision: str) -> dict[str, str]:
    if environment not in {"production", "staging"}:
        raise ValueError("environment must be production or staging")
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("GITHUB_SHA must be a full commit SHA")
    return {
        "environment": environment,
        "source_revision": revision,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("production", "staging"), required=True)
    parser.add_argument("--output", type=Path, default=Path("registry/publication.json"))
    args = parser.parse_args()
    metadata = build_metadata(args.environment, os.environ.get("GITHUB_SHA", ""))
    args.output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
