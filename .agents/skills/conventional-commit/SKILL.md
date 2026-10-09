---
name: conventional-commits
description: Write, review and fix commit messages following the Conventional Commits 1.0.0 specification (feat, fix, BREAKING CHANGE, scopes, footers) and its mapping to SemVer. Use this skill whenever the user asks to write, suggest, improve or validate a commit message, shares a diff or a list of changes and wants "the commit", asks which commit type to use, which SemVer bump a set of commits implies, or how to flag a breaking change, or mentions commitlint, automated changelogs, semantic-release or "conventional commits", even if they don't name the specification explicitly.
---

# Conventional Commits 1.0.0

This skill produces and reviews commit messages that comply with the
[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) specification.
The point of the convention is a history that both humans and tools can read: automatic
CHANGELOG generation, computing the next SemVer version, and triggering build/publish
pipelines. That's why structure matters more than style: a nicely worded but malformed
message gets skipped by tooling.

The full list of normative rules (all 16 from the spec, with their MUST/MAY level) lives in
`references/spec.md`. Read it when you need to justify a correction or settle an edge case
(multi-line footers, BREAKING CHANGE synonyms, casing, etc.).

## Structure

```
<type>[optional scope][!]: <description>

[optional body]

[optional footer(s)]
```

- **type**: a noun classifying the change. Required.
- **scope**: a noun in parentheses naming the affected section of the codebase, e.g. `fix(parser):`.
- **`!`**: immediately before the colon, flags a breaking change.
- **`: `**: colon plus one space, required.
- **description**: short summary right after `: `.
- **body**: free-form text, one or more paragraphs, separated from the description by **one blank line**.
- **footers**: separated from the body by a blank line; each is `Token: value` or `Token #value`, in the style of git trailers.

## Types

Only two types have meaning defined by the spec, and they are mandatory when they apply:

| Type | When | SemVer effect |
|---|---|---|
| `feat` | Adds a new feature | MINOR |
| `fix` | Fixes a bug | PATCH |

Any other type is allowed. The most common ones (Angular convention / `@commitlint/config-conventional`):

| Type | Typical use |
|---|---|
| `docs` | Documentation only |
| `style` | Formatting, whitespace, semicolons; no logic change |
| `refactor` | Restructures code without fixing bugs or adding features |
| `perf` | Performance improvement |
| `test` | Adding or fixing tests |
| `build` | Build system or dependencies |
| `ci` | Continuous integration config |
| `chore` | Maintenance that doesn't touch source or tests |
| `revert` | Reverts earlier commits |

These extra types **have no effect on the version** unless they include a BREAKING CHANGE.
If the repository already uses its own set of types (check `git log`, `commitlint.config.*`,
`.czrc` or the contributing guide), follow that over this table.

## Breaking changes

A breaking change can appear in a commit of **any** type and always means MAJOR. There are
two ways to flag it, and they can be combined:

1. `!` before the colon: `feat(api)!: remove /v1/users endpoint`. The description must then explain the break, and the footer may be omitted.
2. An uppercase footer: `BREAKING CHANGE: <explanation>` (or its synonym `BREAKING-CHANGE:`).

Use both when the break deserves a detailed explanation: the `!` makes it visible in
`git log --oneline`, and the footer explains what changed and how to migrate.

## Writing a commit

1. **Understand the change.** If there's a diff, read it; if there's only a description, work from that. Only ask when you can't decide between `feat` and `fix` or can't tell whether it breaks compatibility, since those determine the version.
2. **Check it's a single change.** If the diff mixes, say, a feature and an unrelated fix, recommend splitting it into several commits (the spec explicitly suggests this) and propose a message for each part.
3. **Pick the type** from the table. Common doubt: a change the user perceives as new behavior is `feat`; one that corrects wrong behavior is `fix`; one with no observable change is `refactor`/`perf`/`chore`.
4. **Pick a scope** if it adds information (module, package, component). Reuse the vocabulary already in the repo's history. Leave it out for cross-cutting changes.
5. **Decide whether it's breaking**: removed or renamed public APIs, signature changes, config formats, minimum runtime versions, changed default behavior.
6. **Write the description**: short (aim for a first line of ≤ 72 characters for git tooling), imperative mood ("add", "fix", not "added"/"fixes"), no trailing period. Use the language of the repo's existing history; if unknown, write in English.
7. **Add a body** only when the *why* or *how* isn't obvious: motivation, context, rejected alternatives. Wrap lines at ~72 characters.
8. **Add footers** for references (`Refs: #123`, `Closes #45`), co-authors (`Co-authored-by: ...`), reviews (`Reviewed-by: ...`) and `BREAKING CHANGE:`. Tokens use hyphens instead of spaces (except `BREAKING CHANGE`).
9. **Validate** with `scripts/validate_commit.py` when you can run code (see below).

Deliver the message in a code block so it can be copied as-is. If there are nuances (uncertain type, possible break), explain them in one or two sentences outside the block.

## Reviewing an existing commit

1. Validate it with the script or against `references/spec.md`.
2. Separate **errors** (violations of a MUST: missing `: `, lowercase `breaking change` footer, body without a blank line, `feat` used for a bug) from **suggestions** (style: length, imperative mood, a more precise scope). Don't present a style suggestion as a spec violation.
3. Propose the full corrected version.

## Computing the version from commits

Given the commits since the last release, the bump is the largest one present:

- Any BREAKING CHANGE (`!` or footer) → **MAJOR**
- Otherwise, any `feat` → **MINOR**
- Otherwise, any `fix` → **PATCH**
- Only other types → no new version required by the spec (the project's release tool may have its own policy).

For projects at `0.y.z`: many tools (e.g. semantic-release, release-please) apply their own rules in that phase; mention this when relevant instead of assuming.

## Validator

`scripts/validate_commit.py` checks a message's structure against the spec and reports errors and warnings:

```bash
python scripts/validate_commit.py "feat(api)!: drop v1 endpoints"
python scripts/validate_commit.py --file COMMIT_EDITMSG
echo "fix: typo" | python scripts/validate_commit.py -
python scripts/validate_commit.py --types feat,fix,docs,chore "chore: bump deps"
python scripts/validate_commit.py --json "feat: x"
```

It exits 0 when there are no errors (warnings don't fail) and 1 otherwise, so it also works as a `commit-msg` hook:

```bash
#!/bin/sh
python /path/to/validate_commit.py --file "$1"
```

## Negative Prompt
Dont use CO-Authored line.

## Examples

**New feature with scope**
```
feat(lang): add Polish language
```

**Fix with body and multiple footers**
```
fix: prevent racing of requests

Introduce a request id and a reference to the latest request. Dismiss
incoming responses other than those from the latest request.

Remove timeouts that were used to mitigate the race; they are obsolete.

Reviewed-by: Z
Refs: #123
```

**Breaking change with `!` and explanatory footer**
```
feat(config)!: let extends key inherit from other config files

BREAKING CHANGE: the `extends` key is now used to extend other config
files. Move any custom value it held to the new `preset` key.
```

**Revert**
```
revert: let us never again speak of the noodle incident

Refs: 676104e, a215868
```

**Fixing a malformed message**

Input: `Fixed the login bug.`
Output: `fix(auth): handle expired session tokens on login`
Why: the type followed by `: ` is missing; also, use imperative mood, no trailing period, and a description that says what was fixed.

Input: `feat: new API` + footer `breaking change: removed old routes`
Output: footer `BREAKING CHANGE: remove /v1 routes; use /v2 instead`
Why: as a footer, BREAKING CHANGE must be uppercase for tools to detect it.