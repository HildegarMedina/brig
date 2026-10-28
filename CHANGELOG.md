# Changelog

## 1.0.0

First stable Brig release.

- Create isolated Docker development environments with pinned project profiles,
  services, and persistent project data.
- Run Claude Code, Codex, and OpenCode with separate credential proxies and shared
  host text clipboard support.
- Attach context files and mount read-only reference projects with agent guidance.
- Install published releases without cloning the repository, with user-local uv
  setup, fixed runtime dependencies, and checksum-verified packages.
- Check for stable Brig updates once every 24 hours in the background. Update
  explicitly, select an exact release, or pin the installed version.
- Provide English, Spanish, and Portuguese interfaces with terminal-friendly
  sailing and shutdown animations.

## 1.0.1

Bug fix release.

- Fix update checks incorrectly prompting to update agents that are not being used.

## 1.0.2

Bug fix release

- Fixed issues with the CLI update command.
