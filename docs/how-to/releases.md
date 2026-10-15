# Install and manage Brig releases

Brig releases use stable `X.Y.Z` versions and Git tags such as `v1.0.0`.
The version comes from `src/brig/__init__.py`; package metadata and `brig --version`
read that same value. Project profile versions and agent versions are independent.

## Install a published release

From Linux, as your regular user:

```bash
curl -fsSL https://github.com/HildegarMedina/brig/releases/latest/download/install.sh | bash
```

To select an exact version:

```bash
curl -fsSL https://github.com/HildegarMedina/brig/releases/download/v1.0.0/install.sh | bash
```

The standalone installer downloads the release wheel and `brig-requirements.txt`,
checks both against that release's `SHA256SUMS`, and installs through uv with
those exact dependency constraints. No Git checkout is required. Downloads use
HTTPS; checksums detect damaged or mismatched artifacts, not a compromised
release publisher. The installer itself is trusted code from this repository.

The installer prepares uv, a compatible Python, Docker, and Compose using the
same presentation and platform rules as `scripts/install.sh`. Linux requires
`curl` or `wget` and `sha256sum` (normally included with coreutils). To see details
or install another version using a downloaded installer:

```bash
bash install.sh --verbose
bash install.sh --version 1.0.0
```

The remote URLs become usable when the corresponding GitHub Release is published.
For development, `./scripts/install.sh` still installs the current checkout with
the committed runtime dependency constraints.

## Check and update

```bash
brig --version
brig self check
brig self update
brig self update --version 1.0.0
```

Any normal CLI invocation, including help and version commands, can schedule a
release check. Checks run in a detached background process, so short commands
and unavailable networks do not wait for GitHub. An atomic reservation and file
lock allow only one automatic attempt per 24 hours for the Brig data directory,
shared by all projects. Failed attempts count toward that interval too.

The worker caches the latest stable version. Interactive invocations show an
available-version notice from that cache; a newly fetched result is shown on a
subsequent invocation. Notices go to stderr and are suppressed for redirected
output. The TUI and running agents are not interrupted by background messages.
Explicit `brig self check` and `brig self update` bypass the daily cache and
report failures. No releases are installed automatically.

`brig self update` verifies the downloaded wheel and constraint file before
starting uv. `--version` permits an explicit downgrade or reinstall. Installing a
previous Brig version does not roll back project data formats; consult that
release's compatibility notes. Self-updates do not start Docker, recreate project
containers, switch profiles, or update coding agents. `brig update` continues to
manage the project's coding agents.

## Keep an exact Brig version

```bash
brig self pin
brig self unpin
```

Pinning records the installed version, stops automatic checks/notices, and blocks
`brig self update` from selecting another version. Reinstalling the pinned
version explicitly is allowed. Unpin before upgrading or downgrading. Pinning
also blocks an upgrade if applied while its artifacts are being downloaded.

Settings and the daily cache live in `self-update.json`, next to the Brig state,
with a separate `self-update.lock`. `--data-dir` selects their location as well as
project storage; alternate data directories have independent policy and cache.
These files contain no provider credentials. Setting `BRIG_NO_SELF_UPDATE_CHECK=1`
disables automatic checks without changing saved policy. Explicit self commands
still work. Embedded Python callers using `main(argv)` do not start workers.

## Prepare a release as a maintainer

1. Set `brig.__version__` to the new stable version and update `CHANGELOG.md`.
2. Update `uv.lock` only when dependencies change, and regenerate the runtime
   constraints. The build backend and CI tools are pinned as well:

   ```bash
   uv lock
   uv export --locked --no-dev --no-emit-project --no-hashes --no-annotate --no-header \
     --format requirements.txt --output-file src/brig/release/requirements.txt
   ```

3. Run the required checks and build the exact tagged version locally:

   ```bash
   uv run --locked pre-commit run --all-files
   uv run --locked python scripts/build_release.py --tag v1.0.0
   shellcheck -x dist/release/install.sh
   (cd dist/release && sha256sum --check SHA256SUMS)
   ```

   The builder uses a clean staging tree, checks the wheel metadata and embedded
   lock, and emits only these release files in `dist/release/`:

   - `brig-1.0.0-py3-none-any.whl`
   - `brig-requirements.txt`
   - `install.sh` (all shell helpers embedded)
   - `VERSION`
   - `SHA256SUMS`

4. Review and commit the release changes. When ready to **publish**, create and
   push the matching tag:

   ```bash
   git tag -a v1.0.0 -m 'Brig 1.0.0'
   git push origin v1.0.0
   ```

The release workflow first runs checks on Python 3.12, 3.13, and 3.14, verifies
that the tag matches the package version, and publishes those five assets through
GitHub Releases. It never overwrites an existing release; corrections require a
new version/tag. Enable immutable releases in the GitHub repository settings for
server-enforced protection of published tags and assets. Building locally never
creates a tag, uploads assets, or publishes a release.
