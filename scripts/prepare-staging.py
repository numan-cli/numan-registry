#!/usr/bin/env python3
"""Combine the production catalog and quarantined candidates for staging only."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


def package_id(package: dict) -> tuple[str, str]:
    return package["id"]["owner"], package["id"]["name"]


def merge_catalogs(production: dict, provisional: dict) -> dict:
    if production.get("schema_version") != 1 or provisional.get("schema_version") != 1:
        raise ValueError("both catalogs must use schema version 1")
    merged = copy.deepcopy(production)
    packages = {package_id(package): package for package in merged["packages"]}
    if len(packages) != len(merged["packages"]):
        raise ValueError("duplicate package ID in production catalog")
    seen = set()
    for candidate in provisional["packages"]:
        ident = package_id(candidate)
        if ident in seen:
            raise ValueError(f"duplicate package ID in provisional catalog: {ident}")
        seen.add(ident)
        if ident not in packages:
            package = copy.deepcopy(candidate)
            candidate_versions = [v["version"] for v in package["versions"]]
            if len(candidate_versions) != len(set(candidate_versions)):
                raise ValueError(f"new candidate package has duplicate versions: {ident}")
            merged["packages"].append(package)
            packages[ident] = package
            continue
        package = packages[ident]
        if package["type"] != candidate["type"] or package["repo"] != candidate["repo"]:
            raise ValueError(f"candidate changes package identity/type: {ident}")
        versions = {version["version"] for version in package["versions"]}
        for version in candidate["versions"]:
            if version["version"] in versions:
                raise ValueError(f"candidate would overwrite an existing version: {ident}@{version['version']}")
            versions.add(version["version"])
            package["versions"].append(copy.deepcopy(version))
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", type=Path, default=Path("registry/index.json"))
    parser.add_argument("--provisional", type=Path, default=Path("registry/provisional.json"))
    parser.add_argument("--output", type=Path, required=True, help="Staging output path; source catalogs are never overwritten")
    args = parser.parse_args()
    if args.output.resolve() in {args.production.resolve(), args.provisional.resolve()}:
        parser.error("output must differ from both source catalogs")
    merged = merge_catalogs(json.loads(args.production.read_text(encoding="utf-8")), json.loads(args.provisional.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Prepared {len(merged['packages'])} staging packages at {args.output}")


if __name__ == "__main__":
    main()
