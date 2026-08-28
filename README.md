# e-infra Codex CLI configuration

Drop-in configuration for running Codex CLI against the e-infra proxy
(`https://llm.ai.e-infra.cz/`) with models such as `qwen3.8-27b`, `gemma4`,
`glm`, `deepseek-thinking`.

```
e-infra-config/
├── config.toml                    # merge into ~/.codex/config.toml (or copy the file next to config.toml)
├── catalog/
│   ├── models.json                # model catalog: context windows + embedded base instructions
│   └── base_instructions.md       # last-synced copy of prompt.md (source of truth for diffs)
├── sync_base_instructions.py      # keeps base_instructions in models.json in sync with prompt.md
└── README.md
```

## Why a custom provider instead of `openai_base_url`

Codex decides compaction strategy from the *provider name*, not the URL
(`codex-rs/model-provider/src/provider.rs`, `capabilities()`):

- name == `"OpenAI"` (case-insensitive) or an Azure-looking base URL
  → `RemoteCompactionSupport::V2`: Codex sends a normal `/responses` request
  and expects the **server** to return a `compaction` output item.
  The e-infra proxy returns ordinary message items, so this fails with
  `remote compaction v2 expected exactly one compaction output item, got 0`,
  and the full context makes every further turn fatal → unusable session.
- any other name → `RemoteCompactionSupport::Unsupported` → **local**
  compaction, i.e. a plain summarization request against your own model.
  This works against any Responses-API endpoint.

Therefore this config defines `[model_providers.e-infra]` (name `"e-infra"`)
and selects it with `model_provider = "e-infra"`. Do **not** set the provider
name to "OpenAI" or the base URL to an Azure-like host, or remote compaction
v2 gets re-enabled.

## Auth

`requires_openai_auth = true` makes Codex reuse the existing
`~/.codex/auth.json` (`"auth_mode": "apikey"`, `"OPENAI_API_KEY": "..."`)
and send it as `Authorization: Bearer`.

Do **not** replace this with `requires_openai_auth = false` + `env_key`
unless you actually set the env var: for providers with
`requires_openai_auth = false`, `resolve_provider_auth`
(`codex-rs/model-provider/src/auth.rs`) attaches **no** auth header unless
`env_key`/`experimental_bearer_token` is configured.

`openai_base_url` from the old config must be removed — it only customizes
the *builtin* `openai` provider, which this setup does not use.

## Context windows and compaction timing

Everything below happens at session/turn start; the effective values are
frozen into the turn context (the `model_context_window` you see in
`token_count` events is this same resolved value).

Per model in `catalog/models.json`:

| field | meaning |
| --- | --- |
| `context_window` | the window the model is given. **Placeholder: 512000 — replace with the real limit.** |
| `max_context_window` | upper bound that clamps any `model_context_window` config override. Set it to the same value as `context_window` unless you want the override to be able to grow the window later. |
| `effective_context_window_percent` | headroom (default 95). Hard cap = `context_window × pct/100`; once `total_tokens` reaches it, compaction is forced regardless of other settings. |
| `auto_compact_token_limit` | auto-compact trigger. Placeholder: 460000. When unset, Codex derives 90% of the window. In the default `total` scope it is min()'d to 90% of `context_window`, so values above that are clamped. |

Rules of thumb:

- **Compact later:** raise `context_window` to the model's real limit (this is
  the main lever — it moves both the hard cap and the derived limit).
- **Compact even later, within the same window:** raise
  `auto_compact_token_limit` up to 90% of `context_window`.
- **To exceed 90% of the window** you must either lower
  `effective_context_window_percent` (e.g. 95 → 98) so the hard cap moves,
  or set `model_auto_compact_token_limit_scope = "body_after_prefix"` in
  config.toml plus a large `model_auto_compact_token_limit` (in that scope
  the config value is not clamped to 90%; only the hard cap remains).
- There is no "disable auto-compaction" switch; the hard cap always fires.
  Set the window to the model's true limit and compaction only happens at the
  edge — which is what you want, since the API would reject larger requests
  anyway.
- Auto-compaction uses **local** summarization with this provider (see above),
  so it costs one sampling request against the model but needs no special
  proxy support.

Global overrides in `config.toml` (applied to the resolved model metadata,
clamped as described above):

```toml
model_context_window = 512000        # optional per-run window override
model_auto_compact_token_limit = 460000
model_auto_compact_token_limit_scope = "total"   # or "body_after_prefix"
```

## Base instructions (system prompt)

Each catalog entry carries the full Codex base instructions in
`base_instructions` (the catalog loader rejects entries that have neither
`base_instructions` nor `model_messages.instructions_template`). The text is
copied from `codex-rs/models-manager/prompt.md` in the Codex source tree —
that file is exactly what Codex sends as the system prompt for models that
are *not* in any catalog (fallback metadata, `BASE_INSTRUCTIONS =
include_str!(prompt.md)` in `codex-rs/models-manager/src/model_info.rs`).
Your models previously hit that fallback path, so syncing from `prompt.md`
keeps the catalog prompt identical to what Codex currently sends for your
model. (Note: the *bundled* catalog entries for GPT-5 models embed a
different, model-specific prompt; do not copy from those.)

To re-sync after updating the Codex source tree (or pulling a new Codex
release), run:

```sh
./sync_base_instructions.py            # update models.json from prompt.md
./sync_base_instructions.py --check    # exit 1 if models.json is stale (CI/reminder)
./sync_base_instructions.py --source /path/to/prompt.md --target /path/to/models.json
```

Source resolution order: `--source`, then
`<parent-of-this-folder>/codex-rs/models-manager/prompt.md` (works when this
folder lives inside a Codex source checkout), then
`catalog/base_instructions.md` (the last synced copy, which also lets you
hand-edit and re-apply a modified prompt).

## Model list

The catalog **replaces** the default model catalog entirely. Every slug you
might select with `-m` (and a `review_model`, if you ever configure one) must
be listed in `catalog/models.json`, otherwise it silently falls back to
272K "fallback metadata" and compacts early again. Add new entries by copying
one of the existing ones; keep the slug exactly as the proxy expects it.

`visibility = "none"` keeps the entries out of the model picker while still
being usable via `-m`. Change to `"list"` if you want them selectable in the
TUI.

## Headers

The builtin `openai` provider sends a `version: <codex version>` header plus
env-backed `OpenAI-Organization` / `OpenAI-Project` headers; these are
mirrored in `http_headers` / `env_http_headers`. The version string here is
the one from the source tree used to generate this config (`0.0.0`) — update
it to your installed Codex version if the proxy validates the header, or drop
`http_headers` if the proxy rejects unknown headers.

## Usage

```sh
# one-time: put this folder's contents next to your config.toml (or copy the
# three settings + [model_providers.e-infra] table into ~/.codex/config.toml;
# remember that model_catalog_json paths are relative to the config file).
codex -m qwen3.8-27b
```

The `-c model_reasoning_summary=none` flag is no longer needed; it is set in
`config.toml` (it also hardens the workaround, since catalog models declare
`supports_reasoning_summary_parameter` defaulting to true — the config value
`none` is what actually suppresses the `reasoning.summary` parameter in
requests, see `codex-rs/core/src/client.rs` `build_reasoning`).
