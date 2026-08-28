#!/usr/bin/env python3
"""Sync the base instructions embedded in catalog/models.json from prompt.md.

Codex sends the model's `base_instructions` (from the model catalog) as the
system prompt. The fallback metadata Codex uses for unknown models is generated
from codex-rs/models-manager/prompt.md, and the bundled catalog embeds the same
text. This script copies the current prompt.md content into the
`base_instructions` field of every model in models.json (and refreshes
catalog/base_instructions.md) so the catalog stays in sync with what Codex
itself ships.

Usage:
    sync_base_instructions.py                      # defaults, prints summary
    sync_base_instructions.py --check              # exit 1 if out of sync
    sync_base_instructions.py --source /path/to/prompt.md --target /path/to/models.json

Source resolution order (first that exists):
  1. --source if given
  2. <repo>/codex-rs/models-manager/prompt.md  (repo = 2 levels up from here)
  3. catalog/base_instructions.md (last synced copy, in this directory)
"""

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TARGET = os.path.join(HERE, "catalog", "models.json")
DEFAULT_COPY = os.path.join(HERE, "catalog", "base_instructions.md")
REPO_PROMPT = os.path.normpath(os.path.join(HERE, "..", "codex-rs", "models-manager", "prompt.md"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_source(explicit: str | None) -> str:
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates.append(REPO_PROMPT)
    candidates.append(DEFAULT_COPY)
    for path in candidates:
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    sys.exit(f"error: no source prompt.md found (tried: {', '.join(candidates)})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="path to prompt.md (default: repo prompt.md, else catalog/base_instructions.md)")
    parser.add_argument("--target", default=DEFAULT_TARGET, help="path to models.json (default: %(default)s)")
    parser.add_argument("--check", action="store_true", help="do not write; exit 1 if models.json is out of sync")
    args = parser.parse_args()

    source = resolve_source(args.source)
    with open(source, encoding="utf-8") as f:
        instructions = f.read()
    if not instructions.strip():
        sys.exit(f"error: source {source} is empty")

    with open(args.target, encoding="utf-8") as f:
        catalog = json.load(f)
    models = catalog.get("models")
    if not models:
        sys.exit(f"error: {args.target} contains no models")

    out_of_date = [m["slug"] for m in models if m.get("base_instructions") != instructions]
    copy_out_of_date = not os.path.isfile(DEFAULT_COPY) or sha256_hex(
        open(DEFAULT_COPY, encoding="utf-8").read()
    ) != sha256_hex(instructions)

    print(f"source: {source} ({len(instructions)} bytes, sha256 {sha256_hex(instructions)[:16]}...)")
    print(f"target: {args.target} ({len(models)} models)")

    if args.check:
        if out_of_date or copy_out_of_date:
            if out_of_date:
                print(f"out of sync: {', '.join(out_of_date)}")
            if copy_out_of_date:
                print("out of sync: catalog/base_instructions.md")
            sys.exit(1)
        print("in sync")
        return

    updated = 0
    for model in models:
        if model.get("base_instructions") != instructions:
            model["base_instructions"] = instructions
            updated += 1

    with open(args.target, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)
        f.write("\n")
    # Verify the written file parses.
    with open(args.target, encoding="utf-8") as f:
        json.load(f)

    with open(DEFAULT_COPY, "w", encoding="utf-8") as f:
        f.write(instructions)

    print(f"updated base_instructions in {updated} model(s); refreshed catalog/base_instructions.md")


if __name__ == "__main__":
    main()
