# Choose your interface language

Brig offers English (`en`), Spanish (`es`), and Portuguese (`pt`) for the terminal
interface, CLI help, summaries, progress messages, and errors written by Brig.

## Save a preference

Open `brig`, switch to Settings with Left/Right or Tab, and press Enter. Choose
English, Español, Português, or Automatic. The dashboard updates immediately.
The same preference can be saved from a noninteractive terminal:

```bash
brig language es
brig language pt
brig language en
```

To display the active language:

```bash
brig language
```

Preferences apply to the current Brig data directory. Use
`brig --data-dir DIRECTORY language es` to keep a separate preference for another
workspace. Changing the language does not create profiles, register projects,
install anything, or contact Docker.

## Override it temporarily

```bash
brig --lang es --help
brig --lang pt profile list
BRIG_LANG=es brig project list
```

Global options, including `--lang`, go before the command. These overrides do not
rewrite the saved preference. The selection order is:

1. `--lang en`, `--lang es`, or `--lang pt`.
2. `BRIG_LANG`.
3. Your saved preference.
4. Terminal locale: the first nonempty `LC_ALL`, `LC_MESSAGES`, or `LANG`.
5. English when the selected locale is unsupported.

Locale variants such as `es_ES.UTF-8`, `es-MX`, `pt_BR.UTF-8`, and `pt-PT` select
their language. Portuguese uses one shared catalog for these variants.
An unsupported `BRIG_LANG` value is ignored. POSIX locale precedence is respected:
a nonempty unsupported `LC_ALL` selects English even if `LANG` names a supported
language. If an environment override is set, it also takes precedence over a
saved choice made in Settings.

## Return to automatic selection

```bash
brig language auto
```

Remove `BRIG_LANG` if you also want to follow the terminal locale. Automatic mode
is the default when no preference is saved.

## What stays the same

Commands and options still use their original names: `brig profile create`,
`brig project list`, and `--project`, for example. Names you choose for profiles
and projects, YAML fields, pinned releases, resource names, and generated Docker
configuration remain unchanged. Existing snapshots do not change when you
switch languages.

Output produced by Docker, application commands, agents, operating system errors,
and upstream services can use their own language. Brig translates its surrounding
messages. Documentation in the repository remains in English.

If Brig reports invalid language preferences, keep a copy of `preferences.json`
from your data directory and replace the preference explicitly, for example:

```bash
brig --lang en language es
```

This replaces only the interface preference and preserves environment definitions.
