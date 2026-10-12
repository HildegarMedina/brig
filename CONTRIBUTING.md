# Contributing to Brig

You can help with bug reports, documentation, translations, tests, and code.
Small, focused contributions are welcome. For a substantial feature or a change
to stored profiles, commands, or security behavior, open an issue first to explain
the problem and proposed approach.

## Report a problem or suggest a feature

Include what you expected, what happened, and the steps to reproduce it. For bugs,
include your Brig version, Linux distribution, relevant profile selections, and
Docker/Compose versions when applicable. Share a minimal example and sanitized
error output; remove tokens, passwords, private project paths, and personal data.

For feature requests, describe the task you need to complete and how the current
behavior gets in the way. Documentation corrections and translation improvements
can go directly to a pull request.

## Prepare a development checkout

You need Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).
From your clone:

```bash
./scripts/install_pre_commit.sh
uv run --locked brig --help
uv run --locked brig --data-dir /tmp/brig-development
```

The script installs locked dependencies, activates the Git hook, and runs checks.
Use a separate data directory while developing to keep your regular Brig
registrations and logins separate. Commands that start environments still use
real Docker; this is not a simulation mode.

Unit tests do not require Docker or external provider accounts. The HTTPS proxy
test uses local loopback sockets and fixture credentials. Docker Engine and
Compose are needed for real environment testing.

## Make and verify a change

1. Create a branch and keep the change focused on one problem.
2. Reuse shared application behavior between CLI and TUI. Keep modules focused
   on one responsibility and preserve stored profile versions and project data.
3. Add meaningful tests for changed behavior and failure paths. Use fixture
   credentials; never commit real tokens or use normal login volumes in tests.
4. Update the relevant documentation with the code. Keep docs in English and
   the README focused on the user's tutorial. Add Spanish and Portuguese catalog
   entries when introducing interface messages.
5. Run the required checks and review any automatic Ruff changes:

   ```bash
   uv run --locked pre-commit run --all-files
   ```

The hook runs Ruff lint/format and the unit suite with mandatory **100% line
coverage** across `src/brig`. Do not omit modules or bypass checks to make a
change pass. A documentation-only commit also runs the configured checks.

For changes to images, mounts, agent execution, or service persistence, also run
Docker integration tests when Docker is available:

```bash
BRIG_DOCKER_TESTS=1 uv run --locked python -m unittest tests.integration.test_lifecycle tests.integration.test_agents -v
```

These tests build images and create temporary Docker resources. Native provider
login and inference need separate end-to-end validation with suitable accounts;
fixture tests do not establish provider compatibility.

See [development and maintenance](docs/development.md) for architecture, component
extension points, translations, and test details.

## Submit a pull request

Explain the problem, the resulting behavior, and how you verified it. Include
reproduction steps for a fix and terminal screenshots when they help review a UI
change. State which checks you ran and which remain untested.

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) for
commit messages, for example `fix(ui): preserve selection after refresh` or
`docs: clarify profile inheritance`. Mark incompatible changes with `!` or a
`BREAKING CHANGE` footer and document migration steps. Avoid unrelated formatting
or generated changes in a pull request.

## Suggested work

These are contribution ideas, not promised features or a scheduled release plan.
Check existing issues and discuss the scope before starting a larger task.

| Priority | Task | Useful outcome |
| --- | --- | --- |
| High | Validate native login and inference for Codex, Claude, and OpenCode through the credential proxy | Reproducible checks for login, renewal, streaming, and container recreation |
| High | Expand credential boundary tests | Verify malformed requests, provider changes, concurrent refresh, and failure recovery without exposing secrets |
| High | Exercise Docker lifecycle and upgrades on supported Linux hosts | Confirm installer behavior, UID/GID ownership, migration, and persistent data |
| Medium | Improve startup and authentication diagnostics | Make failures actionable while keeping credentials out of output |
| Medium | Review English, Spanish, and Portuguese UI text | Consistent terminology, preserved format fields, and readable narrow-terminal help |
| Medium | Test terminal accessibility and compatibility | Check keyboard navigation, small terminals, ASCII fallback, and `NO_COLOR` |
| Medium | Add tested profile examples and walkthroughs | Practical PHP, Python, and Node.js setups with inheritance and optional services |
| Explore | Support more protected authentication providers | Define exact endpoints, credential handling, and real compatibility tests before adding an adapter |
| Explore | Add application startup and port-publishing workflows | Agree on user-facing behavior and network exposure before implementation |

For a first contribution, a reproducible bug report, tutorial correction,
translation review, or focused regression test is a good place to start.
