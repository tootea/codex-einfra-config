# codex-einfra catalog

The e-infra model catalog used by the `codex-einfra` package. This directory
is a standalone git repository: the `bin/codex` wrapper clones it into
`$CODEX_HOME/einfra-config` (default `~/.codex/einfra-config`) and points
`model_catalog_json` at `catalog/models.json` from there.

```
einfra-config/
├── catalog/
│   ├── models.toml           # template: [defaults] + one [[model]] per model
│   ├── models.json           # generated model catalog (committed; Codex reads this)
│   └── base_instructions.md  # last-synced copy of the Codex base prompt
├── generate_models.py        # regenerates models.json from models.toml + the prompt
└── README.md
```

## Customizing models

Edit `catalog/models.toml` (add/adjust `[[model]]` sections — a bare `slug`
is enough for pure defaults), regenerate, and commit:

```sh
./generate_models.py            # rewrite catalog/models.json
./generate_models.py --check    # exit 1 if models.json is stale (CI)
git add -A && git commit -m "..."
```

- Slugs must match exactly what the proxy expects (`-m <slug>`).
- `visibility = "none"` (the default) keeps entries out of the model picker
  while remaining usable via `-m`; use `"list"` to expose them in the TUI.
- The catalog **replaces** the default model catalog entirely: any model you
  want selectable must be listed here.

To sync the base prompt after a Codex upgrade, update
`catalog/base_instructions.md` from the Codex source tree
(`codex-rs/models-manager/prompt.md`) and regenerate.

## Upstream updates

Upstream commits are picked up automatically on the **next codex-einfra
package version bump** (the wrapper fetches only then) or any time via:

```sh
git -C ~/.codex/einfra-config pull
```

If you have local commits when upstream advanced, the wrapper prints the
`git rebase @{u}` steps for `~/.codex/einfra-config` and — on a TTY — waits
for Enter before launching so you can read them (codex clears the terminal
on start).

## Provider configuration

The `[model_providers.einfra]` table and the `model_provider` /
`model_catalog_json` root keys are **not** in this repo — they are maintained
in the package's `managed-config.toml` and synced into
`$CODEX_HOME/config.toml` by the wrapper (delimited "codex-einfra managed"
regions; everything else in your `config.toml` is untouched).
