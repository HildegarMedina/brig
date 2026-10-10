# Share and import profiles

Use this to move an environment definition to another machine or reuse a team's
profiles. Import registers profiles only; it does not register projects, install
components, build images, or start Docker. Docker and internet are unnecessary
for import.

## Share saved YAML

Find your profile documents under:

```text
${XDG_DATA_HOME:-~/.local/share}/brig/profiles/profile-NAME/versions/
```

Folder names encode special characters. If you use `--data-dir`, look under that
directory instead. Each `version-N.yaml` contains one immutable version. Copy the
profile folder to share its history. For inherited profiles, also copy the base
profile folders and any ancestors. Each child's `extends` names a specific base
version, and its other sections contain the full resolved configuration.

Share only the needed profile folders, not your entire Brig data directory,
which also contains project registrations and engine artifacts.

## Import files or folders

```bash
brig profile import ./shared-profiles/
brig profile import ./base/versions/ ./child/versions/
brig profile import ./python-dev.yaml
brig profile list
```

You can combine files and folders. Folder scans include nested `.yaml` and `.yml`
files. File order does not matter: Brig sorts histories and resolves inherited
references across the whole batch and the profiles already saved locally.
It does not search outside the supplied folders or download missing bases.

For a new profile, provide all versions starting at 1. If version 1 is already
saved, importing version 2 alone appends it. Importing version 3 into a new
installation requires versions 1 and 2 as well. A child referencing base version
2 therefore needs the base's versions 1 and 2, unless they are already local.

Successful output reports the number of imported and already-present versions.
Running the same import again skips identical versions. Names, version numbers,
and fixed base references are preserved. Existing projects keep their snapshots;
use `brig project update NAME` separately to adopt their profile's latest version
when the environment is stopped.

## Prepare a YAML definition

A file contains one UTF-8 YAML mapping, up to 1 MiB. Current documents require
`schema_version: 2`, `name`, a positive integer `version`, `runtimes`, `tools`,
`databases`, `caches`, and `agent`. Optional fields are `agents` and `extends`.
Use `{}` for empty component sections and quote component release strings.
At least one runtime is required. The default agent must be in the selected
agents; omitting `agents` selects only `agent` for legacy compatibility.

See the [profile format](../reference/components.md#profile-format) for a complete
example. Older schema 1 documents are accepted and saved in the current format.
Source files stay unchanged; imported YAML is rendered in Brig's standard layout.

Duplicate keys, unknown fields, aliases, multiple documents in one file, and
custom object tags are rejected. Database and cache components must be in their
corresponding sections. Inherited definitions must preserve the base's components
and agents; they may add components but cannot override or remove inherited ones.

Import validates registered components, selections, histories, and inheritance
offline. It does not verify that old releases remain downloadable from upstream;
building the environment can still fail if a pinned release is unavailable.

## Resolve rejected imports

- **Missing version:** include the earlier YAML documents in the same command.
- **Unknown base or version:** include the referenced base's history and ancestors,
  or import those first.
- **Different configuration at an existing version:** existing versions cannot be
  overwritten. Restore the original document or add the intended changes as the
  next version. Keep its preceding history available.
- **Name conflict:** use the same capitalization as the existing profile, or give
  the imported profile a distinct name and update its inherited references.
- **Invalid inheritance:** fix missing references, cycles, or overridden inherited
  selections before importing again.

A rejected batch leaves existing definitions and project snapshots intact. A save
failure also preserves the previous state and removes newly written version
files. Brig does not partially import valid files from a rejected batch.
