#!/usr/bin/env python3
"""Generate catalog/models.json from the catalog/models.toml template.

Each [[model]] section of the template is merged over [defaults] key-by-key
(per-model values win) and the base prompt is embedded as `base_instructions`
in every model, so the generated models.json is a fully self-contained model
catalog. Codex sends the catalog's `base_instructions` as the system prompt;
the prompt is copied from codex-rs/models-manager/prompt.md (the source of
the fallback metadata Codex uses for models not in any catalog) so the
catalog stays identical to what Codex itself sends.

Usage:
    generate_models.py                       # regenerate catalog/models.json
    generate_models.py --check               # exit 1 if models.json is stale (CI/reminder)
    generate_models.py --template /path/to/models.toml --target /path/to/models.json
    generate_models.py --source /path/to/prompt.md

Prompt source resolution order (first that exists):
  1. --source if given
  2. <repo>/codex-rs/models-manager/prompt.md  (repo = parent of this folder)
  3. catalog/base_instructions.md (last synced copy, in this directory)
catalog/base_instructions.md is rewritten on every generation as the
last-synced copy (diff source of truth).
"""

import argparse
import hashlib
import json
import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.join(HERE, "catalog", "models.toml")
DEFAULT_TARGET = os.path.join(HERE, "catalog", "models.json")
DEFAULT_COPY = os.path.join(HERE, "catalog", "base_instructions.md")
REPO_PROMPT = os.path.normpath(os.path.join(HERE, "..", "codex-rs", "models-manager", "prompt.md"))

NAME_KEYS = ("slug", "display_name", "description")
OPTION_KEYS = (
    "shell_type",
    "visibility",
    "supported_in_api",
    "priority",
    "supported_reasoning_levels",
    "support_verbosity",
    "web_search_tool_type",
    "truncation_policy",
    "context_window",
    "max_context_window",
    "auto_compact_token_limit",
    "effective_context_window_percent",
)
KNOWN_KEYS = set(NAME_KEYS) | set(OPTION_KEYS)
INT_KEYS = (
    "priority",
    "context_window",
    "max_context_window",
    "auto_compact_token_limit",
    "effective_context_window_percent",
)


def fail(message: str) -> None:
    sys.exit(f"error: {message}")


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
    fail(f"no source prompt.md found (tried: {', '.join(candidates)})")


def load_template(path: str) -> dict:
    if not os.path.isfile(path):
        fail(f"template {path} not found")
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        fail(f"cannot parse {path}: {exc}")


def derive_display_name(slug: str) -> str:
    return " ".join(part.title() for part in slug.split("-") if part)


def validate_option_values(label: str, values: dict) -> None:
    for key in INT_KEYS:
        if key in values and (isinstance(values[key], bool) or not isinstance(values[key], int)):
            fail(f"{label}: {key} must be an integer")
    if "supported_in_api" in values and not isinstance(values["supported_in_api"], bool):
        fail(f"{label}: supported_in_api must be a boolean")
    if "supported_reasoning_levels" in values:
        levels = values["supported_reasoning_levels"]
        if not isinstance(levels, list) or not all(isinstance(item, str) for item in levels):
            fail(f"{label}: supported_reasoning_levels must be an array of strings")
    if "truncation_policy" in values and not isinstance(values["truncation_policy"], dict):
        fail(f"{label}: truncation_policy must be a table")


def build_catalog(template: dict, instructions: str, template_path: str) -> dict:
    defaults = template.get("defaults", {})
    if not isinstance(defaults, dict):
        fail("[defaults] must be a table")
    unknown = sorted(set(defaults) - set(OPTION_KEYS))
    if unknown:
        fail(f"unknown key(s) in [defaults]: {', '.join(unknown)} "
             f"(known keys: {', '.join(OPTION_KEYS)})")

    entries = template.get("model")
    if not entries:
        fail(f"no [[model]] sections in {template_path}")
    if not isinstance(entries, list):
        fail("model must be an array of tables")

    seen = set()
    models = []
    for index, entry in enumerate(entries):
        number = index + 1
        if not isinstance(entry, dict):
            fail(f"[[model]] #{number} must be a table")
        label = f"[[model]] #{number}"
        unknown = sorted(set(entry) - KNOWN_KEYS)
        if unknown:
            fail(f"unknown key(s) in {label}: {', '.join(unknown)} "
                 f"(known keys: {', '.join(sorted(KNOWN_KEYS))})")
        slug = entry.get("slug")
        if slug is None:
            fail(f"{label} is missing 'slug'")
        if not isinstance(slug, str) or not slug.strip():
            fail(f"{label}: 'slug' must be a non-empty string")
        label = f"model {slug!r}"
        if slug in seen:
            fail(f"duplicate slug {slug!r}")
        seen.add(slug)

        merged = dict(defaults)
        for key, value in entry.items():
            if key in OPTION_KEYS:
                merged[key] = value
        missing = [key for key in OPTION_KEYS if key not in merged]
        if missing:
            fail(f"{label}: missing required key(s): {', '.join(missing)} "
                 "(set them in [defaults] or this [[model]] section)")
        validate_option_values(label, merged)

        model = {"slug": slug}
        if "display_name" in entry:
            if not isinstance(entry["display_name"], str):
                fail(f"{label}: 'display_name' must be a string")
            model["display_name"] = entry["display_name"]
        else:
            model["display_name"] = derive_display_name(slug)
        if "description" in entry:
            if not isinstance(entry["description"], str):
                fail(f"{label}: 'description' must be a string")
            model["description"] = entry["description"]
        else:
            model["description"] = f"{model['display_name']} model (e-infra)."
        for key in defaults:
            model[key] = merged[key]
        for key in entry:
            if key in OPTION_KEYS and key not in defaults:
                model[key] = merged[key]
        model["base_instructions"] = instructions
        models.append(model)
    return {"models": models}


def render(catalog: dict) -> str:
    return json.dumps(catalog, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", default=DEFAULT_TEMPLATE,
                        help="TOML template (default: %(default)s)")
    parser.add_argument("--source",
                        help="path to prompt.md (default: repo prompt.md, else catalog/base_instructions.md)")
    parser.add_argument("--target", default=DEFAULT_TARGET,
                        help="path to the generated models.json (default: %(default)s)")
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if models.json is out of sync")
    args = parser.parse_args()

    source = resolve_source(args.source)
    with open(source, encoding="utf-8") as f:
        instructions = f.read()
    if not instructions.strip():
        fail(f"source {source} is empty")

    catalog = build_catalog(load_template(args.template), instructions, args.template)
    rendered = render(catalog)

    print(f"source: {source} ({len(instructions.encode('utf-8'))} bytes, "
          f"sha256 {sha256_hex(instructions)[:16]}...)")
    print(f"template: {args.template} ({len(catalog['models'])} models)")

    if args.check:
        problems = []
        if not os.path.isfile(args.target):
            problems.append(f"{args.target} is missing (run ./generate_models.py)")
        else:
            with open(args.target, "rb") as f:
                current = f.read()
            if current != rendered.encode("utf-8"):
                problems.append(f"{args.target} differs from the template (run ./generate_models.py)")
        if not os.path.isfile(DEFAULT_COPY) or open(DEFAULT_COPY, encoding="utf-8").read() != instructions:
            problems.append(f"{DEFAULT_COPY} differs from the current prompt")
        if problems:
            for problem in problems:
                print(f"out of sync: {problem}")
            sys.exit(1)
        print("in sync")
        return

    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.target)), exist_ok=True)
        with open(args.target, "w", encoding="utf-8") as f:
            f.write(rendered)
        # Verify the written file parses.
        with open(args.target, encoding="utf-8") as f:
            json.load(f)
        with open(DEFAULT_COPY, "w", encoding="utf-8") as f:
            f.write(instructions)
    except OSError as exc:
        fail(f"cannot write {exc.filename or args.target}: {exc}")

    print(f"wrote {args.target} ({len(catalog['models'])} models)")
    print(f"refreshed {DEFAULT_COPY}")


if __name__ == "__main__":
    main()
